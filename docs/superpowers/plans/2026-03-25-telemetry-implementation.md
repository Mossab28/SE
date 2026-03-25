# Nereides Telemetry System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire real GPS data from an ESP32 through a mini PC and MQTT to a VPS running InfluxDB/Grafana/WebSocket, replacing the current simulator-only setup.

**Architecture:** ESP32 reads GPS via TinyGPS++, sends JSON over USB serial to a Windows mini PC. The mini PC publishes via MQTT (paho-mqtt) to Mosquitto on the VPS. Telegraf bridges MQTT to InfluxDB. The FastAPI backend subscribes to MQTT and broadcasts via WebSocket to the frontend dashboard.

**Tech Stack:** Arduino/C++ (ESP32), Python 3 (mini PC + backend), Docker (Mosquitto, Telegraf, InfluxDB, Grafana), vanilla JS (frontend)

**Spec:** `docs/superpowers/specs/2026-03-25-telemetry-architecture-design.md`

---

## File Structure

### New files
- `esp32/gps_serial.ino` — ESP32 firmware: read GPS, output JSON on USB serial
- `mini-pc/serial_to_mqtt.py` — Read USB serial, publish to MQTT
- `mini-pc/requirements.txt` — pyserial, paho-mqtt, python-dotenv
- `mini-pc/.env.example` — Template config for serial port and MQTT host
- `vps/docker-compose.yml` — Full stack: Mosquitto + Telegraf + InfluxDB + Grafana + Backend
- `vps/mosquitto.conf` — Mosquitto broker config
- `vps/telegraf.conf` — Telegraf MQTT→InfluxDB bridge config
- `vps/Dockerfile` — Dockerfile for the FastAPI backend

### Modified files
- `backend.py` — Add MQTT subscriber, GPS fields to TelemetryFrame, staleness detection
- `script.js:1-16,57-59` — Add GPS fields, point WebSocket URL to VPS
- `index.html:46-83` — Add GPS panel to dashboard
- `requirements.txt` — Add paho-mqtt

---

## Task 1: ESP32 GPS Firmware

**Files:**
- Create: `esp32/gps_serial.ino`

**Independent task — no dependencies.**

- [ ] **Step 1: Create the ESP32 firmware**

```cpp
// esp32/gps_serial.ino
#include <TinyGPS++.h>
#include <HardwareSerial.h>

TinyGPSPlus gps;
HardwareSerial SerialGPS(1);
unsigned long lastSend = 0;

void setup() {
  Serial.begin(115200);
  SerialGPS.begin(9600, SERIAL_8N1, 16, 17);
  Serial.println("GPS_SERIAL_READY");
}

void loop() {
  while (SerialGPS.available() > 0) {
    gps.encode(SerialGPS.read());
  }

  if (gps.location.isUpdated()) {
    Serial.print("{\"gps_lat\":");
    Serial.print(gps.location.lat(), 6);
    Serial.print(",\"gps_lng\":");
    Serial.print(gps.location.lng(), 6);
    Serial.print(",\"gps_speed_kmh\":");
    Serial.print(gps.speed.kmph(), 1);
    Serial.print(",\"gps_satellites\":");
    Serial.print(gps.satellites.value());
    Serial.println("}");
    lastSend = millis();
  } else if (millis() - lastSend >= 1000) {
    // No fix — send null values every 1s
    Serial.println("{\"gps_lat\":null,\"gps_lng\":null,\"gps_speed_kmh\":null,\"gps_satellites\":0}");
    lastSend = millis();
  }
}
```

- [ ] **Step 2: Verify JSON output format**

Flash to ESP32, open Arduino Serial Monitor at 115200 baud. Expected output:
```
GPS_SERIAL_READY
{"gps_lat":48.267340,"gps_lng":4.074356,"gps_speed_kmh":0.0,"gps_satellites":7}
```

- [ ] **Step 3: Commit**

```bash
git add esp32/gps_serial.ino
git commit -m "feat: add ESP32 GPS firmware with JSON serial output"
```

---

## Task 2: Mini PC Serial-to-MQTT Script

**Files:**
- Create: `mini-pc/serial_to_mqtt.py`
- Create: `mini-pc/requirements.txt`
- Create: `mini-pc/.env.example`

**Independent task — no dependencies.**

- [ ] **Step 1: Create requirements.txt**

