"""Light automation helpers for Smart Dashboards.

This module centralizes the light-automation logic that previously lived inline
in ``energy_monitor.py`` and was duplicated across the integration:

* ``classify_outlet_type`` — single source of truth for the outlet-type ladder
  that was copy-pasted across 6+ call sites (audit BUG 12).
* ``encode_tuya_scene_hex`` — the canonical Tuya ``scene_data_v2`` hex encoder,
  so the JS frontend can stop carrying its own drifted copy (audit BUG 22).
* ``apply_tuya_scene`` — one scene-apply path used by both the WebSocket
  "test scene" handler and the automation engine (audit BUG 18).
* ``energize_switch_for_mode`` — the "energize switch, do work, de-energize
  after 60s" pattern shared by the group and single apply paths (audit BUG 5).
"""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

_LOGGER = logging.getLogger(__name__)


class OutletType(str, Enum):
    """Canonical outlet type classification (audit BUG 12).

    Previously the integration had six slightly different ladders like
    ``if otype == "outlet" / elif "light" / elif ("vent","wall_heater") /
    elif ("single_outlet","minisplit","stove") / elif ("microwave","fridge")``.
    Adding a type required updating all of them in lockstep. This enum plus
    :func:`classify_outlet_type` is the single source of truth.
    """

    OUTLET = "outlet"
    LIGHT = "light"
    VENT = "vent"
    WALL_HEATER = "wall_heater"
    SINGLE_OUTLET = "single_outlet"
    MINISPLIT = "minisplit"
    STOVE = "stove"
    MICROWAVE = "microwave"
    FRIDGE = "fridge"
    UNKNOWN = "unknown"


def classify_outlet_type(outlet: dict | None) -> OutletType:
    """Classify an outlet dict into a canonical :class:`OutletType`."""
    if not outlet:
        return OutletType.UNKNOWN
    raw = str(outlet.get("type", "outlet")).strip().lower()
    try:
        return OutletType(raw)
    except ValueError:
        return OutletType.UNKNOWN


def switch_entity_for_outlet(outlet: dict | None) -> str | None:
    """Return the primary switch.* entity id for an outlet, by type.

    Consolidates the per-type ``outlet.get("plug1_switch")`` /
    ``outlet.get("switch_entity")`` branching that was duplicated across
    ``_find_outlet_by_switch``, ``_presence_auto_off_configured_switch_ids``,
    ``_presence_auto_off_switch_targets`` and ``_get_power_entity_ids``.
    """
    otype = classify_outlet_type(outlet)
    if otype in (OutletType.OUTLET,):
        # Dual-outlet: plug1 is the "primary" switch; callers that need both
        # should iterate plug1_switch + plug2_switch themselves.
        return (outlet or {}).get("plug1_switch") or None
    if otype in (OutletType.LIGHT, OutletType.VENT, OutletType.WALL_HEATER):
        return (outlet or {}).get("switch_entity") or None
    if otype in (
        OutletType.SINGLE_OUTLET,
        OutletType.MINISPLIT,
        OutletType.STOVE,
        OutletType.MICROWAVE,
        OutletType.FRIDGE,
    ):
        return (outlet or {}).get("plug1_switch") or None
    return None


def all_switch_entities_for_outlet(outlet: dict | None) -> list[str]:
    """All switch.* entity ids an outlet exposes (plug1 + plug2 for dual outlets)."""
    if not outlet:
        return []
    otype = classify_outlet_type(outlet)
    out: list[str] = []
    if otype == OutletType.OUTLET:
        for k in ("plug1_switch", "plug2_switch"):
            v = outlet.get(k)
            if v:
                out.append(str(v))
    else:
        primary = switch_entity_for_outlet(outlet)
        if primary:
            out.append(str(primary))
    return out


