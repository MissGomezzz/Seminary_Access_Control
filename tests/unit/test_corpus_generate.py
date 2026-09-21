"""Pruebas del generador con un cliente simulado. Sin red y sin gasto."""

import json
from datetime import UTC, datetime

import pytest

from acxes.ingestion.corpus_plan import DocSpec, GeneratedDoc, load_plan
from acxes.ingestion.generate import (
    SYSTEM_PROMPT,
    build_prompt,
    generate_all,
    generate_one,
    people_for,
    validate_body,
    write_doc,
)
from acxes.orchestrator.llm_client import LLMInfrastructureError, LLMMessage, LLMResponse

FECHA = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _spec(**cambios) -> DocSpec:
    base = {
        "slug": "circular-de-prueba",
        "title": "Circular de prueba",
        "dept": "academica",
        "sensitivity": "interno",
        "doc_type": "circular",
        "hint": "fechas del periodo",
        "min_words": 100,
    }
    base.update(cambios)
    return DocSpec(**base)


def _cuerpo(palabras: int = 120) -> str:
    return " ".join(["texto"] * palabras)


def _json(cuerpo: str) -> str:
    return json.dumps({"body": cuerpo})


class Guion:
    """Cliente simulado que devuelve respuestas en orden y registra lo que se le pide."""

    def __init__(self, *respuestas: str | Exception) -> None:
        self._respuestas = list(respuestas)
        self.llamadas: list[tuple[str, list[LLMMessage], bool]] = []

    def complete(self, system, messages, tools=(), *, json_mode=False):
        self.llamadas.append((system, list(messages), json_mode))
        siguiente = self._respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return LLMResponse(text=siguiente)


def test_la_peticion_pide_json_y_no_lleva_clasificacion_ni_identidad():
    cliente = Guion(_json(_cuerpo()))
    generate_one(_spec(sensitivity="confidencial"), cliente)

    system, mensajes, json_mode = cliente.llamadas[0]
    prompt = mensajes[0].content
    assert json_mode is True and system == SYSTEM_PROMPT
    for prohibido in ("confidencial", "restringido", "acl_tags", "owner", "canario", "sensibilidad"):
        assert prohibido not in prompt.lower()


def test_una_salida_valida_se_acepta_al_primer_intento():
    cuerpo, problemas = generate_one(_spec(), Guion(_json(_cuerpo())))
    assert cuerpo == _cuerpo() and problemas == []


@pytest.mark.parametrize(
    ("cuerpo", "fragmento"),
    [
        (_cuerpo(20), "muy corto"),
        (_cuerpo() + " ACXES-CNRY-ABCDEFGH", "canario"),
        (_cuerpo() + " acxes-cnry", "canario"),
        (_cuerpo() + " escriba a juan@ejemplo.com", "correo"),
        (_cuerpo() + " visite https://ejemplo.com", "dirección web"),
        (_cuerpo() + " llame al +57 3001234567", "teléfono"),
        (_cuerpo() + " llame al 300 123 4567", "teléfono"),
        ("```" + _cuerpo(), "bloque de código"),
        ("Lo siento, no puedo ayudar con eso. " + _cuerpo(), "negativa"),
    ],
)
def test_validate_body_rechaza_lo_inaceptable(cuerpo, fragmento):
    problemas = validate_body(_spec(), cuerpo)
    assert any(fragmento in p for p in problemas), problemas


def test_un_monto_en_pesos_no_se_confunde_con_un_telefono():
    assert validate_body(_spec(), _cuerpo() + " El total es $4.200.000 al mes.") == []


def test_una_nomina_debe_nombrar_al_dueno_y_traer_el_salario_del_plan():
    spec = _spec(
        sensitivity="confidencial",
        owner="Sofía Ariza",
        doc_type="nomina",
        hint="Nómina individual de Sofía Ariza. Salario mensual: $4.200.000. Incluir deducciones",
        min_words=100,
    )
    problemas = validate_body(spec, _cuerpo())
    assert any("Sofía Ariza" in p for p in problemas) and any("$4.200.000" in p for p in problemas)
    assert validate_body(spec, _cuerpo() + " Sofía Ariza recibe Salario mensual: $4.200.000") == []


