# Raspberry Pi - Guide d'acces et architecture

## Acces SSH

```
Host:     NereidesPI2.local  (ou IP directe si mDNS ne fonctionne pas)
User:     nereides
Password: telemetrie26
```

Connexion :
```bash
ssh nereides@NereidesPI2.local
```

> **Note reseau** : Si le Pi est sur un partage de connexion iPhone, le Mac peut
> etre sur un sous-reseau different (192.0.0.x vs 172.20.10.x). Dans ce cas,
> connecter le Mac en Wi-Fi au hotspot (pas en USB) ou utiliser l'IP directe
> obtenue avec `hostname -I` sur le Pi.

## Systeme

- **OS** : Debian 13 (trixie) - Raspberry Pi OS
- **Hostname** : NereidesPI2
- **Python** : 3.13
- **Ecran** : HDMI, mode portrait (xrandr rotate right)
- **Port serie** : `/dev/serial0` a 115200 baud (UART vers ESP32)
- **GPIO** : LED activite (pin 7), LED connexion internet (pin 11)

## Architecture sur le Pi

```
ESP32 (UART /dev/serial0)
        |
        v
  ecran.py (script principal, service systemd "clock.service")
        |
        +---> CSV local      : /home/nereides/data_telemetrie.csv
        +---> Google Sheets  : POST vers Google Apps Script
        +---> Ecran Tkinter  : affichage fullscreen HDMI (portrait)
        +---> MQTT VPS       : 212.227.88.180:1883 topic "nereides/telemetry"
                                  |
                                  +---> Telegraf -> InfluxDB -> Grafana
                                  +---> Backend FastAPI -> WebSocket -> Dashboard
```

## Fichiers importants

| Fichier | Role |
|---------|------|
| `/home/nereides/ecran.py` | Script principal (serie + CSV + Google + ecran + MQTT VPS) |
| `/home/nereides/ecran.py.bak` | Backup avant ajout du MQTT VPS |
| `/home/nereides/envoie_data.py` | Ancienne version (avec MQTT HiveMQ, plus utilisee) |
| `/home/nereides/data_telemetrie.csv` | Historique CSV (~17 Mo) |
| `/home/nereides/google.py` | Helper test Google Sheets |
| `/home/nereides/led.py` | Helper test LED GPIO |

## Service systemd : clock.service

Le script `ecran.py` est lance au boot via un service systemd :

```ini
# /usr/lib/systemd/system/clock.service
[Unit]
Description=Start Clock
After=graphical.target

[Service]
User=nereides
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/nereides/.Xauthority
WorkingDirectory=/home/nereides
ExecStart=/usr/bin/python -u /home/nereides/ecran.py
Restart=always
RestartSec=5s

[Install]
WantedBy=graphical.target
```

Commandes utiles :
```bash
# Voir les logs en temps reel
sudo journalctl -u clock.service -f

# Redemarrer le service
sudo systemctl restart clock.service

# Voir le statut
sudo systemctl status clock.service
```

## Format des donnees ESP32

L'ESP32 envoie du JSON imbrique sur le port serie :
```json
{
  "batterie": {"SOC": 78, "temperature": 35, "Current": 12.5, "Tension": 48.2},
  "CM": {"RPM": 3200, "TempMoteur": 42, "TempCM": 38, "Current": 15, "Tension": 65},
  "GPS": {"latitude": 48.2673, "longitude": 4.0743, "vitesse": 8.5, "Satellites": 7}
}
```

`ecran.py` transforme ce format en JSON plat pour le VPS :
```json
{
  "timestamp": "2026-04-07T13:29:18Z",
  "source": "raspberry_pi",
  "battery_soc": 78,
  "battery_temperature": 35,
  "battery_current": 12.5,
  "battery_voltage": 48.2,
  "motor_speed": 3200,
  "motor_temperature": 42,
  "gps_lat": 48.2673,
  "gps_lng": 4.0743,
  "gps_speed_kmh": 8.5,
  "gps_satellites": 7
}
```

## VPS - Infra

- **IP** : 212.227.88.180
- **Dokploy** : http://212.227.88.180:3000 (gestion des deployements)
- **Dashboard** : http://212.227.88.180/
- **Grafana** : http://212.227.88.180/grafana/ (user: mossab / mossab123)
- **Backend API** : http://212.227.88.180/backend/health
- **WebSocket** : ws://212.227.88.180/ws
- **MQTT Broker** : 212.227.88.180:1883 (topic: nereides/telemetry)
- **Repo GitHub** : https://github.com/Mossab28/SE (auto-deploy via Dokploy)

---

## Ce qui a ete fait (7 avril 2026)

1. **Analyse de la solution existante** sur le Pi (ecran.py avec CSV + Google Sheets + ecran Tkinter)
2. **Ajout du MQTT VPS** dans `ecran.py` : nouveau client MQTT qui publie les donnees vers le VPS (212.227.88.180:1883) en plus de tout ce qui existait deja
3. **Mapping des donnees** : transformation du format ESP32 imbrique vers le format plat attendu par le backend/Telegraf
4. **Migration Dokploy** : passage du compose "raw" vers un compose lie a GitHub avec auto-deploy
5. **Ajout du service frontend** (nginx) dans le docker-compose pour servir le dashboard
6. **Configuration des domaines** Traefik dans Dokploy (/, /grafana, /backend, /ws)

**Rien n'a ete casse** : le CSV, Google Sheets et l'ecran Tkinter fonctionnent toujours comme avant.

---

## Instructions pour remplacer l'UI sur le Pi

> **IMPORTANT** : Ne pas toucher a `ecran.py` ni au service `clock.service`.
> L'ecran Tkinter est dans `ecran.py` qui gere AUSSI la collecte serie,
> le CSV, Google Sheets et le MQTT VPS. Tout est dans le meme script.

### Desactiver l'ecran Tkinter actuel (sans casser la collecte)

L'UI Tkinter est geree par la fonction `gui_watcher()` dans `ecran.py`.
Pour la desactiver sans toucher a la collecte de donnees :

```bash
ssh nereides@NereidesPI2.local

# Editer ecran.py
nano /home/nereides/ecran.py

# Trouver cette ligne (vers la fin du fichier) :
#   threading.Thread(target=gui_watcher, daemon=True).start()
#
# La commenter :
#   #threading.Thread(target=gui_watcher, daemon=True).start()

# Redemarrer le service
sudo systemctl restart clock.service
```

Cela desactive UNIQUEMENT l'affichage Tkinter. La collecte serie, le CSV,
Google Sheets et le MQTT VPS continuent de tourner normalement.

### Pour lancer une nouvelle UI

Creer un nouveau service systemd pour la nouvelle interface :

```bash
sudo nano /etc/systemd/system/nereides-ui.service
```

```ini
[Unit]
Description=Nereides UI
After=graphical.target

[Service]
User=nereides
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/nereides/.Xauthority
WorkingDirectory=/home/nereides
ExecStart=/usr/bin/python -u /home/nereides/nouvelle_ui.py
Restart=always
RestartSec=5s

[Install]
WantedBy=graphical.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable nereides-ui.service
sudo systemctl start nereides-ui.service
```

### Restaurer l'ancien ecran si besoin

```bash
# Decommenter la ligne gui_watcher dans ecran.py
nano /home/nereides/ecran.py
# Enlever le # devant :
#   threading.Thread(target=gui_watcher, daemon=True).start()

sudo systemctl restart clock.service
```
