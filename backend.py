from __future__ import annotations

import asyncio
import json
import os
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


def build_statuses(frame: TelemetryFrame) -> dict[str, dict[str, str]]:
    power_ok = (frame.battery_voltage or 0) >= 45 and (frame.battery_temperature or 0) < 45
    cooling_ok = (frame.motor_pressure or 0) >= 1.5 and (frame.motor_temperature or 0) < 85
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
        frame = TelemetryFrame(**raw)
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


@app.post("/telemetry")
async def ingest_telemetry(frame: TelemetryFrame) -> dict[str, str]:
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
