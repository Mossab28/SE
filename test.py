"""Tests unitaires pour backend.py et simulateur.py."""
from __future__ import annotations

import os
import unittest
os.environ.setdefault("MQTT_HOST", "")

from backend import TelemetryFrame, build_statuses, build_event
from simulateur import build_payload


class TestTelemetryFrame(unittest.TestCase):
    def test_minimal_frame(self):
        frame = TelemetryFrame()
        self.assertEqual(frame.source, "simulateur_pc_local")
        self.assertIsNone(frame.gps_lat)

    def test_full_frame(self):
        data = {
            "timestamp": "2026-01-01T00:00:00Z", "source": "test",
            "battery_voltage": 48.0, "battery_temperature": 30.0,
            "motor_temperature": 60.0, "motor_pressure": 2.0,
            "gps_lat": 46.2, "gps_lng": 6.14,
            "gps_speed_kmh": 12.5, "gps_satellites": 10,
        }
        frame = TelemetryFrame(**data)
        self.assertEqual(frame.gps_satellites, 10)

    def test_extra_fields_ignored(self):
        frame = TelemetryFrame(**{"unknown_field": "surprise"})
        self.assertFalse(hasattr(frame, "unknown_field"))


class TestBuildStatuses(unittest.TestCase):
    def test_all_ok(self):
        frame = TelemetryFrame(battery_voltage=48.0, battery_temperature=30.0,
                               motor_pressure=2.5, motor_temperature=60.0,
                               controller_safety="Nominal")
        s = build_statuses(frame)
        self.assertEqual(s["power"]["tone"], "ok")
        self.assertEqual(s["cooling"]["tone"], "ok")
        self.assertEqual(s["controller"]["tone"], "ok")

    def test_low_voltage(self):
        frame = TelemetryFrame(battery_voltage=42.0, battery_temperature=30.0)
        self.assertEqual(build_statuses(frame)["power"]["tone"], "alert")

    def test_high_battery_temp(self):
        frame = TelemetryFrame(battery_voltage=48.0, battery_temperature=46.0)
        self.assertEqual(build_statuses(frame)["power"]["tone"], "alert")

    def test_low_pressure(self):
        frame = TelemetryFrame(motor_pressure=1.0, motor_temperature=60.0)
        self.assertEqual(build_statuses(frame)["cooling"]["tone"], "warn")

    def test_high_motor_temp(self):
        frame = TelemetryFrame(motor_pressure=2.0, motor_temperature=90.0)
        self.assertEqual(build_statuses(frame)["cooling"]["tone"], "warn")

    def test_fault_controller(self):
        frame = TelemetryFrame(controller_safety="fault")
        self.assertEqual(build_statuses(frame)["controller"]["tone"], "alert")

    def test_critical_controller(self):
        frame = TelemetryFrame(controller_safety="critical")
        self.assertEqual(build_statuses(frame)["controller"]["tone"], "alert")


class TestBuildEvent(unittest.TestCase):
    def test_event_contains_source(self):
        frame = TelemetryFrame(source="test_source")
        event = build_event(frame)
        self.assertIn("test_source", event)



class TestSimulateur(unittest.TestCase):
    def test_payload_has_gps_keys(self):
        payload = build_payload()
        for key in ("gps_lat", "gps_lng", "gps_speed_kmh", "gps_satellites"):
            self.assertIn(key, payload)

    def test_gps_ranges(self):
        p = build_payload()
        self.assertGreater(p["gps_lat"], 40.0)
        self.assertLess(p["gps_lat"], 55.0)
        self.assertGreaterEqual(p["gps_satellites"], 6)

    def test_payload_accepted_by_frame(self):
        frame = TelemetryFrame(**build_payload())
        self.assertIsNotNone(frame.gps_lat)


if __name__ == "__main__":
    unittest.main()