```
pyserial==3.5
paho-mqtt==2.1.0
python-dotenv==1.1.0
```

- [ ] **Step 2: Create .env.example**

```
SERIAL_PORT=COM3
SERIAL_BAUD=115200
MQTT_HOST=212.227.88.180
MQTT_PORT=1884
MQTT_TOPIC=nereides/telemetry
```

- [ ] **Step 3: Create serial_to_mqtt.py**

```python
"""Read ESP32 JSON from USB serial, publish to MQTT."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import serial
from dotenv import load_dotenv

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM3")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "115200"))
MQTT_HOST = os.getenv("MQTT_HOST", "212.227.88.180")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1884"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "nereides/telemetry")


def connect_serial() -> serial.Serial:
    """Connect to serial port with retry."""
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
            print(f"Serie connectee sur {SERIAL_PORT}")
            return ser
        except serial.SerialException:
            print(f"Port {SERIAL_PORT} indisponible, retry dans 2s...")
            time.sleep(2)


def connect_mqtt() -> mqtt.Client:
    """Connect to MQTT broker with retry."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT)
            client.loop_start()
            print(f"MQTT connecte a {MQTT_HOST}:{MQTT_PORT}")
            return client
        except Exception:
            print(f"MQTT {MQTT_HOST}:{MQTT_PORT} indisponible, retry dans 2s...")
            time.sleep(2)


def main() -> None:
    ser = connect_serial()
    mqtt_client = connect_mqtt()

    print(f"Bridge actif: {SERIAL_PORT} -> MQTT {MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC}")

    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line or not line.startswith("{"):
                continue

            data = json.loads(line)
            data["timestamp"] = datetime.now(timezone.utc).isoformat()
            data["source"] = "esp32_bateau"

            mqtt_client.publish(MQTT_TOPIC, json.dumps(data), qos=1)
            print(f"Publie: {data}")

        except json.JSONDecodeError:
            print(f"JSON invalide ignore: {line[:80]}")
        except serial.SerialException:
            print("Port serie perdu, reconnexion...")
            ser.close()
            ser = connect_serial()
        except Exception as exc:
            print(f"Erreur: {exc}")
            time.sleep(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Test locally (mock)**

On the mini PC, verify the script starts and attempts to connect:
```bash
cd mini-pc
pip install -r requirements.txt
python serial_to_mqtt.py
# Expected: "Port COM3 indisponible, retry dans 2s..." (if no ESP32 plugged in)
```

- [ ] **Step 5: Commit**

```bash
git add mini-pc/
git commit -m "feat: add mini PC serial-to-MQTT bridge script"
```

---

## Task 3: VPS Docker Stack (Mosquitto + Telegraf)

**Files:**
- Create: `vps/docker-compose.yml`
- Create: `vps/mosquitto.conf`
- Create: `vps/telegraf.conf`
- Create: `vps/Dockerfile`

**Independent task — no dependencies on Task 1 or 2.**

- [ ] **Step 1: Create mosquitto.conf**

```
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
```

- [ ] **Step 2: Create telegraf.conf**

```toml
[agent]
  interval = "1s"
  flush_interval = "1s"

[[inputs.mqtt_consumer]]
  servers = ["tcp://mosquitto:1883"]
  topics = ["nereides/telemetry"]
  data_format = "json"
  json_time_key = "timestamp"
  json_time_format = "2006-01-02T15:04:05Z07:00"
  topic_tag = ""

[[outputs.influxdb_v2]]
  urls = ["http://influxdb:8086"]
  token = "mon-token-telemetry-2024"
  organization = "bateau"
  bucket = "telemetry"
