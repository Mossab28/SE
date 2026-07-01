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
MQTT_PORT = 8883
MQTT_TLS = True
MQTT_TOPIC = "nereides/telemetry"

COMMANDES = ["Forward", "Forward", "Forward", "Neutral", "Backward"]
ERROR_CODES = [0, 0, 0, 0, 0, 1 << 3]  # majoritairement sain, defaut occasionnel

# SOC des deux batteries en parallele (se dechargent en meme temps)
soc1 = 92.0
soc2 = 91.0

GPS_LAT_BASE = 48.2674
GPS_LNG_BASE = 3.7235


def build_payload() -> dict:
    """Genere une trame au NOUVEAU format imbrique (Batterie1/Batterie2/CM/GPS).

    Les deux batteries sont en parallele : elles partagent la meme tension de bus
    et se dechargent simultanement, donc leur SOC descend en meme temps et leurs
    courants se repartissent la charge totale demandee par le moteur.
    """
    global soc1, soc2

    # Tension de bus partagee (parallele) + petite dispersion par branche
    bus_voltage = round(random.uniform(46.0, 52.0), 2)
    total_current = random.uniform(40.0, 160.0)
    # Repartition ~50/50 avec un desequilibre realiste
    share = random.uniform(0.45, 0.55)
    current1 = round(total_current * share, 2)
    current2 = round(total_current * (1 - share), 2)

    # Decharge simultanee (proportionnelle au courant de chaque branche)
    soc1 = max(0.0, round(soc1 - current1 * 0.0006, 1))
    soc2 = max(0.0, round(soc2 - current2 * 0.0006, 1))

    error_code = random.choice(ERROR_CODES)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "simulateur_pc_local",
        "Batterie1": {
            "SOC": soc1,
            "Tension": round(bus_voltage + random.uniform(-0.2, 0.2), 2),
            "Current": current1,
        },
        "Batterie2": {
            "SOC": soc2,
            "Tension": round(bus_voltage + random.uniform(-0.2, 0.2), 2),
            "Current": current2,
        },
        "CM": {
            "RPM": round(random.uniform(800, 3200), 0),
            "Current": round(total_current, 2),
            "Tension": bus_voltage,
            "ErrorCode": error_code,
            "TempMoteur": round(random.uniform(45.0, 88.0), 1),
            "TempCM": round(random.uniform(30.0, 70.0), 1),
            "ThrottleV": round(random.uniform(0.8, 4.2), 2),
            "Commande": random.choice(COMMANDES),
            "FNB": random.choice(["F", "F", "F", "N", "B"]),
            "Feedback": random.choice(["Forward", "Forward", "Stationary", "Backward"]),
        },
        "GPS": {
            "vitesse": round(random.uniform(3.0, 19.0), 1),  # noeuds
            "latitude": round(GPS_LAT_BASE + random.uniform(-0.005, 0.005), 6),
            "longitude": round(GPS_LNG_BASE + random.uniform(-0.005, 0.005), 6),
            "Satellites": random.randint(6, 14),
        },
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
            if MQTT_TLS:
                import ssl
                mqtt_client.tls_set(cert_reqs=ssl.CERT_NONE)
                mqtt_client.tls_insecure_set(True)
            mqtt_client.connect(MQTT_HOST, MQTT_PORT)
            mqtt_client.loop_start()
            proto = "mqtts" if MQTT_TLS else "mqtt"
            print(f"MQTT connecte a {proto}://{MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC}")
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
