"""TP-Link smart-outlet mapping and device-side power protection.

Mirrors smoke-alarm auto-load: one entity on the Home Assistant device is
enough to classify switches, power/current/voltage, LED, auto-off, and the
built-in power-protection number. Monthly/daily kWh sensors are ignored.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

_LOGGER = logging.getLogger(__name__)

TPLINK_ROLES = (
    "plug1_switch",
    "plug2_switch",
    "plug1_power",
    "plug2_power",
    "plug1_current",
    "plug2_current",
    "plug1_voltage",
    "plug2_voltage",
    "plug1_power_protection",
    "plug2_power_protection",
    "plug1_auto_off",
    "plug2_auto_off",
    "led",
)

# Integration domain / manufacturer / models that count as a TP-Link plug.
_TPLINK_DOMAINS = {"tplink"}
_TPLINK_MANUFACTURERS = {"tp-link", "tp link", "tplink", "tapo", "kasa"}
_TPLINK_OUTLET_MODELS = {
    "p100",
    "p105",
    "p110",
    "p110m",
    "p115",
    "p125m",
    "p135",
    "p210m",
    "p300",
    "p304m",
    "p306",
    "tp15",
    "tp25",
    "hs100",
    "hs103",
    "hs105",
    "hs107",
    "hs110",
    "kp105",
    "kp115",
    "kp125",
    "kp125m",
    "kp400",
    "ep10",
    "ep25",
    "ep40",
}

# HA tplink feature keys. consumption_* kWh totals are intentionally omitted.
_FEATURE_KEYS = {
    "current_consumption": "power",
    "current": "current",
    "voltage": "voltage",
    "power_protection_threshold": "power_protection",
    "power_protection": "power_protection",
    "auto_off_enabled": "auto_off",
    "led": "led",
    "state": "switch",
}

_SKIP_FEATURES = {
    "consumption_today",
    "consumption_this_month",
    "consumption_total",
    "auto_update_enabled",
    "auto_off_minutes",
    "auto_off_at",
    "on_since",
    "rssi",
    "signal_level",
    "ssid",
    "device_time",
}

_P1_RE = re.compile(r"(?:[:_\-]|\b)p1(?:\b|[:_\-])(?!\d)", re.IGNORECASE)
_P2_RE = re.compile(r"(?:[:_\-]|\b)p2(?:\b|[:_\-])(?!\d)", re.IGNORECASE)

_ROLE_TO_FIELD = {
    "plug1_power": "plug1_entity",
    "plug2_power": "plug2_entity",
    "plug1_switch": "plug1_switch",
    "plug2_switch": "plug2_switch",
}


def normalize_tplink_map(raw: Any) -> dict[str, str]:
    """Keep only known roles whose value looks like an entity id."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for role in TPLINK_ROLES:
        eid = str(raw.get(role) or "").strip()
        if "." in eid:
            out[role] = eid
    return out


def config_fields(outlet: dict[str, Any] | None) -> dict[str, Any]:
    """Validated TP-Link fields to persist on an outlet / single_outlet."""
    raw = outlet or {}
    brand = str(raw.get("outlet_brand") or "").strip().lower()
    anchor = str(raw.get("tplink_anchor") or "").strip()
    device_id = str(raw.get("tplink_device_id") or "").strip()
    return {
        "outlet_brand": "tplink" if brand == "tplink" else None,
        "tplink_anchor": anchor if "." in anchor else None,
        "tplink_device_id": device_id or None,
        "tplink_map": normalize_tplink_map(raw.get("tplink_map")),
    }


def is_tplink_smart_outlet(
    *,
    manufacturer: str = "",
    model: str = "",
    identifiers: Iterable[Any] | None = None,
    config_domains: Iterable[str] | None = None,
    mapped: dict[str, str] | None = None,
) -> bool:
    """True when this HA device is a TP-Link / Tapo / Kasa smart plug or strip.

    Requires a TP-Link integration/manufacturer (or a known plug model such as
    P210M) and at least one plug switch, power sensor, or power-protection
    entity so bulbs and cameras are not treated as outlets.
    """
    if not _is_tplink_identity(manufacturer, model, identifiers, config_domains):
        return False
    found = mapped or {}
    return any(
        found.get(key)
        for key in (
            "plug1_switch",
            "plug2_switch",
            "plug1_power",
            "plug2_power",
            "plug1_power_protection",
            "plug2_power_protection",
        )
    )


