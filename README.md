# ACXES

Implementación de referencia universitaria de control de acceso para un agente de IA institucional. El modelo no es confiable, así que el dato no autorizado nunca entra a su contexto. Un componente determinista decide la autorización antes de la recuperación.

Este repositorio recoge el seminario de Fundamentos de Seguridad de la Información.

## Puesta en marcha

Requisitos: Docker con Compose y Python 3.12 o superior.

Entorno completo con un solo comando:

```
# Windows
powershell -File scripts/up.ps1

# Linux o macOS
bash scripts/up.sh
```

El script crea `.env` desde `.env.example` si no existe, levanta PostgreSQL con pgvector y Keycloak, y espera a que estén sanos. Las claves de `.env.example` son de ejemplo y deben cambiarse.

## Pruebas

```
pip install -e ".[dev]"
ruff check .
pytest
```

Las pruebas usan un cliente simulado del modelo (`LLM_CLIENT=mock`), sin llamadas de red ni gasto.

## Configuración del modelo

Las variables `LLM_*` no dependen de un proveedor. El límite de gasto se configura manualmente en la consola del proveedor elegido desde el primer día. Las claves solo van en `.env`.

## Documentación

- `Documents/`: matriz de acceso y umbrales de evaluación.
