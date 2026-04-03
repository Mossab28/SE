# Contexte Raspberry Pi 3B+ - Bateau Nereides

## Le projet

Système de télémétrie temps réel pour un bateau électrique (association Nereides, UTT).
La chaîne complète : **ESP32 (GPS) → USB Serial → Raspberry Pi 3B+ → MQTT (4G) → VPS → Dashboard web**

## Architecture déployée

```
[ESP32 + GPS Neo-6M]
        │ USB Serial (115200 baud, JSON)
        ▼
[Raspberry Pi 3B+]  ← TU ES ICI
        │ MQTT publish via 4G
        ▼
[VPS 212.227.88.180]
   ├── Mosquitto (port 1883)
   ├── Telegraf → InfluxDB
   ├── FastAPI backend → WebSocket
   └── Grafana (/grafana/)
        │
        ▼
[Dashboard web] (hébergé sur le VPS via Nginx)
```

## Ce qui est déjà fait

- Le VPS tourne : Mosquitto, InfluxDB, Grafana, Telegraf, Backend (Docker Compose)
- Le dashboard web est hébergé sur le VPS (Nginx reverse proxy)
- Le firmware ESP32 est dans `../esp32/gps_serial.ino`
- Le script bridge `serial_to_mqtt.py` est prêt dans ce dossier

## Ce qu'il faut faire sur ce Raspberry Pi

### 1. Installer les dépendances Python

```bash
cd raspberry-pi
pip3 install -r requirements.txt
```

Si `pip3` échoue (externally-managed-environment sur Bookworm) :
```bash
sudo apt update && sudo apt install -y python3-serial
pip3 install --break-system-packages paho-mqtt python-dotenv
```

### 2. Configurer le .env

Copier `.env.example` en `.env` et ajuster :

```env
SERIAL_PORT=/dev/ttyUSB0    # ← ou /dev/ttyACM0 selon l'ESP32
SERIAL_BAUD=115200
MQTT_HOST=212.227.88.180
MQTT_PORT=1883
MQTT_TOPIC=nereides/telemetry
```

Pour trouver le bon port série :
```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```
Ou brancher/débrancher l'ESP32 et regarder :
```bash
dmesg | tail -10
```

### 3. Permissions port série

```bash
sudo usermod -aG dialout $USER
```
Puis **reboot** le Pi.

### 4. Flasher l'ESP32

Le firmware est dans `../esp32/gps_serial.ino`. Flasher depuis un autre PC (Arduino IDE ou PlatformIO), pas depuis le Pi.
- Bibliothèque **TinyGPS++**
- Board : ESP32 Dev Module
- GPS Neo-6M sur UART1 (RX=GPIO16, TX=GPIO17)

### 5. Lancer le bridge

```bash
python3 serial_to_mqtt.py
```

### 6. Lancement automatique au boot (systemd)

```bash
sudo tee /etc/systemd/system/telemetry-bridge.service << 'EOF'
[Unit]
Description=Telemetry Serial to MQTT Bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/SE/raspberry-pi
ExecStart=/usr/bin/python3 serial_to_mqtt.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable telemetry-bridge
sudo systemctl start telemetry-bridge
```

Adapter `User=` et `WorkingDirectory=` si le user n'est pas `pi`.

Vérifier les logs :
```bash
sudo journalctl -u telemetry-bridge -f
```

### 7. Vérifier que ça marche

- `sudo journalctl -u telemetry-bridge -f` → doit afficher `Publie: {...}`
- Dashboard : http://212.227.88.180/
- Grafana : http://212.227.88.180/grafana/ (mossab / mossab123)

## Format des trames JSON (ESP32 → Serial)

```json
{
  "gps_lat": 48.267340,
  "gps_lng": 3.723456,
  "gps_speed_kmh": 12.5,
  "gps_satellites": 8
}
```

Le bridge ajoute automatiquement :
```json
{
  "timestamp": "2026-03-25T14:30:00+00:00",
  "source": "esp32_bateau"
}
```

## Dépannage

- **Port série introuvable** : `ls /dev/ttyUSB* /dev/ttyACM*` — si rien, vérifier le câble USB
- **Permission denied sur /dev/ttyUSB0** : `sudo usermod -aG dialout $USER` puis reboot
- **MQTT connexion refusée** : vérifier que le Pi a internet (4G) et que le port 1883 est ouvert
- **JSON invalide** : le script ignore les lignes non-JSON (logs ESP32, lignes vides)
- **GPS sans fix** : le Neo-6M peut mettre 30s-2min pour un fix à froid (ciel dégagé nécessaire)
- **pip3 externally-managed** : utiliser `--break-system-packages` ou un venv