def uses_device_power_protection(outlet: dict[str, Any] | None) -> bool:
    """True when Home Energy should skip internal shutoff for this outlet."""
    raw = outlet or {}
    if str(raw.get("outlet_brand") or "").strip().lower() != "tplink":
        return False
    otype = str(raw.get("type") or "outlet").strip().lower()
    return otype in {"outlet", "single_outlet"}


def mapped_fields(mapped: dict[str, str] | None) -> dict[str, str]:
    """Standard outlet fields filled from a TP-Link role map."""
    entities = normalize_tplink_map(mapped)
    out: dict[str, str] = {}
    for role, field in _ROLE_TO_FIELD.items():
        eid = entities.get(role)
        if eid:
            out[field] = eid
    return out


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _norm_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "").replace(" ", "").replace("_", "")


def _is_tplink_identity(
    manufacturer: str,
    model: str,
    identifiers: Iterable[Any] | None,
    config_domains: Iterable[str] | None,
) -> bool:
    for domain in config_domains or ():
        if str(domain or "").strip().lower() in _TPLINK_DOMAINS:
            return True
    for ident in identifiers or ():
        domain = ident[0] if isinstance(ident, (tuple, list)) and ident else ident
        if str(domain or "").strip().lower() in _TPLINK_DOMAINS:
            return True
    if _norm_name(manufacturer) in _TPLINK_MANUFACTURERS:
        return True
    model_token = _norm_token(model)
    if model_token in _TPLINK_OUTLET_MODELS:
        return True
    return any(model_token.startswith(known) for known in _TPLINK_OUTLET_MODELS)


def _plug_slot(*parts: Any) -> int | None:
    """Return 1 or 2 when P1/P2 is a distinct token, never from P210M."""
    blob = " ".join(str(part or "") for part in parts)
    if not blob.strip():
        return None
    has_p1 = bool(_P1_RE.search(blob))
    has_p2 = bool(_P2_RE.search(blob))
    if has_p1 and not has_p2:
        return 1
    if has_p2 and not has_p1:
        return 2
    return None


def _is_energy_summation(name: str, unique_id: str, entity_id: str, unit: str) -> bool:
    blob = f"{name} {unique_id} {entity_id}".lower().replace("-", "_")
    if any(
        key in blob
        for key in (
            "consumption_today",
            "consumption_this_month",
            "consumption_total",
            "today_s_consumption",
            "this_month_s_consumption",
        )
    ):
        return True
    if unit in {"kwh", "wh", "kwhs"}:
        if "today" in name or "month" in name or "total" in name:
            return True
    if "today" in name and ("consumption" in name or "energy" in name):
        return True
    if "month" in name and ("consumption" in name or "energy" in name):
        return True
    return False


def _feature_key(unique_id: str, entity_id: str) -> str:
    uid = str(unique_id or "").strip().lower()
    eid = str(entity_id or "").strip().lower()
    tail = eid.split(".", 1)[-1]
    keys = sorted(set(_SKIP_FEATURES) | set(_FEATURE_KEYS), key=len, reverse=True)
    for key in keys:
        if uid.endswith(f"_{key}") or tail.endswith(f"_{key}"):
            return key
    return ""