```

- [ ] **Step 3: Create Dockerfile for backend**

This Dockerfile lives in `~/telemetry/` alongside `backend.py` and `requirements.txt` after deploy.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend.py .
CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: Create docker-compose.yml**

```yaml
services:
  influxdb:
    image: influxdb:2.7
    container_name: influxdb
    restart: unless-stopped
    ports:
      - "8086:8086"
    volumes:
      - influxdb-data:/var/lib/influxdb2
    environment:
      DOCKER_INFLUXDB_INIT_MODE: setup
      DOCKER_INFLUXDB_INIT_USERNAME: mossab
      DOCKER_INFLUXDB_INIT_PASSWORD: mossab123influx
      DOCKER_INFLUXDB_INIT_ORG: bateau
      DOCKER_INFLUXDB_INIT_BUCKET: telemetry
      DOCKER_INFLUXDB_INIT_ADMIN_TOKEN: mon-token-telemetry-2024

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3002:3000"
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      GF_SECURITY_ADMIN_USER: mossab
      GF_SECURITY_ADMIN_PASSWORD: mossab123
      GF_SERVER_ROOT_URL: http://212.227.88.180/grafana/
      GF_SERVER_SERVE_FROM_SUB_PATH: "true"
    depends_on:
      - influxdb

  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: unless-stopped
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto.conf:/mosquitto/config/mosquitto.conf
      - mosquitto-data:/mosquitto/data

  telegraf:
    image: telegraf:latest
    container_name: telegraf
    restart: unless-stopped
    volumes:
      - ./telegraf.conf:/etc/telegraf/telegraf.conf:ro
    depends_on:
      - mosquitto
      - influxdb

  backend:
    build: .
    container_name: backend-telemetry
    restart: unless-stopped
    ports:
      - "8001:8000"
    environment:
      INFLUX_URL: http://influxdb:8086
      INFLUX_TOKEN: mon-token-telemetry-2024
      INFLUX_ORG: bateau
      INFLUX_BUCKET: telemetry
      MQTT_HOST: mosquitto
      MQTT_PORT: "1883"
      MQTT_TOPIC: nereides/telemetry
    depends_on:
      - mosquitto
      - influxdb

volumes:
  influxdb-data:
  grafana-data:
  mosquitto-data:
