from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone

import requests

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

BACKEND_URL = "http://localhost:8000/telemetry"
MQTT_HOST = "212.227.88.180"
MQTT_PORT = 1883
MQTT_TOPIC = "nereides/telemetry"

MODES = ["Standby", "Drive", "Boost"]
SAFETY_STATES = ["Nominal", "Nominal", "Nominal", "Warning"]
distance_km = 0.0
start_time = time.time()

GPS_LAT_BASE = 48.2674
GPS_LNG_BASE = 3.7235


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

    gps_lat = round(GPS_LAT_BASE + random.uniform(-0.005, 0.005), 6)
    gps_lng = round(GPS_LNG_BASE + random.uniform(-0.005, 0.005), 6)
    gps_speed = round(random.uniform(5.0, 35.0), 1)
    gps_satellites = random.randint(6, 14)

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
        "gps_lat": gps_lat,
        "gps_lng": gps_lng,
        "gps_speed_kmh": gps_speed,
        "gps_satellites": gps_satellites,
    }


def send_via_http(payload: dict) -> None:
    try:
        response = requests.post(BACKEND_URL, json=payload, timeout=5)
        response.raise_for_status()
        print("HTTP  | Trame envoyee:", payload.get("timestamp"))
    except requests.RequestException as exc:
        print(f"HTTP  | Erreur d'envoi: {exc}")


def send_via_mqtt(mqtt_client, payload: dict) -> None:
    mqtt_client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
    print("MQTT  | Trame publiee:", payload.get("timestamp"))


def main() -> None:
    use_mqtt = MQTT_AVAILABLE
    mqtt_client = None

    if use_mqtt:
        try:
            mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            mqtt_client.connect(MQTT_HOST, MQTT_PORT)
            mqtt_client.loop_start()
            print(f"MQTT connecte a {MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC}")
        except Exception as exc:
            print(f"MQTT indisponible ({exc}), bascule sur HTTP uniquement.")
            use_mqtt = False
            mqtt_client = None

    print(f"Mode: {'MQTT + HTTP' if use_mqtt else 'HTTP uniquement'}")
    print(f"Backend HTTP: {BACKEND_URL}")

    while True:
        payload = build_payload()
        if use_mqtt and mqtt_client is not None:
            send_via_mqtt(mqtt_client, payload)
        else:
            send_via_http(payload)
        time.sleep(1)


if __name__ == "__main__":
    main()