def _feature_of(row: dict[str, Any]) -> str | None:
    eid = str(row.get("entity_id") or "").strip()
    name = _norm_name(row.get("name") or eid)
    domain = str(row.get("domain") or (eid.split(".", 1)[0] if "." in eid else "")).strip().lower()
    unit = _norm_name(row.get("unit"))
    unique_id = str(row.get("unique_id") or "")
    key = _feature_key(unique_id, eid)
    if key in _SKIP_FEATURES or _is_energy_summation(name, unique_id, eid, unit):
        return None
    if key in _FEATURE_KEYS:
        return _FEATURE_KEYS[key]

    blob = f"{_norm_name(unique_id)} {name} {_norm_name(eid)}"
    if domain == "number" and "power protection" in blob:
        return "power_protection"
    if domain == "switch" and "auto off" in name and "enabled" in name:
        return "auto_off"
    if domain == "switch" and (name in {"led", "ledo"} or name.endswith(" led")):
        return "led"
    if domain == "switch" and ("auto update" in name or "auto-update" in name):
        return None
    if "current consumption" in name or "current_consumption" in unique_id.lower():
        return "power"
    if unit in {"w", "kw"} and "protection" not in name and "energy" not in name:
        return "power"
    if domain == "sensor" and name.endswith(" power") and "energy" not in name:
        return "power"
    if unit in {"a", "ma"} and "consumption" not in name:
        return "current"
    if domain == "sensor" and (name == "current" or name.endswith(" current")) and "consumption" not in name:
        return "current"
    if unit in {"v"} or (domain == "sensor" and "voltage" in name):
        return "voltage"
    if domain == "switch":
        return "switch"
    return None


