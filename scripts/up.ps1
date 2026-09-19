# Levanta el entorno completo con un solo comando
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Se creó .env desde .env.example. Revise las claves antes de usar fuera de local."
}

docker compose up -d --wait
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker compose ps
