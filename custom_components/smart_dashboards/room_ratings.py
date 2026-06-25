"""Per-room efficiency ratings persisted under ``config/data``; hourly recompute + engagement heartbeats."""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DEFAULT_CONFIG

_LOGGER = logging.getLogger(__name__)

# Serialize all read-modify-write operations on the ratings JSON file to prevent
# lost-update races (e.g. concurrent hourly recompute + heartbeat from websocket).
_RATINGS_FILE_LOCK = threading.Lock()

SCHEMA_VERSION = 1
FILENAME = "smart_dashboards_room_ratings.json"
WINDOW_DAYS = 14
ENGAGEMENT_LOOKBACK_DAYS = 7

PILLAR_KEYS = ("compliance", "warning", "consumption", "load", "engagement")

_PERSON_DOMAIN = "person"


def engagement_user_key_from_person(hass: HomeAssistant, person_entity_id: str) -> str | None:
    """Map ``person.*`` to the HA auth user id string used in ``engagement_visits`` keys.

    Prefer ``user_id`` on person state (set when the person is linked to a user in HA).
    Then scan person YAML/storage collections. Finally match person ``friendly_name`` to
    an active auth user's ``name`` (same idea as toggle auth).
    """
    pe = str(person_entity_id or "").strip().lower()
    if not pe.startswith("person."):
        return None
    want_slug = pe.split(".", 1)[-1].strip().lower()

    st = hass.states.get(pe)
    if st:
        uid = st.attributes.get("user_id")
        if uid is not None and str(uid).strip():
            return str(uid).strip()

    dom = hass.data.get(_PERSON_DOMAIN)
    if isinstance(dom, (tuple, list)) and len(dom) >= 2:
        for coll in (dom[0], dom[1]):
            raw_data = getattr(coll, "data", None)
            if not isinstance(raw_data, dict):
                continue
            for item in raw_data.values():
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("id") or "").strip().lower()
                if pid != want_slug:
                    continue
                uid = item.get("user_id")
                if uid is not None and str(uid).strip():
                    return str(uid).strip()

    if st:
        pname = str(st.attributes.get("friendly_name") or "").strip().lower()
        if pname:
            auth = getattr(hass, "auth", None)
            users_map = getattr(auth, "_users", None) if auth is not None else None
            if isinstance(users_map, dict):
                for u in users_map.values():
                    if not getattr(u, "is_active", True):
                        continue
                    uname = str(getattr(u, "name", None) or "").strip().lower()
                    if uname and uname == pname:
                        return str(getattr(u, "id", "") or "").strip() or None
    _LOGGER.debug(
        "No engagement user key for %s; link person to a user in Settings → People",
        pe,
    )
    return None


