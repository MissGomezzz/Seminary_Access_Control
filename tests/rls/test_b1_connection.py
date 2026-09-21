"""Guarda de B1: su conexión debe ignorar RLS, o deja de ser una línea base válida.

B1 se conecta con `acxes_owner`, que en el entorno local es superusuario. Si alguien
restringe ese rol, B1 empezaría a respetar RLS y la comparación con S dejaría de medir la
diferencia de arquitectura. Requiere `python -m acxes.db.apply`.
"""

import psycopg
import pytest

from acxes.config import get_settings, postgres_dsn
from acxes.db.repository import PostgresInstitutionalRepository
from acxes.ingestion.canary import canary_for
from acxes.ingestion.corpus_plan import doc_uuid, load_plan

pytestmark = pytest.mark.db

ACTA_COMITE = "acta-del-comite-disciplinario-2026-01"


def test_la_conexion_de_b1_ignora_rls():
    with psycopg.connect(postgres_dsn(get_settings()), autocommit=True) as conn:
        ignora = conn.execute(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()[0]
        total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert ignora is True
    assert total >= len(load_plan())  # al menos un fragmento por documento


def test_el_rol_de_aplicacion_sin_variables_ve_cero_filas_donde_b1_ve_todo():
    with psycopg.connect(postgres_dsn(get_settings(), role="app"), autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0


def test_b1_recupera_un_acta_restringida_sin_ninguna_etiqueta():
    repo = PostgresInstitutionalRepository(get_settings())

    canarios = {
        canary_for(s.slug) for s in load_plan() if "comite_disciplinario" in s.acl_tags
    }

    hits = repo.search_chunks(["acta", "comité", "disciplinario"], 5)
    doc = repo.get_document(doc_uuid(ACTA_COMITE))

    assert any(c in h.content for h in hits for c in canarios)
    assert doc is not None and canary_for(ACTA_COMITE) in doc.chunks[0].content


def test_b1_lista_los_seis_usuarios_de_prueba_con_su_rol():
    usuarios = PostgresInstitutionalRepository(get_settings()).list_users()

    assert {u.role for u in usuarios} == {"empleado", "supervisor", "administrador"}
    assert len(usuarios) == 6
