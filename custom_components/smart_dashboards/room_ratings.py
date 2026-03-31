"""Per-room efficiency ratings persisted under ``config/data``; hourly recompute + engagement heartbeats."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILENAME = "smart_dashboards_room_ratings.json"
WINDOW_DAYS = 14
ENGAGEMENT_LOOKBACK_DAYS = 7

PILLAR_KEYS = ("compliance", "warning", "consumption", "load", "engagement")


def ratings_store_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("data")) / FILENAME


def canonical_room_id(room: dict[str, Any]) -> str:
    """Stable room key aligned with the energy panel (non-empty id else slug from name)."""
    raw_id = room.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    name = str(room.get("name") or "")
    return re.sub(r"\s+", "_", name.strip().lower())


def legacy_room_id_history(room: dict[str, Any]) -> str:
    """Room id key used by config_manager daily/intraday history (single-space slug)."""
    raw_id = room.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    name = str(room.get("name") or "room")
    return name.lower().replace(" ", "_")


def _room_history_row(
    rooms: dict[str, Any], rid: str, legacy_id: str
) -> dict[str, Any]:
    """Prefer canonical history row; fall back to legacy key if that holds the Wh series."""
    ca = rooms.get(rid) if isinstance(rooms.get(rid), dict) else {}
    le: dict[str, Any] = (
        rooms.get(legacy_id)
        if legacy_id != rid and isinstance(rooms.get(legacy_id), dict)
        else {}
    )

    def wh_sum(d: dict[str, Any]) -> float:
        return sum(float(x) for x in (d.get("wh") or []))

    if wh_sum(ca) > 0:
        return ca
    if wh_sum(le) > 0:
        return le
    return ca or le


def default_store() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "updated_at": None,
        "engagement_visits": {},
        "rooms": {},
    }


def load_ratings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_store()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return default_store()
        raw.setdefault("version", SCHEMA_VERSION)
        if not isinstance(raw.get("engagement_visits"), dict):
            raw["engagement_visits"] = {}
        if not isinstance(raw.get("rooms"), dict):
            raw["rooms"] = {}
        return raw
    except (OSError, json.JSONDecodeError) as e:
        _LOGGER.warning("Room ratings load failed %s: %s", path, e)
        return default_store()


def save_ratings(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
    except OSError as e:
        _LOGGER.warning("Room ratings save failed %s: %s", path, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def record_dashboard_heartbeat(
    data: dict[str, Any], user_key: str, now: datetime | None = None
) -> None:
    """Increment visit count for current hour (max 2 per hour per user key). Mutates ``data``."""
    now = now or dt_util.now()
    day = now.strftime("%Y-%m-%d")
    hour = str(now.hour)
    visits = data.setdefault("engagement_visits", {})
    day_map = visits.setdefault(day, {})
    user_map = day_map.setdefault(user_key, {})
    cur = int(user_map.get(hour, 0))
    user_map[hour] = min(2, cur + 1)


def _score_compliance(
    wh_list: list[float], budget_kwh: float, days_with_data: int
) -> float:
    if days_with_data <= 0:
        return 0.0
    tol = 1.02
    good = 0
    for wh in wh_list:
        used_kwh = float(wh) / 1000.0
        cap = max(float(budget_kwh) * tol, 0.001)
        if used_kwh <= cap:
            good += 1
    return min(100.0, max(0.0, (good / days_with_data) * 100.0))


def _score_warning(warns: list[int], shuts: list[int], cycles: list[int]) -> float:
    total = sum(int(x) for x in warns) + sum(int(x) for x in shuts) + sum(int(x) for x in cycles)
    # ~5 events per 100 points lost, cap at 0
    return max(0.0, 100.0 - min(100.0, total * 4.0))


def _score_consumption(avg_wh: float, median_peer: float) -> float:
    if median_peer <= 0:
        return 0.0
    ratio = avg_wh / (median_peer * 1.5 + 1e-6)
    return max(0.0, min(100.0, (1.0 - min(1.0, ratio)) * 100.0))


def _score_load(config_manager: Any, room_id: str) -> float:
    hist = config_manager.get_room_intraday_history(room_id, 1440)
    watts = hist.get("watts") or []
    if not watts:
        return 0.0
    high_minutes = sum(1 for w in watts if float(w) > 100.0)
    hours_high = high_minutes / 60.0
    return max(0.0, 100.0 - min(100.0, hours_high * 8.0))


def _score_engagement_for_user(
    visits_root: dict[str, Any], now: datetime, user_key: str
) -> float:
    """Same formula as legacy engagement but only one HA user_key's visit map."""
    scores: list[float] = []
    for i in range(ENGAGEMENT_LOOKBACK_DAYS):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        day_users = visits_root.get(d) or {}
        hour_map = day_users.get(user_key) if isinstance(day_users.get(user_key), dict) else {}
        hour_counts: dict[str, int] = {}
        total_visits = 0
        for h, c in hour_map.items():
            try:
                n = int(c)
            except (TypeError, ValueError):
                n = 0
            hour_counts[h] = hour_counts.get(h, 0) + min(2, n)
            total_visits += min(2, n)
        distinct = len(hour_counts)
        part_hours = min(1.0, distinct / 12.0) * 70.0
        part_visits = min(1.0, total_visits / 2.0) * 30.0
        scores.append(min(100.0, part_hours + part_visits))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _user_has_engagement_activity(
    visits_root: dict[str, Any], now: datetime, user_key: str
) -> bool:
    for i in range(ENGAGEMENT_LOOKBACK_DAYS):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        day_users = visits_root.get(d) or {}
        hour_map = day_users.get(user_key) if isinstance(day_users.get(user_key), dict) else {}
        for c in hour_map.values():
            try:
                if int(c) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _engagement_user_keys_in_window(visits_root: dict[str, Any], now: datetime) -> list[str]:
    keys: set[str] = set()
    for i in range(ENGAGEMENT_LOOKBACK_DAYS):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        day_users = visits_root.get(d) or {}
        if isinstance(day_users, dict):
            keys.update(str(k) for k in day_users if isinstance(day_users.get(k), dict))
    return sorted(keys)


