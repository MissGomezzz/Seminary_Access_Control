#!/usr/bin/env bash
# Levanta el entorno completo con un solo comando
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Se creó .env desde .env.example. Revise las claves antes de usar fuera de local."
fi

docker compose up -d --wait
docker compose ps
