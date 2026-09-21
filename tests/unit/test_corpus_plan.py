"""Pruebas del plan del corpus contra la composición aprobada. Sin base de datos ni red."""

import re
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from acxes.ingestion.build_plan import build_specs, render_plan
from acxes.ingestion.corpus_plan import (
    PLAN_PATH,
    USER_NAMES,
    DocSpec,
    check_plan,
    doc_uuid,
    load_injections,
    load_plan,
)

SEED = Path(__file__).resolve().parents[2] / "acxes" / "db" / "seed.sql"


def _spec(**cambios) -> DocSpec:
    base = {
        "slug": "documento",
        "title": "Documento",
        "dept": "financiera",
        "sensitivity": "interno",
        "doc_type": "circular",
        "hint": "algo",
        "min_words": 350,
    }
    base.update(cambios)
    return DocSpec(**base)


@pytest.fixture(scope="module")
def plan() -> list[DocSpec]:
    return load_plan()


def test_el_plan_versionado_es_exactamente_lo_que_genera_el_catalogo():
    assert PLAN_PATH.read_text(encoding="utf-8") == render_plan(build_specs())


def test_composicion_por_dependencia_y_nivel(plan):
    esperado = {
        ("institucional", "publico"): 34,
        ("institucional", "interno"): 14,
        ("academica", "interno"): 20,
        ("academica", "confidencial"): 22,
        ("academica", "restringido"): 7,
        ("financiera", "interno"): 20,
        ("financiera", "confidencial"): 26,
        ("financiera", "restringido"): 7,
    }
    assert Counter((s.dept, s.sensitivity) for s in plan) == esperado
    assert len(plan) == 150


def test_institucional_solo_tiene_publico_e_interno(plan):
    assert not [s for s in plan if s.dept == "institucional" and s.carries_canary]


def test_etiquetas_seis_por_dependencia_y_un_restringido_sin_etiqueta_por_dependencia(plan):
    restringidos = [s for s in plan if s.sensitivity == "restringido"]
    etiquetas = Counter(t for s in restringidos for t in s.acl_tags)
    assert etiquetas == {"comite_disciplinario": 6, "auditoria_interna": 6}
    sin_etiqueta = [s for s in restringidos if not s.acl_tags]
    assert sorted(s.dept for s in sin_etiqueta) == ["academica", "financiera"]


def test_los_documentos_con_dueno_son_nominas_y_evaluaciones_de_los_usuarios_de_prueba(plan):
    con_dueno = [s for s in plan if s.owner]
    assert Counter(s.doc_type for s in con_dueno) == {"nomina": 6, "evaluacion": 5}
    assert {s.owner for s in con_dueno if s.doc_type == "nomina"} == set(USER_NAMES)
    assert all(s.sensitivity == "confidencial" for s in con_dueno)
    for s in con_dueno:
        assert s.owner in s.title


def test_los_nombres_de_dueno_coinciden_con_los_usuarios_de_seed_sql():
    sembrados = set(re.findall(r"\('0{8}-0000-4000-a000-\d+', '([^']+)'", SEED.read_text("utf-8")))
    assert sembrados == set(USER_NAMES)


def test_hay_doce_senuelos_publicos_que_apuntan_a_un_tema_reservado(plan):
    por_slug = {s.slug: s for s in plan}
    senuelos = [s for s in plan if s.kind == "senuelo"]
    assert len(senuelos) == 12
    for s in senuelos:
        assert s.sensitivity == "publico" and s.dept == "institucional"
        assert por_slug[s.decoy_of].carries_canary
    # Cubren tanto lo confidencial como lo restringido
    niveles = {por_slug[s.decoy_of].sensitivity for s in senuelos}
    assert niveles == {"confidencial", "restringido"}


def test_hay_ocho_documentos_con_inyeccion_y_cada_carga_existe_una_vez(plan):
    cargas = load_injections()
    inyectados = [s for s in plan if s.kind == "inyeccion"]
    assert len(inyectados) == 8
    assert sorted(s.injection for s in inyectados) == sorted(cargas)
    assert all(s.sensitivity == "publico" for s in inyectados)


def test_slugs_y_titulos_son_unicos_y_los_uuid_son_estables(plan):
    assert len({s.slug for s in plan}) == 150 and len({s.title for s in plan}) == 150
    assert len({doc_uuid(s.slug) for s in plan}) == 150
    assert doc_uuid("x") == doc_uuid("x")


def test_las_etiquetas_no_se_permiten_fuera_de_restringido():
    with pytest.raises(ValidationError, match="solo se permiten en restringido"):
        _spec(acl_tags=("auditoria_interna",))


def test_una_etiqueta_debe_corresponder_a_la_dependencia():
    with pytest.raises(ValidationError, match="no corresponde"):
        _spec(sensitivity="restringido", acl_tags=("comite_disciplinario",))


def test_una_etiqueta_desconocida_se_rechaza():
    with pytest.raises(ValidationError, match="desconocida"):
        _spec(sensitivity="restringido", acl_tags=("inventada",))


def test_el_dueno_debe_ser_un_usuario_de_prueba_y_no_aplica_a_restringido():
    with pytest.raises(ValidationError, match="no es un usuario de prueba"):
        _spec(sensitivity="confidencial", owner="Persona Inventada")
    with pytest.raises(ValidationError, match="solo aplica a interno o confidencial"):
        _spec(sensitivity="restringido", owner="Sofía Ariza")


def test_un_senuelo_debe_ser_publico_y_un_decoy_of_solo_va_en_senuelos():
    with pytest.raises(ValidationError, match="señuelo"):
        _spec(kind="senuelo", decoy_of="otro", sensitivity="interno")
    with pytest.raises(ValidationError, match="solo un señuelo"):
        _spec(decoy_of="otro")


def test_un_senuelo_que_apunta_a_un_documento_no_reservado_se_rechaza():
    publico = _spec(slug="a", title="A", sensitivity="publico")
    senuelo = _spec(slug="b", title="B", sensitivity="publico", kind="senuelo", decoy_of="a")
    with pytest.raises(ValueError, match="decoy_of"):
        check_plan([publico, senuelo])


def test_slugs_repetidos_se_rechazan():
    with pytest.raises(ValueError, match="slugs repetidos"):
        check_plan([_spec(), _spec(title="Otro")])


def test_los_campos_desconocidos_del_plan_se_rechazan():
    with pytest.raises(ValidationError):
        _spec(sensibilidad="publico")
