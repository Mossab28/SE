from __future__ import annotations

import random
import time
from datetime import datetime, timezone

import requests

BACKEND_URL = "http://localhost:8000/telemetry"
MODES = ["Standby", "Drive", "Boost"]
SAFETY_STATES = ["Nominal", "Nominal", "Nominal", "Warning"]
distance_km = 0.0
start_time = time.time()


def build_payload() -> dict:
    global distance_km
    battery_voltage = round(random.uniform(46.0, 52.0), 2)
    battery_current = round(random.uniform(40.0, 160.0), 2)
    battery_power = round((battery_voltage * battery_current) / 1000, 2)
    motor_temperature = round(random.uniform(45.0, 88.0), 1)
    distance_km = round(distance_km + random.uniform(0.03, 0.18), 2)
    elapsed_seconds = int(time.time() - start_time)
    hours = elapsed_seconds // 3600
    minutes = (elapsed_seconds % 3600) // 60
    seconds = elapsed_seconds % 60
    activity_duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "simulateur_pc_local",
        "battery_temperature": round(random.uniform(28.0, 44.0), 1),
        "battery_voltage": battery_voltage,
        "battery_current": battery_current,
        "battery_power": battery_power,
        "motor_temperature": motor_temperature,
        "motor_pressure": round(random.uniform(1.4, 3.8), 2),
        "motor_speed": round(random.uniform(800, 3200), 0),
        "motor_torque": round(random.uniform(50.0, 220.0), 1),
        "controller_mode": random.choice(MODES),
        "controller_power_request": round(random.uniform(10.0, 100.0), 1),
        "controller_efficiency": round(random.uniform(84.0, 97.0), 1),
        "controller_safety": random.choice(SAFETY_STATES),
        "boat_distance_km": distance_km,
        "boat_activity_duration": activity_duration,
    }


def main() -> None:
    print(f"Envoi des trames vers {BACKEND_URL}")

    while True:
        payload = build_payload()
        response = requests.post(BACKEND_URL, json=payload, timeout=5)
        response.raise_for_status()
        print("Trame envoyee:", payload)
        time.sleep(1)


if __name__ == "__main__":
    main()
