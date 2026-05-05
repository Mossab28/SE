"""http.server minimaliste avec headers no-cache pour servir l'interface pilote.

Sert toujours le dossier dans lequel ce script est place, peu importe le CWD
au lancement (utile pour pythonw.exe lance via le startup Windows ou un service).
"""
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    HTTPServer(("0.0.0.0", 8088), NoCacheHandler).serve_forever()
