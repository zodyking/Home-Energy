"""HA-aligned statistics aggregation: energy (sum of hourly changes) vs power integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

MODE_ENERGY_CHANGE = "energy_change"
MODE_POWER_INTEGRATION = "power_integration"


def entity_statistics_mode(hass: HomeAssistant, entity_id: str) -> str:
    """Classify how to aggregate kWh for this entity.

    total_increasing + energy (or kWh/Wh/MWh) uses recorder statistics hourly *change*
    (same family as the Energy dashboard). Everything else uses step-integration of W.
    """
    state = hass.states.get(entity_id)
    if not state:
        return MODE_POWER_INTEGRATION
    state_class = state.attributes.get("state_class", "") or ""
    device_class = state.attributes.get("device_class", "") or ""
    unit = state.attributes.get("unit_of_measurement", "") or ""
    if state_class == "total_increasing" and (
        device_class == "energy" or unit in ("kWh", "Wh", "MWh")
    ):
        return MODE_ENERGY_CHANGE
    return MODE_POWER_INTEGRATION


def sync_sum_energy_change_wh(
    hass: HomeAssistant,
    entity_id: str,
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[float, dict[str, float], dict[str, Any]]:
    """Sum hourly energy *change* from long-term statistics (kWh → Wh) per local calendar day.

    Negative hourly changes (meter resets) are skipped and counted in meta.
    """
    from homeassistant.components.recorder.statistics import statistics_during_period

    tz = dt_util.get_default_time_zone()
    by_day: dict[str, float] = {}
    negative_skipped = 0
    rows_used = 0

    try:
        energy_stats = statistics_during_period(
            hass,
            start_time=start_dt,
            end_time=end_dt,
            statistic_ids={entity_id},
            period="hour",
            units={"energy": "kWh"},
            types={"change"},
        )
    except Exception as err:
        _LOGGER.warning("Energy statistics query failed for %s: %s", entity_id, err)
        return 0.0, {}, {
            "method": MODE_ENERGY_CHANGE,
            "error": str(err),
            "negative_changes_skipped": 0,
            "rows_used": 0,
        }

    rows = energy_stats.get(entity_id) or []
    total_wh = 0.0

    for row in rows:
        change_kwh = row.get("change")
        if change_kwh is None:
            continue
        try:
            change_kwh = float(change_kwh)
        except (TypeError, ValueError):
            continue
        if change_kwh < 0:
            negative_skipped += 1
            continue
        start_ts = row.get("start")
        if start_ts is None:
            continue
        if isinstance(start_ts, (int, float)):
            ts_dt = datetime.fromtimestamp(start_ts, tz=tz)
        elif isinstance(start_ts, datetime):
            ts_dt = start_ts.astimezone(tz)
        else:
            continue
        wh = change_kwh * 1000.0
        total_wh += wh
        rows_used += 1
        day_key = ts_dt.strftime("%Y-%m-%d")
        by_day[day_key] = by_day.get(day_key, 0.0) + wh

    meta: dict[str, Any] = {
        "method": MODE_ENERGY_CHANGE,
        "negative_changes_skipped": negative_skipped,
        "rows_used": rows_used,
    }
    if total_wh > 0 or by_day:
        _LOGGER.debug(
            "Energy change sum %s: total=%.2f Wh, days=%s, rows=%d, neg_skipped=%d",
            entity_id,
            total_wh,
            list(by_day.keys()),
            rows_used,
            negative_skipped,
        )
    return total_wh, by_day, meta
