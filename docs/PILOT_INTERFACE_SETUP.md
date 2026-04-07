# Deploiement de l'interface pilote sur le Raspberry Pi

## Contexte

L'interface pilote s'affiche sur l'ecran HDMI 7 pouces (480x800 portrait) du
Raspberry Pi, directement sur le bateau. Elle recoit les donnees en local
depuis `ecran.py` (qui lit le port serie de l'ESP32), sans passer par internet.

**Branche Git** : `pilot`
**Fichiers** : `index.html`, `script.js`, `styles.css`

## Architecture cible

```
ESP32 (UART)
    |
    v
ecran.py (lit le port serie, service clock.service)
    |
    +---> CSV, Google Sheets, MQTT VPS (deja en place, ne pas toucher)
    |
    +---> WebSocket local ws://localhost:8765
              |
              v
         Chromium kiosk mode -> Interface pilote (index.html)
```

L'idee : `ecran.py` envoie les donnees en local via un WebSocket.
L'interface pilote tourne dans un navigateur en plein ecran et se connecte
a ce WebSocket local.

---

## Etape 1 : Se connecter au Raspberry Pi

```bash
ssh nereides@NereidesPI2.local
# Mot de passe : telemetrie26
```

> Si le hostname ne resout pas, utiliser l'IP directe (voir `hostname -I` sur le Pi).

## Etape 2 : Recuperer les fichiers de l'interface pilote

```bash
cd /home/nereides

# Cloner le repo (ou pull si deja present)
git clone -b pilot https://github.com/Mossab28/SE.git pilot-ui
# Ou si le dossier existe deja :
# cd pilot-ui && git pull origin pilot
```

Les fichiers de l'interface seront dans `/home/nereides/pilot-ui/`.

## Etape 3 : Ajouter un WebSocket local dans ecran.py

`ecran.py` lit deja les donnees serie et les traite. Il faut ajouter un
WebSocket local pour que l'interface pilote puisse les recevoir.

### Installer la dependance

```bash
pip install websockets
```

### Modifier ecran.py

Ajouter ces imports en haut du fichier :

```python
import asyncio
import websockets
```

Ajouter ce bloc apres les configs existantes (avant la boucle `while True`) :

```python
# ── WebSocket local pour l'interface pilote ──
ws_clients = set()

async def ws_handler(websocket):
    ws_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        ws_clients.discard(websocket)

async def ws_broadcast(data):
    if ws_clients:
        msg = json.dumps(data)
        await asyncio.gather(
            *[client.send(msg) for client in ws_clients],
            return_exceptions=True
        )

ws_loop = None

async def ws_server():
    global ws_loop
    ws_loop = asyncio.get_event_loop()
    async with websockets.serve(ws_handler, "0.0.0.0", 8765):
        await asyncio.Future()  # tourne indefiniment

def start_ws_server():
    asyncio.run(ws_server())

threading.Thread(target=start_ws_server, daemon=True).start()
```

Puis dans la boucle principale, apres `send_to_vps(payload)`, ajouter :

```python
# Envoi local WebSocket (interface pilote)
if ws_loop and ws_clients:
    flat = flatten_and_map(payload)
    asyncio.run_coroutine_threadsafe(ws_broadcast(flat), ws_loop)
```

### Redemarrer le service

```bash
sudo systemctl restart clock.service
sudo journalctl -u clock.service -f
# Verifier qu'il n'y a pas d'erreur
```

## Etape 4 : Adapter le script.js de l'interface pilote

Dans `/home/nereides/pilot-ui/script.js`, modifier l'URL du WebSocket
pour pointer vers le serveur local au lieu du VPS :

```javascript
// Remplacer l'URL WebSocket existante par :
const WS_URL = "ws://localhost:8765";
```

Le format des donnees recues sera le meme que celui du VPS (JSON plat) :
```json
{
  "timestamp": "2026-04-07T13:29:18Z",
  "source": "raspberry_pi",
  "battery_soc": 78,
  "battery_temperature": 35,
  "motor_speed": 3200,
  "motor_temperature": 42,
  "gps_lat": 48.2673,
  "gps_lng": 4.0743,
  "gps_speed_kmh": 8.5,
  "gps_satellites": 7
}
```

### Mapping des cles ESP32 -> JSON plat

| ESP32 (serie) | Cle JSON |
|---|---|
| batterie / temperature | battery_temperature |
| batterie / TempMax | battery_temperature |
| batterie / TempMin | battery_temp_min |
| batterie / Voltage ou Tension | battery_voltage |
| batterie / Current | battery_current |
| batterie / SOC | battery_soc |
| CM / TempMoteur | motor_temperature |
| CM / TempCM | controller_temperature |
| CM / RPM | motor_speed |
| CM / Current | motor_current |
| CM / Tension | motor_voltage |
| CM / ErrorCode | controller_safety |
| CM / Commande | controller_mode |
| CM / Feedback | controller_feedback |
| CM / FNB | controller_fnb |
| CM / ThrottleV | controller_throttle |
| GPS / latitude | gps_lat |
| GPS / longitude | gps_lng |
| GPS / vitesse | gps_speed_kmh |
| GPS / Satellites | gps_satellites |

## Etape 5 : Servir l'interface pilote en HTTP local

```bash
# Methode simple avec Python
cd /home/nereides/pilot-ui
python -m http.server 8080 &
```

Ou mieux, creer un service systemd pour que ca demarre au boot :

```bash
sudo nano /etc/systemd/system/pilot-http.service
```

```ini
[Unit]
Description=Pilot Interface HTTP Server
After=network.target

[Service]
User=nereides
WorkingDirectory=/home/nereides/pilot-ui
ExecStart=/usr/bin/python -m http.server 8080
Restart=always
RestartSec=3s

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable pilot-http.service
sudo systemctl start pilot-http.service
```

## Etape 6 : Lancer Chromium en mode kiosk

Tester manuellement d'abord :

```bash
export DISPLAY=:0
chromium-browser --kiosk --noerrdialogs --disable-infobars \
  --disable-translate --no-first-run --fast --fast-start \
  --disable-features=TranslateUI --disk-cache-dir=/dev/null \
  http://localhost:8080/index.html &
```

Si ca marche, creer le service systemd :

```bash
sudo nano /etc/systemd/system/pilot-kiosk.service
```

```ini
[Unit]
Description=Pilot Interface Kiosk
After=graphical.target pilot-http.service
Wants=pilot-http.service

[Service]
User=nereides
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/nereides/.Xauthority
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/chromium-browser --kiosk --noerrdialogs --disable-infobars --disable-translate --no-first-run --fast --fast-start --disable-features=TranslateUI --disk-cache-dir=/dev/null http://localhost:8080/index.html
Restart=always
RestartSec=5s

[Install]
WantedBy=graphical.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable pilot-kiosk.service
sudo systemctl start pilot-kiosk.service
```

## Etape 7 : Rotation de l'ecran (si pas deja fait)

L'ecran NHD-7.0-HDMI est en 800x480. Pour le mode portrait (480x800) :

```bash
export DISPLAY=:0
xrandr --output HDMI-A-1 --rotate right
```

Pour que ca persiste au reboot, ajouter dans le fichier autostart :
```bash
mkdir -p /home/nereides/.config/autostart
nano /home/nereides/.config/autostart/rotate-screen.desktop
```

```ini
[Desktop Entry]
Type=Application
Name=Rotate Screen
Exec=sh -c "sleep 2 && xrandr --output HDMI-A-1 --rotate right"
X-GNOME-Autostart-enabled=true
```

---

## Resume des services

| Service | Role | Port |
|---|---|---|
| `clock.service` | Collecte serie + CSV + Google + MQTT VPS + WS local | 8765 (WS) |
| `pilot-http.service` | Sert les fichiers HTML/JS/CSS de l'interface pilote | 8080 |
| `pilot-kiosk.service` | Chromium en plein ecran sur l'interface pilote | - |

## Commandes utiles

```bash
# Logs du collecteur de donnees
sudo journalctl -u clock.service -f

# Redemarrer tout
sudo systemctl restart clock.service
sudo systemctl restart pilot-http.service
sudo systemctl restart pilot-kiosk.service

# Mettre a jour l'interface pilote depuis GitHub
cd /home/nereides/pilot-ui && git pull origin pilot
```

## Ce qu'il ne faut PAS faire

- **Ne pas toucher a `ecran.py` au-dela de l'ajout du WebSocket local** — il gere la collecte serie, le CSV, Google Sheets et le MQTT VPS
- **Ne pas desactiver `clock.service`** — c'est le coeur de la telemetrie
- **Ne pas modifier les fichiers sur la branche `main`** — c'est le dashboard terre (VPS)
- **Toujours travailler sur la branche `pilot`** pour l'interface pilote
