# Exporte tout ce qu'il faut pour reprendre la session Claude sur un autre PC.
# Genere C:\Users\SE\Desktop\nereides-handoff.zip
#
# Contient :
#   - session Claude Code (.jsonl)
#   - mini-pc/.env (config locale)
#   - pilot-preview/ (interface kiosk non versionnee)
#   - nereides_startup.bat (auto-start Windows)
#   - cle SSH du VPS (~/.ssh/vps_pwnai)
#   - RESTORE.md avec les instructions
#
# !!! Le zip contient une cle SSH privee : NE PAS la partager publiquement.

$ErrorActionPreference = "Stop"

$out = "$env:USERPROFILE\Desktop\nereides-handoff"
$zip = "$out.zip"

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
if (Test-Path $zip) { Remove-Item -Force $zip }
New-Item -ItemType Directory -Path $out | Out-Null

# 1) Session Claude Code (.jsonl) + sous-dossier
$claudeProject = "$env:USERPROFILE\.claude\projects\C--Users-SE-Desktop-SE"
if (Test-Path $claudeProject) {
    New-Item -ItemType Directory -Path "$out\claude-session" | Out-Null
    Copy-Item "$claudeProject\*.jsonl" "$out\claude-session\" -ErrorAction SilentlyContinue
    Write-Host "OK session Claude (.jsonl)"
} else {
    Write-Warning "Dossier Claude introuvable: $claudeProject"
}

# 2) Config mini-pc
$env_file = "C:\Users\SE\Desktop\SE\mini-pc\.env"
if (Test-Path $env_file) {
    New-Item -ItemType Directory -Path "$out\mini-pc" | Out-Null
    Copy-Item $env_file "$out\mini-pc\.env"
    Write-Host "OK mini-pc/.env"
}

# 3) Interface kiosk locale (non versionnee)
$pilot = "$env:USERPROFILE\Desktop\pilot-preview"
if (Test-Path $pilot) {
    Copy-Item -Recurse $pilot "$out\pilot-preview"
    Write-Host "OK pilot-preview/"
}

# 4) Script de demarrage Windows
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\nereides_startup.bat"
if (Test-Path $startup) {
    Copy-Item $startup "$out\nereides_startup.bat"
    Write-Host "OK nereides_startup.bat"
}

# 5) Cle SSH VPS
$sshKey = "$env:USERPROFILE\.ssh\vps_pwnai"
if (Test-Path $sshKey) {
    New-Item -ItemType Directory -Path "$out\ssh" | Out-Null
    Copy-Item $sshKey "$out\ssh\vps_pwnai"
    Write-Host "OK cle SSH (PRIVEE - garder confidentielle)"
}

# 6) Instructions de restauration
@'
# Reprise de session Nereides sur un autre PC

## 0. Prerequis
- Windows 10/11
- Git installe (https://git-scm.com)
- Python 3.12 : `winget install Python.Python.3.12` puis FERMER/RELANCER le terminal
- Claude Code installe (https://claude.com/claude-code) + `claude login`

## 1. Cloner le repo (au meme chemin C:\Users\SE\Desktop\SE)

Si l'utilisateur Windows s'appelle "SE" :
```
git clone https://github.com/Mossab28/SE.git C:\Users\SE\Desktop\SE
```

Sinon, adapter le chemin (mais le nom de session Claude changera).

## 2. Restaurer les fichiers depuis ce zip

```powershell
$src = "C:\Users\<user>\Desktop\nereides-handoff"

# Session Claude
$dst = "$env:USERPROFILE\.claude\projects\C--Users-SE-Desktop-SE"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item "$src\claude-session\*.jsonl" $dst

# Config mini-pc
Copy-Item "$src\mini-pc\.env" "C:\Users\SE\Desktop\SE\mini-pc\.env"

# Interface kiosk locale
Copy-Item -Recurse "$src\pilot-preview" "$env:USERPROFILE\Desktop\pilot-preview"

# Script de demarrage
Copy-Item "$src\nereides_startup.bat" "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\"

# Cle SSH VPS (perms strictes)
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
Copy-Item "$src\ssh\vps_pwnai" "$env:USERPROFILE\.ssh\vps_pwnai"
icacls "$env:USERPROFILE\.ssh\vps_pwnai" /inheritance:r /grant:r "${env:USERNAME}:R"
```

## 3. Installer les dependances Python

```
& "C:\Users\SE\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -r C:\Users\SE\Desktop\SE\mini-pc\requirements.txt
```

## 4. Reprendre la session Claude

```
cd C:\Users\SE\Desktop\SE
claude
```
Puis dans Claude : `/resume` et choisir la session.

## 5. Tester

- Brancher l'ESP32 (verifier le port COM dans Gestionnaire de peripheriques, ajuster `mini-pc/.env`)
- Soit redemarrer Windows (le startup lance tout auto)
- Soit lancer manuellement : `mini-pc/test_simulator.bat` pour generer des donnees fake

## URLs

- Dashboard : https://nereides.pwn-ai.fr/
- Backend : https://nereides.pwn-ai.fr/backend/latest
- Grafana : https://nereides.pwn-ai.fr/grafana/
- WebSocket pilote local : ws://localhost:8765
- Interface kiosk local : http://localhost:8088/

## VPS

```
ssh -i ~/.ssh/vps_pwnai mossab@212.227.88.180
```
'@ | Out-File -Encoding utf8 "$out\RESTORE.md"
Write-Host "OK RESTORE.md"

# Creer le zip
Compress-Archive -Path "$out\*" -DestinationPath $zip -Force
Remove-Item -Recurse -Force $out

$size = [Math]::Round((Get-Item $zip).Length / 1MB, 2)
Write-Host ""
Write-Host "===================================" -ForegroundColor Green
Write-Host "Export termine : $zip ($size MB)" -ForegroundColor Green
Write-Host "===================================" -ForegroundColor Green
Write-Host ""
Write-Host "ATTENTION : ce zip contient une cle SSH privee."
Write-Host "Transfert USB only - NE JAMAIS commit ou partager publiquement."