def test_la_salida_que_no_es_el_json_exigido_se_rechaza_y_se_reintenta():
    cliente = Guion("texto sin json", '{"body": "x", "sensitivity": "publico"}', _json(_cuerpo()))
    cuerpo, _ = generate_one(_spec(), cliente)
    assert cuerpo == _cuerpo() and len(cliente.llamadas) == 3


def test_el_reintento_informa_al_modelo_de_por_que_se_rechazo_el_anterior():
    cliente = Guion(_json(_cuerpo(10)), _json(_cuerpo()))
    generate_one(_spec(), cliente)
    assert "muy corto" in cliente.llamadas[1][1][0].content


def test_agotados_los_intentos_no_devuelve_cuerpo_y_explica_el_motivo():
    cliente = Guion(*[_json(_cuerpo(5))] * 3)
    cuerpo, problemas = generate_one(_spec(), cliente, attempts=3)
    assert cuerpo is None and "muy corto" in problemas[0] and len(cliente.llamadas) == 3


def test_el_prompt_solo_ofrece_nombres_ficticios_y_es_determinista():
    spec = _spec(doc_type="acta")
    assert people_for(spec) == people_for(spec)
    assert build_prompt(spec) == build_prompt(spec)
    assert all(nombre in build_prompt(spec) for nombre in people_for(spec))


def test_el_prompt_de_un_senuelo_pide_que_sea_general():
    spec = _spec(
        sensitivity="publico", dept="institucional", kind="senuelo", decoy_of="otro", slug="s", title="S"
    )
    assert "público y general" in build_prompt(spec)


def test_generate_all_escribe_archivos_con_modelo_y_fecha_y_es_reanudable(tmp_path):
    specs = [_spec(slug=f"doc-{i}", title=f"Doc {i}") for i in range(3)]
    cliente = Guion(*[_json(_cuerpo())] * 3)

    primera = generate_all(specs, cliente, "modelo-x", tmp_path, limit=2, now=lambda: FECHA)
    assert primera.generated == ["doc-0", "doc-1"]
    guardado = GeneratedDoc.model_validate_json((tmp_path / "doc-0.json").read_text("utf-8"))
    assert guardado.model == "modelo-x" and guardado.generated_at == "2026-09-21T12:00:00+00:00"
    assert guardado.slug == "doc-0" and guardado.body == _cuerpo()

    segunda = generate_all(specs, cliente, "modelo-x", tmp_path, now=lambda: FECHA)
    assert segunda.skipped == ["doc-0", "doc-1"] and segunda.generated == ["doc-2"]
    assert len(cliente.llamadas) == 3


def test_generate_all_no_escribe_un_documento_rechazado_y_sigue_con_los_demas(tmp_path):
    specs = [_spec(slug="malo", title="Malo"), _spec(slug="bueno", title="Bueno")]
    cliente = Guion(*[_json(_cuerpo(3))] * 3, _json(_cuerpo()))

    reporte = generate_all(specs, cliente, "m", tmp_path)

    assert "malo" in reporte.failed and reporte.generated == ["bueno"]
    assert not (tmp_path / "malo.json").exists() and (tmp_path / "bueno.json").exists()


def test_un_fallo_de_infraestructura_detiene_la_corrida_sin_marcar_el_documento(tmp_path):
    specs = [_spec(slug="a", title="A"), _spec(slug="b", title="B")]
    cliente = Guion(LLMInfrastructureError("cuota agotada", status_code=429))

    reporte = generate_all(specs, cliente, "m", tmp_path)

    assert reporte.infrastructure_error == "cuota agotada"
    assert reporte.generated == [] and reporte.failed == {}
    assert not list(tmp_path.glob("*.json"))


def test_only_limita_los_slugs(tmp_path):
    specs = [_spec(slug="a", title="A"), _spec(slug="b", title="B")]
    reporte = generate_all(specs, Guion(_json(_cuerpo())), "m", tmp_path, only={"b"})
    assert reporte.generated == ["b"]


def test_write_doc_no_deja_temporales(tmp_path):
    write_doc(tmp_path, GeneratedDoc(slug="a", body="x", model="m", generated_at="t"))
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_todos_los_prompts_del_plan_son_construibles_y_sin_clasificacion():
    for spec in load_plan():
        prompt = build_prompt(spec).lower()
        assert spec.title.lower() in prompt
        assert "acl_tags" not in prompt and "canario" not in prompt