def _engagement_score_for_mode(
    visits_root: dict[str, Any],
    now: datetime,
    engagement_user_key: str | None,
    room_has_presence: bool,
) -> tuple[float, str]:
    """Returns (score, meta) where meta is ok | no_data | na."""
    if not room_has_presence:
        return 0.0, "na"
    if engagement_user_key is not None:
        if not _user_has_engagement_activity(visits_root, now, engagement_user_key):
            return 0.0, "no_data"
        return _score_engagement_for_user(visits_root, now, engagement_user_key), "ok"
    user_keys = _engagement_user_keys_in_window(visits_root, now)
    if not user_keys:
        return 0.0, "no_data"
    parts = [_score_engagement_for_user(visits_root, now, uk) for uk in user_keys]
    return sum(parts) / len(parts), "ok"


def _stars_from_average(avg: float) -> float:
    """Map 0–100 mean to 0–5 in 0.5 steps."""
    x = max(0.0, min(100.0, avg))
    steps = round(x / 100.0 * 10.0)
    return min(5.0, max(0.0, steps / 2.0))


def _default_pillar_meta() -> dict[str, str]:
    return {k: "ok" for k in PILLAR_KEYS}


def recompute_room_ratings(
    hass: HomeAssistant,
    config_manager: Any,
    engagement_user_key: str | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Synchronous recompute; call from executor if desired. Returns full store dict.

    When ``persist`` is False (e.g. WebSocket with viewer-specific engagement), scores are
    not written to disk so hourly snapshots stay household-averaged.
    """
    path = ratings_store_path(hass)
    data = load_ratings(path)
    now = dt_util.now()
    history = config_manager.get_daily_history(days=WINDOW_DAYS, include_today=True)
    rooms_h = history.get("rooms") or {}
    rooms_cfg = config_manager.energy_config.get("rooms", [])

    room_avg_wh: dict[str, float] = {}
    for room in rooms_cfg:
        rid = canonical_room_id(room)
        legacy_id = legacy_room_id_history(room)
        rdata_hist = _room_history_row(rooms_h, rid, legacy_id)
        series = rdata_hist.get("wh") or []
        if not series:
            room_avg_wh[rid] = 0.0
        else:
            room_avg_wh[rid] = sum(float(x) for x in series) / max(1, len(series))
    med_list = sorted(v for v in room_avg_wh.values() if v > 0)
    median_peer = med_list[len(med_list) // 2] if med_list else 0.0

    visits_root = data.get("engagement_visits") or {}

    rooms_out: dict[str, Any] = {}
    for room in rooms_cfg:
        rid = canonical_room_id(room)
        legacy_id = legacy_room_id_history(room)
        presence_raw = str(room.get("presence_person_entity") or "").strip()
        room_has_presence = bool(presence_raw)

        try:
            budget_kwh = float(room.get("kwh_budget", 5) or 5)
        except (TypeError, ValueError):
            budget_kwh = 5.0
        rdata = _room_history_row(rooms_h, rid, legacy_id)
        wh_list = [float(x) for x in (rdata.get("wh") or [])]
        has_daily = len(wh_list) > 0

        meta: dict[str, str] = _default_pillar_meta()

        if not has_daily:
            compliance = 0.0
            meta["compliance"] = "no_data"
            warning = 0.0
            meta["warning"] = "no_data"
            consumption = 0.0
            meta["consumption"] = "no_data"
        else:
            compliance = _score_compliance(wh_list, budget_kwh, len(wh_list))
            meta["compliance"] = "ok"
            warning = _score_warning(
                rdata.get("warnings") or [],
                rdata.get("shutoffs") or [],
                rdata.get("power_cycles") or [],
            )
            meta["warning"] = "ok"
            if median_peer <= 0:
                consumption = 0.0
                meta["consumption"] = "no_data"
            else:
                consumption = _score_consumption(room_avg_wh.get(rid, 0.0), median_peer)
                meta["consumption"] = "ok"

        load = _score_load(config_manager, legacy_id)
        hist = config_manager.get_room_intraday_history(legacy_id, 1440)
        if not (hist.get("watts") or []):
            meta["load"] = "no_data"

        engagement, eng_meta = _engagement_score_for_mode(
            visits_root, now, engagement_user_key, room_has_presence
        )
        meta["engagement"] = eng_meta

        c_part = 0.0 if meta["compliance"] == "no_data" else compliance
        w_part = 0.0 if meta["warning"] == "no_data" else warning
        cons_part = 0.0 if meta["consumption"] == "no_data" else consumption
        load_part = 0.0 if meta["load"] == "no_data" else load
        if meta["engagement"] == "na":
            avg = (c_part + w_part + cons_part + load_part) / 4.0
        else:
            eng_part = 0.0 if meta["engagement"] == "no_data" else float(engagement)
            avg = (c_part + w_part + cons_part + load_part + eng_part) / 5.0

        stars = _stars_from_average(avg)
        rooms_out[rid] = {
            "compliance": round(compliance, 1),
            "warning": round(warning, 1),
            "consumption": round(consumption, 1),
            "load": round(load, 1),
            "engagement": round(float(engagement), 1) if meta["engagement"] != "na" else 0.0,
            "average": round(avg, 1),
            "stars": stars,
            "pillar_meta": meta,
        }

    data["version"] = SCHEMA_VERSION
    data["updated_at"] = now.isoformat()
    data["rooms"] = rooms_out
    if persist:
        save_ratings(path, data)
    return data


def ratings_payload_for_ws(data: dict[str, Any]) -> dict[str, Any]:
    """Strip large fields for WebSocket (rooms + meta only)."""
    return {
        "version": data.get("version", SCHEMA_VERSION),
        "updated_at": data.get("updated_at"),
        "rooms": data.get("rooms") or {},
    }