def merge_efficiency_scoring_params(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Clamp efficiency scoring fields from config (defaults from ``DEFAULT_CONFIG``)."""
    d0: dict[str, Any] = DEFAULT_CONFIG["energy"]["efficiency_settings"]
    r = raw or {}

    def _sf(key: str, lo: float, hi: float) -> float:
        try:
            v = float(r.get(key, d0[key]))
        except (TypeError, ValueError):
            v = float(d0[key])
        return max(lo, min(hi, v))

    def _si(key: str, lo: int, hi: int) -> int:
        try:
            v = int(float(r.get(key, d0[key])))
        except (TypeError, ValueError):
            v = int(d0[key])
        return max(lo, min(hi, v))

    return {
        "history_window_days": _si("history_window_days", 1, 90),
        "engagement_lookback_days": _si("engagement_lookback_days", 1, 30),
        "compliance_tolerance": _sf("compliance_tolerance", 1.0, 1.5),
        "warning_points_per_event": _sf("warning_points_per_event", 0.25, 25.0),
        "consumption_peer_multiplier": _sf("consumption_peer_multiplier", 0.5, 5.0),
        "load_high_watts": _sf("load_high_watts", 1.0, 5000.0),
        "load_penalty_per_high_hour": _sf("load_penalty_per_high_hour", 0.0, 50.0),
        "engagement_distinct_hours_target": _si("engagement_distinct_hours_target", 1, 24),
        "engagement_hours_weight": _sf("engagement_hours_weight", 0.0, 100.0),
        "engagement_visits_weight": _sf("engagement_visits_weight", 0.0, 100.0),
        "engagement_visits_daily_norm": _sf("engagement_visits_daily_norm", 1.0, 48.0),
        "engagement_max_visits_per_hour": _si("engagement_max_visits_per_hour", 1, 10),
    }


def efficiency_scoring_params_from_manager(config_manager: Any) -> dict[str, Any]:
    raw = (
        config_manager.energy_config.get("efficiency_settings")
        if config_manager is not None
        else None
    )
    return merge_efficiency_scoring_params(
        raw if isinstance(raw, dict) else None
    )


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


def _merge_engagement_visits(ours: dict, theirs: dict) -> dict:
    """Merge two engagement_visits dicts, taking max counts per user per hour.

    Prevents lost-update race: if heartbeat incremented a count between our load
    and save, we don't overwrite it with a lower value.
    """
    merged: dict = {}
    all_days = set(ours.keys()) | set(theirs.keys())
    for day in all_days:
        our_day = ours.get(day) or {}
        their_day = theirs.get(day) or {}
        merged_day: dict = {}
        all_users = set(our_day.keys()) | set(their_day.keys())
        for user in all_users:
            our_hours = our_day.get(user) or {}
            their_hours = their_day.get(user) or {}
            merged_hours: dict = {}
            all_hours = set(our_hours.keys()) | set(their_hours.keys())
            for hour in all_hours:
                our_val = int(our_hours.get(hour, 0))
                their_val = int(their_hours.get(hour, 0))
                merged_hours[hour] = max(our_val, their_val)
            merged_day[user] = merged_hours
        merged[day] = merged_day
    return merged


def record_dashboard_heartbeat(
    data: dict[str, Any],
    user_key: str,
    now: datetime | None = None,
    *,
    max_per_hour: int | None = None,
) -> None:
    """Increment visit count for current hour (capped per user key). Mutates ``data``."""
    cap = max_per_hour
    if cap is None:
        cap = int(
            DEFAULT_CONFIG["energy"]["efficiency_settings"]["engagement_max_visits_per_hour"]
        )
    cap = max(1, int(cap))
    now = now or dt_util.now()
    day = now.strftime("%Y-%m-%d")
    hour = str(now.hour)
    visits = data.setdefault("engagement_visits", {})
    day_map = visits.setdefault(day, {})
    user_map = day_map.setdefault(user_key, {})
    cur = int(user_map.get(hour, 0))
    user_map[hour] = min(cap, cur + 1)


def _score_compliance(
    wh_list: list[float],
    budget_kwh: float,
    days_with_data: int,
    compliance_tolerance: float,
) -> float:
    if days_with_data <= 0:
        return 0.0
    tol = float(compliance_tolerance)
    good = 0
    for wh in wh_list:
        used_kwh = float(wh) / 1000.0
        cap = max(float(budget_kwh) * tol, 0.001)
        if used_kwh <= cap:
            good += 1
    return min(100.0, max(0.0, (good / days_with_data) * 100.0))


def _score_warning(
    warns: list[int],
    shuts: list[int],
    cycles: list[int],
    points_per_event: float,
) -> float:
    total = sum(int(x) for x in warns) + sum(int(x) for x in shuts) + sum(int(x) for x in cycles)
    ppe = float(points_per_event)
    return max(0.0, 100.0 - min(100.0, total * ppe))


def _score_consumption(
    avg_wh: float, median_peer: float, peer_mult: float
) -> float:
    if median_peer <= 0:
        return 0.0
    pm = float(peer_mult)
    ratio = avg_wh / (median_peer * pm + 1e-6)
    return max(0.0, min(100.0, (1.0 - min(1.0, ratio)) * 100.0))


def _score_load(
    config_manager: Any,
    room_id: str,
    high_watts: float,
    penalty_per_high_hour: float,
) -> float:
    hist = config_manager.get_room_intraday_history(room_id, 1440)
    watts = hist.get("watts") or []
    if not watts:
        return 0.0
    hw = float(high_watts)
    high_minutes = sum(1 for w in watts if float(w) > hw)
    hours_high = high_minutes / 60.0
    pen = float(penalty_per_high_hour)
    return max(0.0, 100.0 - min(100.0, hours_high * pen))


def _score_engagement_for_user(
    visits_root: dict[str, Any],
    now: datetime,
    user_key: str,
    p: dict[str, Any],
) -> float:
    """Engagement for one HA user_key; uses caps and weights from ``p``."""
    lookback = int(p["engagement_lookback_days"])
    cap = max(1, int(p["engagement_max_visits_per_hour"]))
    distinct_target = max(1, int(p["engagement_distinct_hours_target"]))
    w_h = float(p["engagement_hours_weight"])
    w_v = float(p["engagement_visits_weight"])
    visit_daily_norm = max(1.0, float(p["engagement_visits_daily_norm"]))

    scores: list[float] = []
    for i in range(lookback):
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
            hour_counts[h] = hour_counts.get(h, 0) + min(cap, n)
            total_visits += min(cap, n)
        distinct = len(hour_counts)
        part_hours = min(1.0, distinct / float(distinct_target)) * w_h
        part_visits = min(1.0, total_visits / visit_daily_norm) * w_v
        scores.append(min(100.0, part_hours + part_visits))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _user_has_engagement_activity(
    visits_root: dict[str, Any],
    now: datetime,
    user_key: str,
    lookback_days: int,
) -> bool:
    for i in range(lookback_days):
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


def _engagement_score_for_assignee(
    hass: HomeAssistant,
    visits_root: dict[str, Any],
    now: datetime,
    presence_person_entity: str,
    room_has_presence: bool,
    p: dict[str, Any],
) -> tuple[float, str]:
    """Engagement for the HA user linked to the room's ``presence_person_entity`` only."""
    lb = int(p["engagement_lookback_days"])
    if not room_has_presence:
        return 0.0, "na"
    assignee_key = engagement_user_key_from_person(hass, presence_person_entity)
    if not assignee_key:
        return 0.0, "no_data"
    if not _user_has_engagement_activity(visits_root, now, assignee_key, lb):
        return 0.0, "no_data"
    return _score_engagement_for_user(visits_root, now, assignee_key, p), "ok"


def _score_engagement_single_day(
    visits_root: dict[str, Any],
    day: str,
    user_key: str,
    p: dict[str, Any],
) -> float:
    """Engagement score for a single calendar day (dashboard visits for one user)."""
    cap = max(1, int(p["engagement_max_visits_per_hour"]))
    distinct_target = max(1, int(p["engagement_distinct_hours_target"]))
    w_h = float(p["engagement_hours_weight"])
    w_v = float(p["engagement_visits_weight"])
    visit_daily_norm = max(1.0, float(p["engagement_visits_daily_norm"]))

    day_users = visits_root.get(day) or {}
    hour_map = day_users.get(user_key) if isinstance(day_users.get(user_key), dict) else {}
    hour_counts: dict[str, int] = {}
    total_visits = 0
    for h, c in hour_map.items():
        try:
            n = int(c)
        except (TypeError, ValueError):
            n = 0
        hour_counts[h] = hour_counts.get(h, 0) + min(cap, n)
        total_visits += min(cap, n)
    distinct = len(hour_counts)
    part_hours = min(1.0, distinct / float(distinct_target)) * w_h
    part_visits = min(1.0, total_visits / visit_daily_norm) * w_v
    return min(100.0, part_hours + part_visits)


def _user_has_engagement_on_day(
    visits_root: dict[str, Any],
    day: str,
    user_key: str,
) -> bool:
    day_users = visits_root.get(day) or {}
    hour_map = day_users.get(user_key) if isinstance(day_users.get(user_key), dict) else {}
    for c in hour_map.values():
        try:
            if int(c) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _score_engagement_period_days(
    visits_root: dict[str, Any],
    days: list[str],
    user_key: str,
    p: dict[str, Any],
) -> float:
    """Engagement over explicit calendar days (e.g. billing period)."""
    cap = max(1, int(p["engagement_max_visits_per_hour"]))
    distinct_target = max(1, int(p["engagement_distinct_hours_target"]))
    w_h = float(p["engagement_hours_weight"])
    w_v = float(p["engagement_visits_weight"])
    visit_daily_norm = max(1.0, float(p["engagement_visits_daily_norm"]))

    distinct_slots: set[tuple[str, str]] = set()
    total_visits = 0
    for d in days:
        day_users = visits_root.get(d) or {}
        hour_map = day_users.get(user_key) if isinstance(day_users.get(user_key), dict) else {}
        for h, c in hour_map.items():
            try:
                n = min(cap, int(c))
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                distinct_slots.add((d, str(h)))
            total_visits += n

    n_days = max(1, len(days))
    denom_hours = float(distinct_target) * float(n_days)
    denom_visits = visit_daily_norm * float(n_days)
    part_hours = min(1.0, len(distinct_slots) / (denom_hours + 1e-6)) * w_h
    part_visits = min(1.0, total_visits / (denom_visits + 1e-6)) * w_v
    return min(100.0, part_hours + part_visits)


def _user_has_engagement_on_days(
    visits_root: dict[str, Any],
    days: list[str],
    user_key: str,
) -> bool:
    for d in days:
        if _user_has_engagement_on_day(visits_root, d, user_key):
            return True
    return False


def _engagement_score_for_assignee_intraday(
    hass: HomeAssistant,
    visits_root: dict[str, Any],
    today: str,
    presence_person_entity: str,
    room_has_presence: bool,
    p: dict[str, Any],
) -> tuple[float, str]:
    """Today's engagement only for the room assignee."""
    if not room_has_presence:
        return 0.0, "na"
    assignee_key = engagement_user_key_from_person(hass, presence_person_entity)
    if not assignee_key:
        return 0.0, "no_data"
    if not _user_has_engagement_on_day(visits_root, today, assignee_key):
        return 0.0, "no_data"
    return _score_engagement_single_day(visits_root, today, assignee_key, p), "ok"


def _engagement_score_for_assignee_period(
    hass: HomeAssistant,
    visits_root: dict[str, Any],
    days: list[str],
    presence_person_entity: str,
    room_has_presence: bool,
    p: dict[str, Any],
) -> tuple[float, str]:
    """Engagement summed over ``days`` (billing / statistics range) for the assignee."""
    if not room_has_presence:
        return 0.0, "na"
    assignee_key = engagement_user_key_from_person(hass, presence_person_entity)
    if not assignee_key:
        return 0.0, "no_data"
    if not days:
        return 0.0, "no_data"
    if not _user_has_engagement_on_days(visits_root, days, assignee_key):
        return 0.0, "no_data"
    return _score_engagement_period_days(visits_root, days, assignee_key, p), "ok"


def _monthly_load_score_from_daily_wh(
    wh_by_day: dict[str, float],
    day_keys: list[str],
    budget_kwh: float,
    high_watts: float,
    penalty_per_high_hour: float,
    compliance_tolerance: float,
) -> tuple[float, str]:
    """Load pillar over a range: penalize energy above budget tolerance as equivalent high-watt hours."""
    if not day_keys:
        return 0.0, "no_data"
    hw = float(high_watts)
    pen = float(penalty_per_high_hour)
    tol = float(compliance_tolerance)
    cap_kwh = max(float(budget_kwh) * tol, 0.001)
    total_high_hours = 0.0
    any_wh = False
    for d in day_keys:
        wh = float(wh_by_day.get(d, 0) or 0)
        if wh > 0:
            any_wh = True
        used_kwh = wh / 1000.0
        excess_kwh = max(0.0, used_kwh - cap_kwh)
        if excess_kwh <= 0:
            continue
        equiv_h = min(24.0, excess_kwh / max(hw / 1000.0, 1e-6))
        total_high_hours += equiv_h
    score = max(0.0, 100.0 - min(100.0, total_high_hours * pen))
    if not any_wh:
        return score, "no_data"
    return score, "ok"


def _stars_from_average(avg: float) -> float:
    """Map 0–100 mean to 0–5 in 0.5 steps."""
    x = max(0.0, min(100.0, avg))
    steps = round(x / 100.0 * 10.0)
    return min(5.0, max(0.0, steps / 2.0))


def _default_pillar_meta() -> dict[str, str]:
    return {k: "ok" for k in PILLAR_KEYS}


def _assemble_room_rating(
    compliance: float,
    warning: float,
    consumption: float,
    load: float,
    engagement: float,
    meta: dict[str, str],
) -> dict[str, Any]:
    """Composite average, stars, and rounded pillar values (matches ``recompute_room_ratings``)."""
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
    return {
        "compliance": round(compliance, 1),
        "warning": round(warning, 1),
        "consumption": round(consumption, 1),
        "load": round(load, 1),
        "engagement": round(float(engagement), 1) if meta["engagement"] != "na" else 0.0,
        "average": round(avg, 1),
        "stars": stars,
        "pillar_meta": dict(meta),
    }


def compute_intraday_ratings(
    hass: HomeAssistant,
    config_manager: Any,
    rooms_payload: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Efficiency pillars using **today only** (live power row + intraday samples + today's visits).

    ``rooms_payload`` items must include ``id``, ``total_day_wh``, ``warnings``, ``shutoffs``,
    ``power_cycles`` (as returned by ``get_power_data``).
    """
    p = efficiency_scoring_params_from_manager(config_manager)
    path = ratings_store_path(hass)
    data = load_ratings(path)
    visits_root = data.get("engagement_visits") or {}
    today = dt_util.now().strftime("%Y-%m-%d")

    by_id: dict[str, dict[str, Any]] = {}
    for r in rooms_payload:
        rid = str(r.get("id") or "").strip()
        if rid:
            by_id[rid] = r

    peer_wh: list[float] = []
    for r in rooms_payload:
        tw = float(r.get("total_day_wh") or 0)
        if tw > 0:
            peer_wh.append(tw)
    peer_wh.sort()
    median_peer = peer_wh[len(peer_wh) // 2] if peer_wh else 0.0

    rooms_cfg = config_manager.energy_config.get("rooms", [])
    out: dict[str, dict[str, Any]] = {}
    for room in rooms_cfg:
        rid = canonical_room_id(room)
        legacy_id = legacy_room_id_history(room)
        row = by_id.get(rid, {})
        total_day_wh = float(row.get("total_day_wh") or 0)
        warnings = int(row.get("warnings") or 0)
        shutoffs = int(row.get("shutoffs") or 0)
        power_cycles = int(row.get("power_cycles") or 0)
        presence_raw = str(room.get("presence_person_entity") or "").strip()
        room_has_presence = bool(presence_raw)

        try:
            budget_kwh = float(room.get("kwh_budget", 5) or 5)
        except (TypeError, ValueError):
            budget_kwh = 5.0

        meta = _default_pillar_meta()

        compliance = _score_compliance(
            [total_day_wh],
            budget_kwh,
            1,
            float(p["compliance_tolerance"]),
        )
        meta["compliance"] = "ok"

        warning = _score_warning(
            [warnings],
            [shutoffs],
            [power_cycles],
            float(p["warning_points_per_event"]),
        )
        meta["warning"] = "ok"

        if median_peer <= 0:
            consumption = 0.0
            meta["consumption"] = "no_data"
        else:
            consumption = _score_consumption(
                total_day_wh,
                median_peer,
                float(p["consumption_peer_multiplier"]),
            )
            meta["consumption"] = "ok"

        load = _score_load(
            config_manager,
            legacy_id,
            float(p["load_high_watts"]),
            float(p["load_penalty_per_high_hour"]),
        )
        hist = config_manager.get_room_intraday_history(legacy_id, 1440)
        if not (hist.get("watts") or []):
            meta["load"] = "no_data"

        engagement, eng_meta = _engagement_score_for_assignee_intraday(
            hass,
            visits_root,
            today,
            presence_raw,
            room_has_presence,
            p,
        )
        meta["engagement"] = eng_meta

        out[rid] = _assemble_room_rating(
            compliance,
            warning,
            consumption,
            load,
            engagement,
            meta,
        )
    return out


def compute_monthly_ratings(
    hass: HomeAssistant,
    config_manager: Any,
    *,
    stat_day_keys: list[str],
    room_wh_totals: dict[str, float],
    room_day_wh: dict[str, dict[str, float]],
    room_event_totals: dict[str, dict[str, int]],
) -> dict[str, dict[str, Any]]:
    """Efficiency pillars over ``stat_day_keys`` (billing / statistics range).

    ``room_wh_totals``: period sum Wh per room id.
    ``room_day_wh``: room id → {date → Wh}.
    ``room_event_totals``: room id → warnings/shutoffs/power_cycles sums for the range.
    """
    p = efficiency_scoring_params_from_manager(config_manager)
    path = ratings_store_path(hass)
    data = load_ratings(path)
    visits_root = data.get("engagement_visits") or {}

    n_days = max(1, len(stat_day_keys))
    room_avg_wh: dict[str, float] = {}
    for rid, total_wh in room_wh_totals.items():
        room_avg_wh[rid] = float(total_wh) / float(n_days)

    med_list = sorted(v for v in room_avg_wh.values() if v > 0)
    median_peer = med_list[len(med_list) // 2] if med_list else 0.0

    rooms_cfg = config_manager.energy_config.get("rooms", [])
    out: dict[str, dict[str, Any]] = {}
    for room in rooms_cfg:
        rid = canonical_room_id(room)
        presence_raw = str(room.get("presence_person_entity") or "").strip()
        room_has_presence = bool(presence_raw)

        try:
            budget_kwh = float(room.get("kwh_budget", 5) or 5)
        except (TypeError, ValueError):
            budget_kwh = 5.0

        meta = _default_pillar_meta()
        ev = room_event_totals.get(
            rid, {"warnings": 0, "shutoffs": 0, "power_cycles": 0}
        )
        twarn = int(ev.get("warnings", 0))
        tshut = int(ev.get("shutoffs", 0))
        tcyc = int(ev.get("power_cycles", 0))

        wh_list = [
            float(room_day_wh.get(rid, {}).get(d, 0) or 0) for d in stat_day_keys
        ]
        if not stat_day_keys:
            compliance = 0.0
            meta["compliance"] = "no_data"
            warning = 0.0
            meta["warning"] = "no_data"
            consumption = 0.0
            meta["consumption"] = "no_data"
            load = 0.0
            meta["load"] = "no_data"
        else:
            if not any(wh_list):
                compliance = 0.0
                meta["compliance"] = "no_data"
            else:
                compliance = _score_compliance(
                    wh_list,
                    budget_kwh,
                    len(wh_list),
                    float(p["compliance_tolerance"]),
                )
                meta["compliance"] = "ok"

            warning = _score_warning(
                [twarn],
                [tshut],
                [tcyc],
                float(p["warning_points_per_event"]),
            )
            meta["warning"] = "ok"

            avg_wh = room_avg_wh.get(rid, 0.0)
            if median_peer <= 0 or avg_wh <= 0:
                consumption = 0.0
                meta["consumption"] = "no_data"
            else:
                consumption = _score_consumption(
                    avg_wh,
                    median_peer,
                    float(p["consumption_peer_multiplier"]),
                )
                meta["consumption"] = "ok"

            wh_by_day = room_day_wh.get(rid, {}) or {}
            load, load_meta = _monthly_load_score_from_daily_wh(
                {k: float(v or 0) for k, v in wh_by_day.items()},
                stat_day_keys,
                budget_kwh,
                float(p["load_high_watts"]),
                float(p["load_penalty_per_high_hour"]),
                float(p["compliance_tolerance"]),
            )
            meta["load"] = load_meta

        engagement, eng_meta = _engagement_score_for_assignee_period(
            hass,
            visits_root,
            stat_day_keys,
            presence_raw,
            room_has_presence,
            p,
        )
        meta["engagement"] = eng_meta

        out[rid] = _assemble_room_rating(
            compliance,
            warning,
            consumption,
            load,
            engagement,
            meta,
        )

    return out


def recompute_room_ratings(
    hass: HomeAssistant,
    config_manager: Any,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Synchronous recompute; call from executor if desired. Returns full store dict.

    Engagement uses each room's ``presence_person_entity`` → linked HA user only
    (``engagement_visits`` keys match ``str(user.id)``).

    When ``persist`` is False, scores are not written to disk (e.g. on-demand WS load).

    Uses ``_RATINGS_FILE_LOCK`` when ``persist=True`` to prevent lost-update races
    with concurrent heartbeat writes.
    """
    p = efficiency_scoring_params_from_manager(config_manager)
    path = ratings_store_path(hass)
    with _RATINGS_FILE_LOCK:
        data = load_ratings(path)
    now = dt_util.now()
    history = config_manager.get_daily_history(
        days=int(p["history_window_days"]), include_today=True
    )
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
            compliance = _score_compliance(
                wh_list,
                budget_kwh,
                len(wh_list),
                float(p["compliance_tolerance"]),
            )
            meta["compliance"] = "ok"
            warning = _score_warning(
                rdata.get("warnings") or [],
                rdata.get("shutoffs") or [],
                rdata.get("power_cycles") or [],
                float(p["warning_points_per_event"]),
            )
            meta["warning"] = "ok"
            if median_peer <= 0:
                consumption = 0.0
                meta["consumption"] = "no_data"
            else:
                consumption = _score_consumption(
                    room_avg_wh.get(rid, 0.0),
                    median_peer,
                    float(p["consumption_peer_multiplier"]),
                )
                meta["consumption"] = "ok"

        load = _score_load(
            config_manager,
            legacy_id,
            float(p["load_high_watts"]),
            float(p["load_penalty_per_high_hour"]),
        )
        hist = config_manager.get_room_intraday_history(legacy_id, 1440)
        if not (hist.get("watts") or []):
            meta["load"] = "no_data"

        engagement, eng_meta = _engagement_score_for_assignee(
            hass,
            visits_root,
            now,
            presence_raw,
            room_has_presence,
            p,
        )
        meta["engagement"] = eng_meta

        rooms_out[rid] = _assemble_room_rating(
            compliance,
            warning,
            consumption,
            load,
            engagement,
            meta,
        )

    data["version"] = SCHEMA_VERSION
    data["updated_at"] = now.isoformat()
    data["rooms"] = rooms_out
    if persist:
        with _RATINGS_FILE_LOCK:
            # Re-read engagement_visits to merge any heartbeats added since we
            # loaded. Prevents lost-update race with concurrent dashboard heartbeats.
            fresh = load_ratings(path)
            fresh_visits = fresh.get("engagement_visits") or {}
            our_visits = data.get("engagement_visits") or {}
            merged_visits = _merge_engagement_visits(our_visits, fresh_visits)
            data["engagement_visits"] = merged_visits
            save_ratings(path, data)
    return data


def ratings_payload_for_ws(data: dict[str, Any]) -> dict[str, Any]:
    """Strip large fields for WebSocket (rooms + meta only)."""
    return {
        "version": data.get("version", SCHEMA_VERSION),
        "updated_at": data.get("updated_at"),
        "rooms": data.get("rooms") or {},
    }
