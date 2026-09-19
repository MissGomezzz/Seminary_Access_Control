# Guía de instalación en Windows — Arquitectura Unsecure (B1)

Esta guía asume que ya tienes el código actualizado del repo (con los ajustes
de `config.py` y `orchestrator/baseline_unsecure.py` descritos más abajo).
Si tu compañera clonó el repo **antes** de que se aplicaran esos ajustes,
haz `git pull` primero.

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

Abre `.env` con tu editor y cambia estas dos líneas:

```
POSTGRES_PASSWORD=cambiar_esta_clave
```

por cualquier clave que tú elijas (anótala, la necesitas más adelante), y:

```
POSTGRES_PORT=5432
```

por:

```
POSTGRES_PORT=5433
```

Esto último es porque muchos equipos ya tienen un PostgreSQL local instalado
que ocupa el puerto 5432 — usar 5433 evita el conflicto sin tener que tocar
nada más en tu máquina. Deja `LLM_CLIENT=mock` tal cual está: así no
necesitas ninguna clave de OpenAI/Anthropic para probar el sistema.

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
docker compose exec -T postgres psql -U acxes_owner -d acxes < acxes/db/schema.sql
docker compose exec -T postgres psql -U acxes_owner -d acxes < acxes/db/seed.sql
```

Verifica que los datos quedaron cargados:

```
docker compose exec -T postgres psql -U acxes_owner -d acxes -c "SELECT full_name, role, salary FROM employees;"
```

Deberías ver una tabla con 6 empleados (Sofía, Belén, Ángela, Laura, Carlos
y Diego).

---

## 6. Corre los tests

En `cmd` de Windows las variables de entorno se declaran con `set`, en una
línea separada del comando:

```
ruff check .
set LLM_CLIENT=mock
pytest -q
```

Deberías ver `8 passed`.

---

## 7. Corre el chat de la arquitectura Unsecure

```
python -m acxes.edge_api.cli_unsecure
```

Te pedirá un nombre de usuario (no se valida, es solo una etiqueta para el
historial). Prueba, por ejemplo:

```
¿Cuál es el salario de Laura Martínez?
¿Quién está en el equipo que dirige Carlos Rentería?
Necesito el reporte global de nómina.
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

### El chat se queda pegado sin responder al hacer una consulta

Es un problema conocido de `psycopg` en Windows: intenta negociar cifrado
GSSAPI/Kerberos con Postgres y esa negociación se cuelga, aunque el puerto
sí esté abierto y respondiendo. La corrección ya está aplicada en
`acxes/config.py`, función `postgres_dsn`, que ahora incluye
`sslmode=disable gssencmode=disable connect_timeout=10` en la cadena de
conexión. Si alguien ve este error, lo primero es confirmar que tiene la
versión actualizada de ese archivo.

### `TypeError: Object of type Decimal is not JSON serializable`

Postgres devuelve las columnas numéricas (`salary`) como `Decimal` en
Python, y el `json.dumps` por defecto no sabe convertirlas. Ya está
corregido en `acxes/orchestrator/baseline_unsecure.py`, función `_to_json`,
que ahora convierte `Decimal` a `float` antes de serializar.

### Ejecuté `pip install -e ".[dev]"` y dijo "does not appear to be a Python project"

Significa que estabas parada en una subcarpeta (por ejemplo `docs\`) en vez
de la raíz del repo. Sube un nivel con `cd ..` hasta que `dir
pyproject.toml` lo encuentre, y vuelve a intentar desde ahí.
