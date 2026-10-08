"""Aceptación manual del agente S con el modelo real (etapa 4).

Se omite salvo que `.env` tenga LLM_CLIENT=real y LLM_API_KEY, y requiere la base aplicada.
Consume cuota del proveedor. Ejecutar con:

    pytest tests/integration -m llm_real -s

Verifica que una conversación funciona para los tres roles y que el modelo real nunca recibe
fragmentos fuera de lo que el oráculo permite. Imprime cada respuesta para revisión manual.
"""

import psycopg
import pytest

from acxes.config import get_settings, postgres_dsn
from acxes.ingestion.corpus_plan import doc_uuid, load_plan
from acxes.secure_app import build_secure_agent
from tests.rls.contexts import database_pdp, security_context
from tests.rls.oracle import PERSONAS, expected_slugs

pytestmark = [pytest.mark.llm_real, pytest.mark.db]

CONVERSACION = [
    "¿Cuáles son las fechas de pago de la nómina?",
    "¿Y cuánto fue mi salario en la última nómina?",
]


@pytest.mark.parametrize("nombre", ["Sofía", "Carlos", "Diego"])
def test_conversacion_con_el_modelo_real(nombre):
    specs = load_plan()
    slug_by_doc = {doc_uuid(s.slug): s.slug for s in specs}
    with psycopg.connect(postgres_dsn(get_settings()), autocommit=True) as conn:
        chunk_slug = {
            str(cid): slug_by_doc[did]
            for cid, did in conn.execute("SELECT id, doc_id FROM chunks").fetchall()
        }
    agente = build_secure_agent()
    ctx = security_context(nombre, database_pdp())
    permitidos = expected_slugs(PERSONAS[nombre], specs)

    for pregunta in CONVERSACION:
        turno = agente.respond(ctx, pregunta)
        print(f"\n[{nombre}] {pregunta}\n{turno.text}\n{turno.iterations} iteraciones")
        assert turno.text
        assert {chunk_slug[c] for c in turno.chunk_ids} <= permitidos