```

- [ ] **Step 5: Commit**

```bash
git add vps/
git commit -m "feat: add VPS Docker stack with Mosquitto, Telegraf, backend"
```

- [ ] **Step 6: Deploy to VPS**

SSH into VPS and deploy (this step is done manually or by the orchestrating agent):
```bash
# On VPS: stop old containers, pull repo, start new stack
cd ~/telemetry && docker compose down
cd ~ && git clone https://github.com/Mossab28/SE.git SE-deploy || (cd ~/SE-deploy && git pull)
# Copy all VPS configs + backend files into ~/telemetry/ (flat, same dir as Dockerfile)
cp ~/SE-deploy/vps/* ~/telemetry/
cp ~/SE-deploy/backend.py ~/telemetry/
cp ~/SE-deploy/requirements.txt ~/telemetry/
cd ~/telemetry && docker compose up -d --build
```

- [ ] **Step 7: Open MQTT port in UFW and add Nginx stream proxy**

```bash
# UFW
sudo ufw allow 1884/tcp

# Nginx stream proxy — add to /etc/nginx/nginx.conf OUTSIDE the http block:
# stream {
#     server {
#         listen 1884;
#         proxy_pass 127.0.0.1:1883;
#     }
# }

# Also add backend WebSocket proxy to the uber-clone server block:
# location /ws {
#     proxy_pass http://127.0.0.1:8001;
#     proxy_http_version 1.1;
#     proxy_set_header Upgrade $http_upgrade;
#     proxy_set_header Connection "upgrade";
#     proxy_set_header Host $host;
#     proxy_set_header X-Real-IP $remote_addr;
# }

sudo nginx -t && sudo systemctl reload nginx
```

- [ ] **Step 8: Test MQTT connectivity**

From local machine:
```bash
# Install mosquitto-clients for testing
# Publish a test message
mosquitto_pub -h 212.227.88.180 -p 1884 -t nereides/telemetry -m '{"timestamp":"2026-03-25T14:00:00Z","source":"test","gps_lat":48.26,"gps_lng":4.07,"gps_speed_kmh":0,"gps_satellites":5}'

# Verify in InfluxDB via Grafana or curl
curl -s -H "Authorization: Token mon-token-telemetry-2024" \
  -H "Content-Type: application/vnd.flux" \
  --data 'from(bucket:"telemetry") |> range(start: -1m) |> limit(n:1)' \
  "http://212.227.88.180/influxdb/api/v2/query?org=bateau"
```

---

## Task 4: Backend — Add MQTT Subscriber + GPS Fields

**Files:**
- Modify: `backend.py:24-42` (add GPS fields to TelemetryFrame)
- Modify: `backend.py` (add MQTT subscriber on startup)
- Modify: `requirements.txt` (add paho-mqtt)

**Depends on:** Task 3 concepts (MQTT topic name), but can be coded independently.

- [ ] **Step 1: Add paho-mqtt to requirements.txt**

Append `paho-mqtt==2.1.0` to `requirements.txt`.

- [ ] **Step 2: Add GPS fields to TelemetryFrame in backend.py**

Add after line 42 (`boat_activity_duration`):
```python
    gps_lat: float | None = None
    gps_lng: float | None = None
    gps_speed_kmh: float | None = None
    gps_satellites: int | None = None
```

- [ ] **Step 3: Add MQTT subscriber to backend.py**

Add imports at top:
```python
import asyncio
import threading
import paho.mqtt.client as mqtt
```

Add MQTT env vars after the INFLUX vars (after line 57):
```python
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "nereides/telemetry")
```

Add MQTT subscriber setup and staleness detection before the routes:
```python
_loop: asyncio.AbstractEventLoop | None = None

def _on_mqtt_message(client, userdata, msg):
    """Called in MQTT thread — schedule coroutine on the main event loop."""
    try:
        raw = json.loads(msg.payload)
        frame = TelemetryFrame(**raw)
        if _loop is not None:
            asyncio.run_coroutine_threadsafe(_process_frame(frame), _loop)
    except Exception as exc:
        print(f"MQTT parse error: {exc}")

async def _process_frame(frame: TelemetryFrame) -> None:
    """Same logic as POST /telemetry, reused for MQTT frames."""
    fields = frame.model_dump(exclude={"timestamp", "source"}, exclude_none=True)
    statuses = build_statuses(frame)
    write_to_influx(frame)
    latest_payload.update({
        "connected": True,
        "fields": fields,
        "statuses": statuses,
        "event": build_event(frame),
    })
    await broadcast(latest_payload)

@app.on_event("startup")
async def startup_event():
    global _loop
    _loop = asyncio.get_event_loop()
    if MQTT_HOST:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.on_message = _on_mqtt_message
        mqtt_client.connect(MQTT_HOST, MQTT_PORT)
        mqtt_client.subscribe(MQTT_TOPIC, qos=1)
        mqtt_client.loop_start()
        print(f"MQTT subscriber: {MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC}")
```

- [ ] **Step 4: Refactor POST /telemetry to use _process_frame**

Replace the body of `ingest_telemetry` (lines 128-143):
```python
@app.post("/telemetry")
async def ingest_telemetry(frame: TelemetryFrame) -> dict[str, str]:
    await _process_frame(frame)
    return {"status": "accepted"}
```

- [ ] **Step 5: Test locally with simulateur.py**

```bash
INFLUX_URL="" uvicorn backend:app --host 0.0.0.0 --port 8000 --reload &
python simulateur.py &
sleep 3
curl -s http://localhost:8000/latest | python3 -m json.tool | head -5
# Expected: {"connected": true, "fields": {...}, ...}
```

Kill both processes after test.

- [ ] **Step 6: Commit**

```bash
git add backend.py requirements.txt
git commit -m "feat: add MQTT subscriber and GPS fields to backend"
```

---

## Task 5: Frontend — Add GPS Display + VPS WebSocket URL

**Files:**
- Modify: `script.js:1-16` (add GPS fields)
- Modify: `script.js:57-59` (change WebSocket URL to VPS)
- Modify: `index.html` (add GPS panel after line 83)

**Depends on:** Task 4 (GPS field names), but can be coded in parallel.

- [ ] **Step 1: Add GPS fields to script.js**

Add to the `fields` object (after line 15, before the closing `};`):
```javascript
  gps_lat: "--",
  gps_lng: "--",
  gps_speed_kmh: "--",
  gps_satellites: "--",
```

- [ ] **Step 2: Change backend URLs to point to VPS**

Replace lines 57-59:
```javascript
const backendHost = "212.227.88.180";
const backendHttpUrl = `http://${backendHost}/backend`;
const backendWsUrl = `ws://${backendHost}/ws`;
```

- [ ] **Step 3: Add GPS panel to index.html**

Insert after the `</section>` closing the spotlight-panel (after line 83):
```html
      <section class="panel">
        <div class="panel-heading">
          <h2>Position GPS</h2>
        </div>
        <div class="metric-grid">
          <article class="metric-card">
            <span class="metric-name">Latitude</span>
            <strong class="metric-value" data-field="gps_lat">--</strong>
            <span class="metric-unit">deg</span>
          </article>
          <article class="metric-card">
            <span class="metric-name">Longitude</span>
            <strong class="metric-value" data-field="gps_lng">--</strong>
            <span class="metric-unit">deg</span>
          </article>
          <article class="metric-card">
            <span class="metric-name">Vitesse</span>
            <strong class="metric-value" data-field="gps_speed_kmh">--</strong>
            <span class="metric-unit">km/h</span>
          </article>
          <article class="metric-card">
            <span class="metric-name">Satellites</span>
            <strong class="metric-value" data-field="gps_satellites">--</strong>
            <span class="metric-unit">sats</span>
          </article>
        </div>
      </section>
```

- [ ] **Step 4: Add staleness detection to script.js**

In the `startAgeTicker` function area (after line 406), add a staleness check that marks connection lost after 5s of no data:

```javascript
function checkStaleness() {
  if (lastTelemetryAt) {
    const elapsed = (Date.now() - lastTelemetryAt.getTime()) / 1000;
    if (elapsed > 5) {
      window.dashboardBridge.setConnectionState(false);
      window.dashboardBridge.pushEvent("Donnees stale — aucune trame depuis 5s.");
    }
  }
}
```

Add `checkStaleness()` call inside the existing `startAgeTicker` interval, by modifying it:
```javascript
function startAgeTicker() {
  clearInterval(ageTimer);
  ageTimer = window.setInterval(() => {
    stampUpdate();
    checkStaleness();
  }, 1000);
}
```

- [ ] **Step 5: Verify dashboard renders GPS section**

Open `index.html` in browser. The GPS panel should show with "--" placeholder values.

- [ ] **Step 6: Commit**

```bash
git add script.js index.html
git commit -m "feat: add GPS panel, staleness detection, and point WebSocket to VPS"
```

---

## Task 6: VPS Nginx — Backend WebSocket + MQTT Stream Proxy

**This task is VPS-side configuration only. Must be done via SSH.**

**Depends on:** Task 3 (containers running).

- [ ] **Step 1: Add Nginx stream block for MQTT**

Add to `/etc/nginx/nginx.conf` (outside `http {}` block):
```nginx
stream {
    server {
        listen 1884;
        proxy_pass 127.0.0.1:1883;
    }
}
```

- [ ] **Step 2: Add backend + WebSocket proxy to uber-clone config**

Add to `/etc/nginx/sites-enabled/uber-clone` inside the server block:
```nginx
      location /backend/ {
          proxy_pass http://127.0.0.1:8001/;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }

      location /ws {
          proxy_pass http://127.0.0.1:8001/ws;
          proxy_http_version 1.1;
          proxy_set_header Upgrade $http_upgrade;
          proxy_set_header Connection "upgrade";
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
      }
```

- [ ] **Step 3: Open port 1884 in UFW**

```bash
sudo ufw allow 1884/tcp
sudo nginx -t && sudo systemctl reload nginx
```

- [ ] **Step 4: Test MQTT from local machine**

```bash
mosquitto_pub -h 212.227.88.180 -p 1884 -t nereides/telemetry \
  -m '{"gps_lat":48.26,"gps_lng":4.07,"gps_speed_kmh":5.2,"gps_satellites":8}'
```

- [ ] **Step 5: Test WebSocket from local machine**

```bash
# Using websocat or browser console:
# ws://212.227.88.180/ws
# Should receive the latest payload as JSON
```

---

## Task Order & Parallelism

```
Task 1 (ESP32)          ─── independent, can run in parallel
Task 2 (Mini PC script) ─── independent, can run in parallel
Task 3 (VPS Docker)     ─── independent, can run in parallel
Task 4 (Backend update) ─── independent code, deploy after Task 3
Task 5 (Frontend update)─── independent code, can run in parallel
Task 6 (VPS Nginx)      ─── depends on Task 3 containers running
```

**Parallel group 1:** Tasks 1, 2, 3, 4, 5 (all code changes)
**Sequential after:** Task 6 (Nginx config on VPS, needs Task 3 deployed)
**Final integration test:** Push repo, deploy to VPS, plug in ESP32 to mini PC, verify end-to-end
