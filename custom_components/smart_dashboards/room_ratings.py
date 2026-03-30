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


def ratings_store_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("data")) / FILENAME


def canonical_room_id(room: dict[str, Any]) -> str:
    """Stable room key aligned with the energy panel (non-empty id else slug from name)."""
    raw_id = room.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    name = str(room.get("name") or "")
    return re.sub(r"\s+", "_", name.strip().lower())


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
        return 50.0
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
        return 60.0
    ratio = avg_wh / (median_peer * 1.5 + 1e-6)
    return max(0.0, min(100.0, (1.0 - min(1.0, ratio)) * 100.0))


def _score_load(config_manager: Any, room_id: str) -> float:
    hist = config_manager.get_room_intraday_history(room_id, 1440)
    watts = hist.get("watts") or []
    if not watts:
        return 70.0
    high_minutes = sum(1 for w in watts if float(w) > 100.0)
    hours_high = high_minutes / 60.0
    return max(0.0, 100.0 - min(100.0, hours_high * 8.0))


def _score_engagement(visits_root: dict[str, Any], now: datetime) -> float:
    """Score from last ENGAGEMENT_LOOKBACK_DAYS: distinct hours + visit counts."""
    scores: list[float] = []
    for i in range(ENGAGEMENT_LOOKBACK_DAYS):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        day_users = visits_root.get(d) or {}
        # merge all user keys for household
        hour_counts: dict[str, int] = {}
        total_visits = 0
        for _uk, hour_map in day_users.items():
            if not isinstance(hour_map, dict):
                continue
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
        return 40.0
    return sum(scores) / len(scores)


def _stars_from_average(avg: float) -> float:
    """Map 0–100 mean to 0–5 in 0.5 steps."""
    x = max(0.0, min(100.0, avg))
    steps = round(x / 100.0 * 10.0)
    return min(5.0, max(0.0, steps / 2.0))


def recompute_room_ratings(hass: HomeAssistant, config_manager: Any) -> dict[str, Any]:
    """Synchronous recompute; call from executor if desired. Returns full store dict."""
    path = ratings_store_path(hass)
    data = load_ratings(path)
    now = dt_util.now()
    history = config_manager.get_daily_history(days=WINDOW_DAYS, include_today=True)
    dates = history.get("dates") or []
    rooms_cfg = config_manager.energy_config.get("rooms", [])

    # Peer median of average daily Wh for consumption scoring
    room_avg_wh: dict[str, float] = {}
    for room in rooms_cfg:
        rid = canonical_room_id(room)
        series = (history.get("rooms") or {}).get(rid, {}).get("wh") or []
        if not series:
            room_avg_wh[rid] = 0.0
        else:
            room_avg_wh[rid] = sum(float(x) for x in series) / max(1, len(series))
    med_list = sorted(v for v in room_avg_wh.values() if v > 0)
    median_peer = med_list[len(med_list) // 2] if med_list else 0.0

    engagement_score = _score_engagement(data.get("engagement_visits") or {}, now)

    rooms_out: dict[str, Any] = {}
    for room in rooms_cfg:
        rid = canonical_room_id(room)
        try:
            budget_kwh = float(room.get("kwh_budget", 5) or 5)
        except (TypeError, ValueError):
            budget_kwh = 5.0
        rdata = (history.get("rooms") or {}).get(rid, {})
        wh_list = [float(x) for x in (rdata.get("wh") or [])]
        days_n = len(dates)
        compliance = _score_compliance(wh_list, budget_kwh, days_n)
        warning = _score_warning(
            rdata.get("warnings") or [],
            rdata.get("shutoffs") or [],
            rdata.get("power_cycles") or [],
        )
        consumption = _score_consumption(room_avg_wh.get(rid, 0.0), median_peer)
        load = _score_load(config_manager, rid)
        engagement = engagement_score
        avg = (compliance + warning + consumption + load + engagement) / 5.0
        stars = _stars_from_average(avg)
        rooms_out[rid] = {
            "compliance": round(compliance, 1),
            "warning": round(warning, 1),
            "consumption": round(consumption, 1),
            "load": round(load, 1),
            "engagement": round(engagement, 1),
            "average": round(avg, 1),
            "stars": stars,
        }

    data["version"] = SCHEMA_VERSION
    data["updated_at"] = now.isoformat()
    data["rooms"] = rooms_out
    save_ratings(path, data)
    return data


def ratings_payload_for_ws(data: dict[str, Any]) -> dict[str, Any]:
    """Strip large fields for WebSocket (rooms + meta only)."""
    return {
        "version": data.get("version", SCHEMA_VERSION),
        "updated_at": data.get("updated_at"),
        "rooms": data.get("rooms") or {},
    }
