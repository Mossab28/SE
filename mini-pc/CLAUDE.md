# Contexte Mini PC — Bateau Nereides (bridge télémétrie)

Tu es une instance Claude qui tourne **sur le mini-PC embarqué** (Windows). Le mini-PC est
une **alternative au Raspberry Pi** : il lit la trame série de l'électronique du bateau
(ESP32) et la relaie vers le VPS (MQTT/dashboard/Grafana) + une interface pilote locale.

> ⚠️ **Dernière mise à jour : 2026-07-04.** Fais `git pull` avant tout — le code a beaucoup
> évolué (format imbriqué, GPS en km/h, dossier `pilot-ui/`).

## Chaîne complète

```
[Électronique bateau : 2 batteries (BMS JBD, CAN) + contrôleur moteur CM (CAN) + GPS]
        │ USB Série (115200 baud) — trames JSON imbriquées, 1 ligne = 1 objet {...}
        ▼
[Mini PC]  ← TU ES ICI   (mini-pc/serial_to_mqtt.py)
        ├── MQTT TLS  → VPS 212.227.88.180:8883   (dashboard web + Grafana)
        ├── HTTP POST → https://nereides.pwn-ai.fr/backend/telemetry
        └── WebSocket local :8765 → interface pilote (pilot-ui/, marche sans internet)
        ▼
[VPS] Mosquitto → Telegraf → InfluxDB → Grafana   +   Backend FastAPI → WebSocket → Dashboard
```

## Format des trames (ESP32 → série), depuis le firmware `BoiteTelemMonaco`

Chaque ligne = un objet JSON **imbriqué** partiel. Le CM envoie 2 trames alternées :
```json
{"CM":{"Current":6.1,"RPM":818,"Tension":82.3,"ErrorCode":42}}
{"CM":{"TempMoteur":0,"TempCM":49,"ThrottleV":2.68,"Commande":"Backward","FNB":"B","Feedback":"Backward"}}
{"Batterie1":{"SOC":90,"Tension":48.5,"Current":22,"Protection":0}}
{"Batterie2":{"SOC":88,"Tension":48.6,"Current":24,"Protection":0}}
{"GPS":{"vitesse":12.0,"latitude":48.2675,"longitude":3.7236,"Satellites":9}}
```
- Clés batteries en **majuscule** `Batterie1`/`Batterie2` (aligné avec le mapping de réception).
- **`GPS.vitesse` est en km/h** (le firmware convertit les nœuds ×1.852). NE PAS reconvertir.
- Le BMS **n'envoie pas** de température batterie (que SOC/Tension/Courant/Protection).

## Comment le bridge traite ça (`serial_to_mqtt.py`)

1. Il **relaie la trame brute** (imbriquée) vers MQTT → c'est le **backend VPS** qui l'aplatit
   (`flatten_nested`) → `battery1_*`, `battery2_*`, pack agrégé, `motor_*`, `controller_*`, `gps_*`.
2. En parallèle il **aplatit localement** (copie de `flatten_nested`) pour alimenter le
   **WebSocket pilote** `:8765` (l'UI `pilot-ui/` attend du plat).
3. Modes de test sans matériel : `--fake`, `--scenario`, `--race` (données simulées plates).

## Lancer le système (commandes exactes)

```bat
cd C:\Users\SE\Desktop\SE
git pull

cd mini-pc
pip install -r requirements.txt
copy .env.example .env        REM puis éditer SERIAL_PORT avec le bon COM

REM 1) le bridge (lit le série, publie MQTT + WS pilote)
python serial_to_mqtt.py
REM (ou start_bridge.bat)

REM 2) l'interface pilote (dans 2 autres fenêtres)
serve_pilot.bat               REM sert pilot-ui/ sur http://localhost:8080
launch_kiosk.bat              REM ouvre Chrome/Edge en plein écran
```

`.env` important : `SERIAL_PORT=COMx`, `MQTT_HOST=212.227.88.180`, `MQTT_PORT=8883`,
`MQTT_TLS=true`, `MQTT_TOPIC=nereides/telemetry`.
Trouver le COM : Gestionnaire de périphériques → Ports (COM & LPT) → "USB Serial"/"CP210x"/"CH340".

## Interface pilote — `pilot-ui/`

Fichiers `pilot-ui/index.html` + `script.js` + `styles.css`. Affiche :
Vitesse, **Batterie 1** (SOC/Temp/Courant), **Batterie 2** (SOC/Temp/Courant), **CM** (Temp/Courant).
Se connecte à `ws://localhost:8765` (le bridge). La case Temp batterie reste `--` (BMS ne l'envoie pas).

## Vérifier que ça marche

- Console bridge : `Publie (JSON): {...}` à chaque trame.
- Dashboard web : https://nereides.pwn-ai.fr/ → section « Batteries — pack parallèle ».
- Grafana : http://212.227.88.180/grafana/ (mossab / mossab123), dashboard "Nereides - Telemetrie Bateau".

## Pièges connus / à savoir

- **Horloge du mini-PC** : garde-la à l'heure (NTP Windows). Telegraf horodate désormais à la
  réception côté VPS, donc un décalage n'empêche plus l'affichage Grafana, mais reste propre.
- **Cohérence avec le Raspberry** : les deux produisent les mêmes champs. Seule différence, le
  **pack agrégé** (battery_soc/voltage/current/power) n'est calculé que par le backend (donc via
  le mini-PC il apparaît ; via `ecran.py` du Pi il n'est pas calculé).
- **Température batterie** : indisponible tant que le firmware ne décode pas la trame température
  du BMS JBD (il faut le `tableau_can_batterie.xlsx`).
- **GPS** : ne remonte que si le module GPS est câblé (UART2 GPIO32/33 sur l'ESP) et a un fix.

## Ne PAS refaire

- Ne remets pas de conversion nœuds→km/h sur le GPS : le firmware envoie déjà des km/h.
- Ne repasse pas les clés batteries en minuscule : c'est `Batterie1`/`Batterie2`.