def classify_entities(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Map TP-Link parent + P1/P2 child entities onto outlet roles.

    First match wins. Daily/monthly kWh sensors are never mapped.
    """
    found: dict[str, str] = {}
    unslotted: list[tuple[str, str]] = []

    def take(role: str, entity_id: str) -> None:
        if role not in found and entity_id:
            found[role] = entity_id

    for row in rows:
        eid = str(row.get("entity_id") or "").strip()
        if "." not in eid:
            continue
        feature = _feature_of(row)
        if not feature:
            continue
        slot = _plug_slot(row.get("name"), eid, row.get("device_name"), row.get("unique_id"))
        if feature == "led":
            take("led", eid)
            continue
        if slot in (1, 2):
            take(f"plug{slot}_{feature}" if feature != "switch" else f"plug{slot}_switch", eid)
        else:
            unslotted.append((feature, eid))

    has_explicit_p2 = any(role.startswith("plug2_") for role in found)
    for feature, eid in unslotted:
        if feature == "led":
            take("led", eid)
            continue
        slot = 2 if has_explicit_p2 and f"plug1_{'switch' if feature == 'switch' else feature}" in found else 1
        role = f"plug{slot}_switch" if feature == "switch" else f"plug{slot}_{feature}"
        take(role, eid)
    return found


def _config_domains_for_device(hass: Any, device: Any) -> list[str]:
    domains: list[str] = []
    entries = getattr(device, "config_entries", None) or ()
    getter = getattr(getattr(hass, "config_entries", None), "async_get_entry", None)
    if getter is None:
        return domains
    for entry_id in entries:
        entry = getter(entry_id)
        domain = getattr(entry, "domain", None) if entry is not None else None
        if domain:
            domains.append(str(domain))
    return domains


def _device_family(hass: Any, device_id: str) -> tuple[Any | None, list[Any]]:
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        return None, []
    root = device
    seen: set[str] = set()
    while getattr(root, "via_device_id", None) and root.id not in seen:
        seen.add(root.id)
        parent = registry.async_get(root.via_device_id)
        if parent is None:
            break
        root = parent
    family = [root]
    for other in registry.devices.values():
        if other.id != root.id and getattr(other, "via_device_id", None) == root.id:
            family.append(other)
    return root, family


def _rows_for_devices(hass: Any, devices: list[Any]) -> list[dict[str, Any]]:
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    rows: list[dict[str, Any]] = []
    for device in devices:
        device_name = getattr(device, "name_by_user", None) or getattr(device, "name", "") or ""
        for entry in er.async_entries_for_device(registry, device.id, include_disabled_entities=False):
            state = hass.states.get(entry.entity_id)
            name = entry.name or entry.original_name or (state.name if state else "") or entry.entity_id
            attrs = state.attributes if state else {}
            rows.append(
                {
                    "entity_id": entry.entity_id,
                    "name": name,
                    "domain": entry.entity_id.split(".", 1)[0],
                    "unit": attrs.get("unit_of_measurement") or "",
                    "unique_id": entry.unique_id or "",
                    "device_name": device_name,
                    "device_id": device.id,
                }
            )
    return rows


def _protection_values(hass: Any, mapped: dict[str, str]) -> dict[str, int]:
    values: dict[str, int] = {}
    for slot, role in ((1, "plug1_power_protection"), (2, "plug2_power_protection")):
        eid = mapped.get(role)
        if not eid:
            continue
        state = hass.states.get(eid)
        if state is None:
            continue
        try:
            values[f"plug{slot}"] = int(float(state.state))
        except (TypeError, ValueError):
            continue
    return values


def resolve_tplink_outlet(
    hass: Any,
    entity_id: str | None = None,
    device_id: str | None = None,
) -> dict[str, Any]:
    """Classify every entity on a TP-Link outlet and its P1/P2 children."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    resolved = str(device_id or "").strip() or None
    if not resolved and entity_id:
        entry = registry.async_get(str(entity_id).strip())
        if entry is None:
            return {"device_id": None, "is_tplink": False, "entities": {}, "found": []}
        resolved = entry.device_id
    if not resolved:
        return {"device_id": None, "is_tplink": False, "entities": {}, "found": []}

    root, family = _device_family(hass, resolved)
    if root is None:
        return {"device_id": None, "is_tplink": False, "entities": {}, "found": []}

    rows = _rows_for_devices(hass, family)
    mapped = classify_entities(rows)
    domains = _config_domains_for_device(hass, root)
    is_tplink = is_tplink_smart_outlet(
        manufacturer=getattr(root, "manufacturer", "") or "",
        model=getattr(root, "model", "") or "",
        identifiers=getattr(root, "identifiers", None),
        config_domains=domains,
        mapped=mapped,
    )
    if not is_tplink:
        return {
            "device_id": root.id,
            "is_tplink": False,
            "manufacturer": getattr(root, "manufacturer", None),
            "model": getattr(root, "model", None),
            "device_name": getattr(root, "name_by_user", None) or getattr(root, "name", None),
            "entities": {},
            "found": [],
        }
    found = [{"role": role, "entity_id": eid} for role, eid in mapped.items()]
    return {
        "device_id": root.id,
        "is_tplink": True,
        "manufacturer": getattr(root, "manufacturer", None),
        "model": getattr(root, "model", None),
        "device_name": getattr(root, "name_by_user", None) or getattr(root, "name", None),
        "entities": mapped,
        "found": found,
        "fields": mapped_fields(mapped),
        "protection_values": _protection_values(hass, mapped),
    }


async def async_sync_power_protection(hass: Any, energy_config: dict[str, Any] | None) -> None:
    """Write configured shutoff watts onto each TP-Link power-protection number."""
    rooms = (energy_config or {}).get("rooms") or []
    for room in rooms:
        for outlet in room.get("outlets") or []:
            if not isinstance(outlet, dict) or not uses_device_power_protection(outlet):
                continue
            mapped = normalize_tplink_map(outlet.get("tplink_map"))
            pairs = (
                (mapped.get("plug1_power_protection"), outlet.get("plug1_shutoff")),
                (mapped.get("plug2_power_protection"), outlet.get("plug2_shutoff")),
            )
            for eid, watts in pairs:
                if not eid or not str(eid).startswith("number."):
                    continue
                try:
                    value = int(watts or 0)
                except (TypeError, ValueError):
                    value = 0
                try:
                    await hass.services.async_call(
                        "number",
                        "set_value",
                        {"entity_id": eid, "value": value},
                        blocking=False,
                    )
                except Exception as err:  # noqa: BLE001 — device may be offline
                    _LOGGER.warning("TP-Link power protection sync failed for %s: %s", eid, err)