def encode_tuya_scene_hex(scene: dict) -> str:
    """Encode Tuya scene data into the ``scene_data_v2`` hex string.

    This is the canonical implementation. The frontend
    (``energy-panel.js::_encodeTuyaSceneHex``) carried a drifted JS port which
    is being removed (audit BUG 22). If the frontend ever needs a preview, it
    should call the ``smart_dashboards/encode_tuya_scene`` WS command which
    delegates here.
    """
    units = scene.get("scene_units", []) if isinstance(scene, dict) else []
    if not units:
        return ""

    scene_index = hex(max(1, scene.get("scene_num", 1)))[2:].zfill(2)
    hex_str = scene_index

    for unit in units:
        # White mode = a color-temperature is set and no hue/saturation.
        # ``unit.get("h", 0)`` returns None if the key exists with a null value,
        # which previously made the Python and JS encoders disagree. Normalize
        # to 0 so the two modes are unambiguous.
        h = int(unit.get("h") or 0)
        s = int(unit.get("s") or 0)
        temp = int(unit.get("temperature") or 0)
        is_white_mode = temp > 0 and h == 0 and s == 0

        sw = int(float(unit.get("unit_switch_duration", 50) or 50))
        gr = int(float(unit.get("unit_gradient_duration", sw) or sw))
        byte_sw = max(0, min(100, sw))
        byte_gr = max(0, min(100, gr))
        switch_hex = hex(byte_sw)[2:].zfill(2)
        gradient_hex = hex(byte_gr)[2:].zfill(2)

        transition_type = "00"
        mode = unit.get("unit_change_mode", "static")
        if mode == "jump":
            transition_type = "01"
        elif mode == "gradient":
            transition_type = "02"

        if is_white_mode:
            brightness = max(0, min(1000, int(unit.get("bright", 1000) or 1000)))
            temperature = max(0, min(1000, int(unit.get("temperature", 500) or 500)))
            bright_hex = hex(brightness)[2:].zfill(4)
            temp_hex = hex(temperature)[2:].zfill(4)
            hex_str += (
                switch_hex + gradient_hex + transition_type
                + "0000" + "0000" + "0000" + bright_hex + temp_hex
            )
        else:
            hue = max(0, min(359, h))
            saturation = max(0, min(1000, s))
            brightness = max(0, min(1000, int(unit.get("bright", 1000) or 1000)))
            hue_hex = hex(hue)[2:].zfill(4)
            sat_hex = hex(saturation)[2:].zfill(4)
            bright_hex = hex(brightness)[2:].zfill(4)
            hex_str += (
                switch_hex + gradient_hex + transition_type
                + hue_hex + sat_hex + bright_hex + "0000" + "0000"
            )

    return hex_str


async def apply_tuya_scene(
    hass: "HomeAssistant",
    entity_id: str,
    scene: dict,
    *,
    blocking: bool = False,
) -> bool:
    """Apply a Tuya scene to a light via the ``text.{light}_scene`` entity.

    Single source of truth used by both the WebSocket "test scene" handler and
    the automation engine's apply path (audit BUG 18). Previously the test path
    in ``websocket.py`` had a 3-branch fallback (``text.set_value`` → DP 25 →
    ``light.turn_on`` with effect) that the automation path never used, so a
    scene that worked in test could silently fail in automation.

    Returns ``True`` if the scene was sent (the light's actual convergence is
    observed separately by the automation engine's match check).
    """
    if not entity_id or not entity_id.startswith("light."):
        _LOGGER.warning("apply_tuya_scene: invalid entity_id %s", entity_id)
        return False

    scene_hex = encode_tuya_scene_hex(scene)
    if not scene_hex:
        _LOGGER.warning("apply_tuya_scene: empty scene hex for %s", entity_id)
        return False

    light_name = entity_id.replace("light.", "", 1)
    scene_text_entity = f"text.{light_name}_scene"

    # Set the "scene" effect first so the light enters scene mode (if supported).
    st = hass.states.get(entity_id)
    if st and st.attributes:
        effect_list = st.attributes.get("effect_list") or []
        scene_effect = next(
            (e for e in effect_list if str(e).lower() == "scene"), None
        )
        if scene_effect:
            try:
                await hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": entity_id, "effect": scene_effect},
                    blocking=blocking,
                )
            except Exception as e:
                _LOGGER.warning(
                    "apply_tuya_scene: failed to set effect=%s on %s: %s",
                    scene_effect, entity_id, e,
                )

    # Enable a disabled text.{light}_scene entity if needed.
    try:
        from homeassistant.helpers import entity_registry as er
        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get(scene_text_entity)
        if entry and entry.disabled_by is not None:
            ent_reg.async_update_entity(scene_text_entity, disabled_by=None)
            _LOGGER.info(
                "apply_tuya_scene: enabled disabled entity %s for %s",
                scene_text_entity, entity_id,
            )
            await asyncio.sleep(0.5)
    except Exception as e:
        _LOGGER.debug("apply_tuya_scene: entity-registry check failed: %s", e)

    scene_state = hass.states.get(scene_text_entity)
    if scene_state is None:
        _LOGGER.warning(
            "apply_tuya_scene: scene text entity %s does not exist for %s",
            scene_text_entity, entity_id,
        )
        return False

    try:
        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": scene_text_entity, "value": scene_hex},
            blocking=blocking,
        )
        return True
    except Exception as e:
        _LOGGER.warning(
            "apply_tuya_scene: scene set failed for %s (%s): %s",
            entity_id, scene_text_entity, e,
        )
        return False


async def energize_switch_for_mode(
    set_switch_cb,
    switch_entity: str | None,
) -> tuple[bool, float | None]:
    """Energize a switch.* for a "mode" light segment if it is currently off.

    Returns ``(was_off, energized_at_monotonic)``. The caller is responsible
    for de-energizing after the mode work completes (see audit BUG 5: this
    pattern was duplicated between ``_apply_light_group_segment`` and
    ``_apply_light_action`` with subtly different de-energize conditions).
    """
    import time
    if not switch_entity or not str(switch_entity).startswith("switch."):
        return False, None
    was_off = not await set_switch_cb(switch_entity, read_only=True)
    if was_off:
        await set_switch_cb(switch_entity, on=True)
        return True, time.monotonic()
    return False, None
