from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import paho.mqtt.client as mqtt
from pydantic import BaseModel, ConfigDict


class TelemetryFrame(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timestamp: str | None = None
    source: str = "simulateur_pc_local"
    battery_temperature: float | None = None
    battery_temp_min: float | None = None
    battery_voltage: float | None = None
    battery_current: float | None = None
    battery_power: float | None = None
    battery_soc: float | None = None
    # Pack en parallele : chaque batterie suivie individuellement
    battery1_soc: float | None = None
    battery1_voltage: float | None = None
    battery1_current: float | None = None
    battery2_soc: float | None = None
    battery2_voltage: float | None = None
    battery2_current: float | None = None
    motor_temperature: float | None = None
    motor_pressure: float | None = None
    motor_speed: float | None = None
    motor_torque: float | None = None
    motor_current: float | None = None
    motor_voltage: float | None = None
    controller_mode: str | None = None
    controller_temperature: float | None = None
    controller_power_request: float | None = None
    controller_efficiency: float | None = None
    controller_safety: str | None = None
    controller_fnb: str | None = None
    controller_feedback: str | None = None
    controller_error_code: int | None = None
    controller_throttle: float | None = None
    boat_distance_km: float | None = None
    boat_activity_duration: str | None = None
    gps_lat: float | None = None
    gps_lng: float | None = None
    gps_speed_kmh: float | None = None
    gps_satellites: int | None = None


latest_payload: dict[str, Any] = {
    "connected": False,
    "fields": {},
    "statuses": {},
    "event": "Backend initialise. En attente de telemetrie.",
}
clients: set[WebSocket] = set()

MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "nereides/telemetry")
AI_PREDICTOR_URL = os.getenv("AI_PREDICTOR_URL", "http://localhost:8002")


NESTED_KEYS = ("Batterie1", "Batterie2", "CM", "GPS")


