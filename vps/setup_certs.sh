#!/usr/bin/env bash
# Genere des certs self-signed pour le listener TLS de Mosquitto.
# A executer une seule fois sur le VPS, dans le dossier vps/.
# Usage: bash setup_certs.sh
set -euo pipefail

CERTS_DIR="$(dirname "$0")/certs"
mkdir -p "$CERTS_DIR"
cd "$CERTS_DIR"

if [[ -f server.crt ]]; then
  echo "Certs deja presents. Pour regenerer, supprime $CERTS_DIR puis relance."
  exit 0
fi

# 1) CA root
openssl genrsa -out ca.key 2048
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
  -subj "/CN=Nereides-CA"

# 2) Server cert (CN = IP du VPS pour matcher la connexion)
openssl genrsa -out server.key 2048
openssl req -new -out server.csr -key server.key \
  -subj "/CN=212.227.88.180"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 3650

rm -f server.csr ca.srl
chmod 644 *.crt *.key
echo "Certs generes dans $CERTS_DIR :"
ls -la
echo
echo "Maintenant : docker compose up -d --force-recreate mosquitto"
