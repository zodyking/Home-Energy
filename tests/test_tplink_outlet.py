"""Unit tests for TP-Link outlet classification (no Home Assistant required)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "smart_dashboards"))

from tplink_outlet import (  # noqa: E402
    classify_entities,
    is_tplink_smart_outlet,
    mapped_fields,
    normalize_tplink_map,
    uses_device_power_protection,
)


def row(entity_id, name, *, domain=None, unit="", unique_id="", device_name=""):
    return {
        "entity_id": entity_id,
        "name": name,
        "domain": domain or entity_id.split(".", 1)[0],
        "unit": unit,
        "unique_id": unique_id,
        "device_name": device_name,
    }


P210M_ROWS = [
    row("switch.kitchen_4_p1", "Kitchen 4-P1", unique_id="mac_P1_state", device_name="Kitchen Outlet 4"),
    row("switch.kitchen_4_p2", "Kitchen 4-P2", unique_id="mac_P2_state", device_name="Kitchen Outlet 4"),
    row("switch.kitchen_outlet_4_led", "LED", unique_id="mac_led", device_name="Kitchen Outlet 4"),
    row("switch.kitchen_outlet_4_auto_update", "Auto-update enabled", unique_id="mac_auto_update_enabled", device_name="Kitchen Outlet 4"),
    row("sensor.kitchen_p1_current", "Current", unit="A", unique_id="mac_P1_current", device_name="Kitchen Outlet 4:P1"),
    row("sensor.kitchen_p1_power", "Current consumption", unit="W", unique_id="mac_P1_current_consumption", device_name="Kitchen Outlet 4:P1"),
    row("sensor.kitchen_p1_voltage", "Voltage", unit="V", unique_id="mac_P1_voltage", device_name="Kitchen Outlet 4:P1"),
    row("number.kitchen_p1_protection", "Power protection", unique_id="mac_P1_power_protection_threshold", device_name="Kitchen Outlet 4:P1"),
    row("switch.kitchen_p1_auto_off", "Auto-off enabled", unique_id="mac_P1_auto_off_enabled", device_name="Kitchen Outlet 4:P1"),
    row("sensor.kitchen_p1_today", "Today's consumption", unit="kWh", unique_id="mac_P1_consumption_today", device_name="Kitchen Outlet 4:P1"),
    row("sensor.kitchen_p1_month", "This month's consumption", unit="kWh", unique_id="mac_P1_consumption_this_month", device_name="Kitchen Outlet 4:P1"),
    row("sensor.kitchen_p2_current", "Current", unit="A", unique_id="mac_P2_current", device_name="Kitchen Outlet 4:P2"),
    row("sensor.kitchen_p2_power", "Current consumption", unit="W", unique_id="mac_P2_current_consumption", device_name="Kitchen Outlet 4:P2"),
    row("sensor.kitchen_p2_voltage", "Voltage", unit="V", unique_id="mac_P2_voltage", device_name="Kitchen Outlet 4:P2"),
    row("number.kitchen_p2_protection", "Power protection", unique_id="mac_P2_power_protection_threshold", device_name="Kitchen Outlet 4:P2"),
    row("switch.kitchen_p2_auto_off", "Auto-off enabled", unique_id="mac_P2_auto_off_enabled", device_name="Kitchen Outlet 4:P2"),
    row("sensor.kitchen_p2_today", "Today's consumption", unit="kWh", unique_id="mac_P2_consumption_today", device_name="Kitchen Outlet 4:P2"),
]


class TplinkOutletTests(unittest.TestCase):
    def test_p210m_maps_plugs_and_skips_kwh(self):
        mapped = classify_entities(P210M_ROWS)
        self.assertEqual(mapped["plug1_switch"], "switch.kitchen_4_p1")
        self.assertEqual(mapped["plug2_switch"], "switch.kitchen_4_p2")
        self.assertEqual(mapped["plug1_power"], "sensor.kitchen_p1_power")
        self.assertEqual(mapped["plug2_power"], "sensor.kitchen_p2_power")
        self.assertEqual(mapped["plug1_current"], "sensor.kitchen_p1_current")
        self.assertEqual(mapped["plug2_current"], "sensor.kitchen_p2_current")
        self.assertEqual(mapped["plug1_voltage"], "sensor.kitchen_p1_voltage")
        self.assertEqual(mapped["plug2_voltage"], "sensor.kitchen_p2_voltage")
        self.assertEqual(mapped["plug1_power_protection"], "number.kitchen_p1_protection")
        self.assertEqual(mapped["plug2_power_protection"], "number.kitchen_p2_protection")
        self.assertEqual(mapped["plug1_auto_off"], "switch.kitchen_p1_auto_off")
        self.assertEqual(mapped["plug2_auto_off"], "switch.kitchen_p2_auto_off")
        self.assertEqual(mapped["led"], "switch.kitchen_outlet_4_led")
        self.assertNotIn("sensor.kitchen_p1_today", mapped.values())
        self.assertNotIn("sensor.kitchen_p1_month", mapped.values())
        self.assertNotIn("sensor.kitchen_p2_today", mapped.values())

    def test_p210m_model_does_not_count_as_p2(self):
        mapped = classify_entities(
            [
                row(
                    "sensor.kitchen_power",
                    "Current consumption",
                    unit="W",
                    unique_id="mac_current_consumption",
                    device_name="Kitchen Outlet 4",
                ),
                row("switch.kitchen_outlet", "Kitchen Outlet 4", unique_id="mac_state", device_name="Kitchen Outlet 4"),
            ]
        )
        self.assertEqual(mapped.get("plug1_power"), "sensor.kitchen_power")
        self.assertEqual(mapped.get("plug1_switch"), "switch.kitchen_outlet")
        self.assertNotIn("plug2_power", mapped)
        self.assertNotIn("plug2_switch", mapped)

    def test_identity_requires_tplink_and_plug_features(self):
        mapped = {"plug1_switch": "switch.kitchen_4_p1"}
        self.assertTrue(
            is_tplink_smart_outlet(
                manufacturer="TP-Link",
                model="P210M",
                identifiers={("tplink", "A8:29")},
                config_domains=["tplink"],
                mapped=mapped,
            )
        )
        self.assertFalse(
            is_tplink_smart_outlet(
                manufacturer="TP-Link",
                model="L530E",
                identifiers={("tplink", "bulb")},
                config_domains=["tplink"],
                mapped={"led": "switch.bulb_led"},
            )
        )
        self.assertFalse(
            is_tplink_smart_outlet(
                manufacturer="Shelly",
                model="Plug S",
                identifiers=set(),
                mapped=mapped,
            )
        )

    def test_internal_shutoff_only_skipped_for_tplink_outlets(self):
        self.assertTrue(
            uses_device_power_protection(
                {"type": "outlet", "outlet_brand": "tplink", "plug1_shutoff": 800}
            )
        )
        self.assertTrue(
            uses_device_power_protection(
                {"type": "single_outlet", "outlet_brand": "tplink"}
            )
        )
        self.assertFalse(
            uses_device_power_protection(
                {"type": "outlet", "outlet_brand": None, "plug1_shutoff": 800}
            )
        )
        self.assertFalse(
            uses_device_power_protection(
                {"type": "minisplit", "outlet_brand": "tplink", "plug1_shutoff": 800}
            )
        )

    def test_mapped_fields_and_normalize(self):
        mapped = classify_entities(P210M_ROWS)
        fields = mapped_fields(mapped)
        self.assertEqual(fields["plug1_entity"], "sensor.kitchen_p1_power")
        self.assertEqual(fields["plug2_entity"], "sensor.kitchen_p2_power")
        self.assertEqual(fields["plug1_switch"], "switch.kitchen_4_p1")
        cleaned = normalize_tplink_map({**mapped, "bogus": "nope", "plug1_power": ""})
        self.assertNotIn("bogus", cleaned)
        self.assertIn("plug1_switch", cleaned)


if __name__ == "__main__":
    unittest.main()