def _num(source: dict[str, Any], key: str) -> float | None:
    """Extract a numeric value from a nested object, tolerant to missing/invalid."""
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def flatten_nested(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert the embedded nested format (Batterie1/Batterie2/CM/GPS) to flat fields.

    The batteries are wired in PARALLEL: they share the pack voltage and discharge
    simultaneously, so the aggregate voltage is the mean and the aggregate current is
    the sum of both branches. Each branch is also kept individually. Returns `raw`
    unchanged when it is already in the flat format.
    """
    if not any(k in raw for k in NESTED_KEYS):
        return raw

    out: dict[str, Any] = {"source": raw.get("source", "raspberry_bateau")}
    if raw.get("timestamp") is not None:
        out["timestamp"] = raw["timestamp"]

    b1, b2 = raw.get("Batterie1") or {}, raw.get("Batterie2") or {}
    if b1:
        out["battery1_soc"] = _num(b1, "SOC")
        out["battery1_voltage"] = _num(b1, "Tension")
        out["battery1_current"] = _num(b1, "Current")
    if b2:
        out["battery2_soc"] = _num(b2, "SOC")
        out["battery2_voltage"] = _num(b2, "Tension")
        out["battery2_current"] = _num(b2, "Current")

    socs = [x for x in (_num(b1, "SOC"), _num(b2, "SOC")) if x is not None]
    volts = [x for x in (_num(b1, "Tension"), _num(b2, "Tension")) if x is not None]
    currents = [x for x in (_num(b1, "Current"), _num(b2, "Current")) if x is not None]
    if socs:
        out["battery_soc"] = round(sum(socs) / len(socs), 1)
    if volts:
        out["battery_voltage"] = round(sum(volts) / len(volts), 2)  # parallele : tension partagee
    if currents:
        out["battery_current"] = round(sum(currents), 2)  # parallele : les courants s'additionnent
    if volts and currents:
        out["battery_power"] = round((out["battery_voltage"] * out["battery_current"]) / 1000, 2)

    cm = raw.get("CM") or {}
    if cm:
        out["motor_speed"] = _num(cm, "RPM")
        out["motor_current"] = _num(cm, "Current")
        out["motor_voltage"] = _num(cm, "Tension")
        out["motor_temperature"] = _num(cm, "TempMoteur")
        out["controller_temperature"] = _num(cm, "TempCM")
        out["controller_throttle"] = _num(cm, "ThrottleV")
        if cm.get("Commande") is not None:
            out["controller_mode"] = str(cm["Commande"])
        if cm.get("FNB") is not None:
            out["controller_fnb"] = str(cm["FNB"])
        if cm.get("Feedback") is not None:
            out["controller_feedback"] = str(cm["Feedback"])
        err = _num(cm, "ErrorCode")
        if err is not None:
            out["controller_error_code"] = int(err)
            out["controller_safety"] = "Nominal" if int(err) == 0 else "Fault"

    gps = raw.get("GPS") or {}
    if gps:
        out["gps_lat"] = _num(gps, "latitude")
        out["gps_lng"] = _num(gps, "longitude")
        sats = _num(gps, "Satellites")
        if sats is not None:
            out["gps_satellites"] = int(sats)
        vitesse = _num(gps, "vitesse")
        if vitesse is not None:
            out["gps_speed_kmh"] = round(vitesse, 1)  # firmware ESP envoie deja des km/h

    return {k: v for k, v in out.items() if v is not None}


def build_statuses(frame: TelemetryFrame) -> dict[str, dict[str, str]]:
    power_ok = (frame.battery_voltage or 0) >= 45 and (frame.battery_temperature or 0) < 45
    cooling_ok = (frame.motor_temperature or 0) < 85 and (
        frame.motor_pressure is None or frame.motor_pressure >= 1.5
    )
    controller_ok = (frame.controller_safety or "").lower() not in {"fault", "trip", "critical"}

    return {
        "power": {"text": "Operationnelle" if power_ok else "Sur alerte", "tone": "ok" if power_ok else "alert"},
        "cooling": {"text": "Operationnel" if cooling_ok else "A surveiller", "tone": "ok" if cooling_ok else "warn"},
        "controller": {"text": "Nominal" if controller_ok else "Defaut", "tone": "ok" if controller_ok else "alert"},
        "comms": {"text": "Operationnelle", "tone": "ok"},
    }


def build_event(frame: TelemetryFrame) -> str:
    return (
        f"Trame recue de {frame.source} a "
        f"{datetime.now(timezone.utc).astimezone().strftime('%H:%M:%S')}."
    )


async def broadcast(message: dict[str, Any]) -> None:
    dead_clients: list[WebSocket] = []

    for client in clients:
        try:
            await client.send_text(json.dumps(message))
        except Exception:
            dead_clients.append(client)

    for client in dead_clients:
        clients.discard(client)


_loop: asyncio.AbstractEventLoop | None = None


async def _process_frame(frame: TelemetryFrame) -> None:
    """Process a telemetry frame from any source (POST or MQTT)."""
    fields = frame.model_dump(exclude={"timestamp", "source"}, exclude_none=True)
    statuses = build_statuses(frame)
    if "fields" not in latest_payload or not isinstance(latest_payload.get("fields"), dict):
        latest_payload["fields"] = {}
    latest_payload["fields"].update(fields)
    latest_payload["connected"] = True
    latest_payload["statuses"] = statuses
    latest_payload["event"] = build_event(frame)
    await broadcast(latest_payload)


def _on_mqtt_message(client, userdata, msg):
    """Called in MQTT thread — schedule coroutine on the main event loop."""
    try:
        raw = json.loads(msg.payload)
        frame = TelemetryFrame(**flatten_nested(raw))
        if _loop is not None:
            asyncio.run_coroutine_threadsafe(_process_frame(frame), _loop)
    except Exception as exc:
        print(f"MQTT parse error: {exc}")


@asynccontextmanager
async def lifespan(app):
    global _loop
    _loop = asyncio.get_event_loop()
    if MQTT_HOST:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.on_message = _on_mqtt_message
        mqtt_client.connect(MQTT_HOST, MQTT_PORT)
        mqtt_client.subscribe(MQTT_TOPIC, qos=1)
        mqtt_client.loop_start()
        print(f"MQTT subscriber: {MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC}")
    yield


app = FastAPI(title="Telemetry Bridge", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/latest")
def latest() -> dict[str, Any]:
    return latest_payload


@app.get("/predictions")
def predictions() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{AI_PREDICTOR_URL}/predictions", timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"status": "unavailable"}


@app.post("/telemetry")
async def ingest_telemetry(raw: dict[str, Any]) -> dict[str, str]:
    frame = TelemetryFrame(**flatten_nested(raw))
    await _process_frame(frame)
    return {"status": "accepted"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    clients.add(websocket)
    await websocket.send_text(json.dumps(latest_payload))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.discard(websocket)
