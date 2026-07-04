"""Sert l'interface pilote du repo (pilot-ui/) sur le port 8088, sans cache.

Sert TOUJOURS le dossier pilot-ui/ du repo (versionne, mis a jour par auto_pull),
peu importe le CWD au lancement. Le kiosk Edge pointe sur http://localhost:8088/.
"""
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = int(os.getenv("PILOT_HTTP_PORT", "8088"))
PILOT_DIR = Path(__file__).resolve().parent.parent / "pilot-ui"


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    os.chdir(PILOT_DIR)
    print(f"Interface pilote servie depuis {PILOT_DIR} sur http://0.0.0.0:{PORT}")
    HTTPServer(("0.0.0.0", PORT), NoCacheHandler).serve_forever()
