# Guía de instalación en Windows — Arquitectura Unsecure (B1)

Esta guía asume que ya tienes el código actualizado del repo. Si clonaste el
repo **antes** de la versión con el esquema compartido y Groq, haz `git pull`
primero.

Requisitos: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
instalado y abierto, y Python 3.12 o superior.

---

## 1. Clona el repo (si no lo tienes)

```
git clone https://github.com/MissGomezzz/Seminary_Access_Control.git
cd Seminary_Access_Control
```

Si ya lo tienes, solo entra a la carpeta:

```
cd Seminary_Access_Control
```

**Importante**: todos los comandos de aquí en adelante se corren desde la
**raíz** del repo (`Seminary_Access_Control`), nunca desde dentro de
`docs\` ni de ninguna otra subcarpeta.

---

## 2. Crea el entorno virtual e instala dependencias

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Sabrás que el entorno está activo porque tu línea empieza con `(.venv)`.

---

## 3. Crea tu archivo `.env`

```
copy .env.example .env
```

Abre `.env` con tu editor y cambia estas líneas:

```
POSTGRES_PASSWORD=cambiar_esta_clave
POSTGRES_APP_PASSWORD=cambiar_esta_clave_app
POSTGRES_AUDIT_PASSWORD=cambiar_esta_clave_auditoria
```

por claves que tú elijas (anótalas, `POSTGRES_PASSWORD` la necesitas más
adelante). Las otras dos son las claves de los roles de aplicación y de
auditoría que crea el paso 5. Y:

```
POSTGRES_PORT=5432
```

por:

```
POSTGRES_PORT=5433
```

Esto último es porque muchos equipos ya tienen un PostgreSQL local instalado
que ocupa el puerto 5432 — usar 5433 evita el conflicto sin tener que tocar
nada más en tu máquina. Deja `LLM_CLIENT=mock` para probar sin ninguna clave.
Para usar Groq de verdad, pon `LLM_CLIENT=real` y tu clave en `LLM_API_KEY`
(el resto de las variables `LLM_*` ya viene en `.env.example`). Cada valor va
en su propia variable: la clave solo en `LLM_API_KEY`.

---

## 4. Levanta PostgreSQL con Docker

Con Docker Desktop abierto:

```
docker compose up -d --wait postgres
```

La primera vez descarga la imagen y puede tardar uno o dos minutos.
Verifica que quedó sano:

```
docker compose ps
```

Debe verse algo así, con estado `healthy` y el puerto `5433`:

```
NAME                                  ...   STATUS             PORTS
seminary_access_control-postgres-1    ...   Up (healthy)       127.0.0.1:5433->5432/tcp
```

---

## 5. Carga el esquema y los datos de prueba

```
python -m acxes.db.apply
```

Crea las tablas, los roles `acxes_app` y `acxes_audit`, las políticas RLS y un
corpus provisional de 23 documentos con seis usuarios de prueba. Se puede
volver a correr cuando quieras: recrea todo. No necesita `psql`.

Verifica que los datos quedaron cargados:

```
docker compose exec -T postgres psql -U acxes_owner -d acxes -c "SELECT full_name, dept, clearance FROM users;"
```

Deberías ver seis usuarios (Sofía, Belén, Ángela, Laura, Carlos y Diego).

---

## 6. Corre los tests

En `cmd` de Windows las variables de entorno se declaran con `set`, en una
línea separada del comando:

```
ruff check .
set LLM_CLIENT=mock
pytest -q
```

Con la base cargada (paso 5) deberías ver todas las pruebas pasar, incluidas
las de `tests/rls/`. Si la base no está disponible, esas pruebas se omiten y
`pytest` lo indica.

---

## 7. Corre el chat de la arquitectura Unsecure

```
python -m acxes.edge_api.cli_unsecure
```

Te muestra los usuarios de prueba y te deja elegir uno por número (no se
verifica la identidad, ese es el punto de B1). Prueba, por ejemplo:

```
¿Cuál es el salario de Laura Martínez?
Necesito el presupuesto detallado por centro de costo.
Necesito el acta del comité disciplinario.
```

Escribe `salir` para terminar.

---

## Problemas conocidos y cómo se resolvieron

Estos ya están corregidos en el código que vas a clonar/actualizar, pero se
documentan aquí por si alguien los vuelve a ver (por ejemplo, si trabaja
sobre una copia vieja del repo).

### "ports are not available" al levantar Docker

Significa que algo en tu equipo ya usa el puerto 5432 (normalmente un
PostgreSQL instalado localmente). Para confirmarlo:

```
netstat -ano | findstr :5432
tasklist /FI "PID eq <el número que te dio arriba>"
```

Si te dice `postgres.exe`, no hace falta desinstalarlo ni detenerlo: basta
con usar `POSTGRES_PORT=5433` en tu `.env`, como en el paso 3.

### Cada conexión a la base tarda 10 segundos

En Windows, `localhost` se resuelve primero a IPv6 (`::1`) y Docker publica el
puerto solo en `127.0.0.1`, así que la conexión espera 10 segundos antes de
probar IPv4. Usa `POSTGRES_HOST=127.0.0.1` en `.env`, que es el valor de
`.env.example` y el predeterminado de `acxes/config.py`.

### El chat se queda pegado sin responder al hacer una consulta

Es un problema conocido de `psycopg` en Windows: intenta negociar cifrado
GSSAPI/Kerberos con Postgres y esa negociación se cuelga, aunque el puerto
sí esté abierto y respondiendo. La corrección ya está aplicada en
`acxes/config.py`, función `postgres_dsn`, que ahora incluye
`sslmode=disable gssencmode=disable connect_timeout=10` en la cadena de
conexión. Si alguien ve este error, lo primero es confirmar que tiene la
versión actualizada de ese archivo.

### `TypeError: Object of type Decimal is not JSON serializable`

Postgres devuelve las columnas numéricas como `Decimal` en Python, y el
`json.dumps` por defecto no sabe convertirlas. Ya está corregido en
`acxes/orchestrator/baseline_unsecure.py`, función `_to_json`, que convierte
`Decimal` a `float` antes de serializar.

### El chat responde "estado 404" al consultar el modelo

Casi siempre es `LLM_BASE_URL`. Debe ser `https://api.groq.com/openai/v1`,
sin `/chat/completions` al final, aunque el cliente ya tolera esa forma. Desde
esta versión el mensaje incluye el código de error de Groq, por ejemplo
`model_not_found` si el identificador de `LLM_MODEL_AGENT` no existe, o
`invalid_api_key` con estado 401 si la clave es incorrecta.

### `pytest` falla con "Input should be 'mock' or 'real'"

Un valor está en la variable equivocada de `.env`, normalmente la clave de
Groq escrita en `LLM_CLIENT` en lugar de `LLM_API_KEY`. `LLM_CLIENT` solo
acepta `mock` o `real`. Corrígelo y no compartas el valor por ningún canal.

### Ejecuté `pip install -e ".[dev]"` y dijo "does not appear to be a Python project"

Significa que estabas parada en una subcarpeta (por ejemplo `docs\`) en vez
de la raíz del repo. Sube un nivel con `cd ..` hasta que `dir
pyproject.toml` lo encuentre, y vuelve a intentar desde ahí.
