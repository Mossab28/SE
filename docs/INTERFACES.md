# Interfaces Nereides - Guide des 2 branches

## 2 interfaces, 2 branches, 2 usages

| | Interface Terre | Interface Pilote |
|---|---|---|
| **Branche** | `main` | `pilot` |
| **Usage** | Suivi a distance depuis la terre | Affichage embarque sur le bateau |
| **Deploiement** | VPS (auto-deploy via Dokploy) | Ecran Raspberry Pi (HDMI) |
| **URL** | http://nereides.pwn-ai.fr/ | Pas d'URL, affichage local |
| **Style** | Vert/blanc, dashboard complet | Contraste fort, lecture rapide |
| **Ecran cible** | Desktop/mobile (navigateur) | 7" portrait 480x800 (NHD-7.0-HDMI) |
| **Donnees** | Via WebSocket depuis le backend VPS | Via port serie direct depuis l'ESP32 |

## Branche `main` — Interface Terre

C'est le dashboard de supervision a distance. Il se connecte au backend VPS
via WebSocket et affiche les donnees en temps reel (batterie, moteur, GPS, carte).

- **Auto-deploy** : chaque push sur `main` declenche un redeploy sur le VPS via Dokploy
- **Ne pas mettre l'interface pilote sur `main`** — ca casserait le dashboard terre
- Les fichiers frontend concernes : `index.html`, `script.js`, `styles.css`

### Workflow pour modifier le dashboard terre

```bash
git checkout main
# Modifier index.html, script.js, styles.css
git add index.html script.js styles.css
git commit -m "feat: description du changement"
git push origin main
# -> Dokploy deploie automatiquement sur le VPS
```

## Branche `pilot` — Interface Pilote

C'est l'interface embarquee affichee sur l'ecran HDMI 7 pouces du Raspberry Pi.
Elle est optimisee pour la lecture en navigation : gros chiffres, contraste fort,
viewport 480x800 portrait.

- **Ne se deploie PAS sur le VPS** — elle est uniquement pour le Raspberry Pi
- Elle sera deployee sur le Pi via un service systemd dedie (voir `docs/RASPBERRY_PI_ACCESS.md`)

### Workflow pour modifier l'interface pilote

```bash
git checkout pilot
# Modifier index.html, script.js, styles.css
git add index.html script.js styles.css
git commit -m "feat: description du changement"
git push origin pilot
# -> PAS de deploy auto, il faudra git pull sur le Raspberry
```

### Pour synchroniser pilot avec les changements de main (backend, docs, etc.)

```bash
git checkout pilot
git merge main
git push origin pilot
```

## Architecture des donnees

```
ESP32 (capteurs)
    |
    v
Raspberry Pi (ecran.py)
    |
    +---> Port serie -> Interface Pilote (ecran HDMI local)
    |
    +---> MQTT (212.227.88.180:1883)
              |
              +---> Telegraf -> InfluxDB -> Grafana
              +---> Backend FastAPI -> WebSocket -> Interface Terre
```

Les 2 interfaces recoivent les MEMES donnees, mais par des chemins differents :
- **Pilote** : directement du port serie (temps reel, sans internet)
- **Terre** : via MQTT -> VPS -> WebSocket (necessite internet)

## Fichiers partages entre les 2 branches

Ces fichiers sont les MEMES sur les 2 branches (ne pas les modifier sur `pilot` sans merger depuis `main`) :
- `backend.py` — backend FastAPI
- `vps/` — configuration Docker/VPS
- `docs/` — documentation
- `esp32/` — firmware ESP32
- `raspberry-pi/` — scripts Raspberry

Seuls `index.html`, `script.js` et `styles.css` different entre les 2 branches.
