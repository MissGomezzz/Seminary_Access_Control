from pathlib import Path
from uuid import UUID

import pytest

from acxes.pdp.evaluator import ACTIVE_POLICY, PolicyDecisionPoint
from acxes.pdp.model import Predicate, Sensitivity
from acxes.pdp.subject_store import SubjectRecord
from acxes.security_context import SecurityContext

VERSION = "2026-09-21.1"
_USER = "00000000-0000-4000-a000-00000000000{}"


def _ctx(n: int, role: str, dept: str, clearance: str, tags=(), **over) -> SecurityContext:
    fields = {
        "user_id": UUID(_USER.format(n)),
        "roles": (role, "default-roles-acxes", "offline_access"),
        "dept": dept,
        "clearance": clearance,
        "acl_tags": tuple(tags),
        "session_id": "s",
        "policy_version": VERSION,
    }
    fields.update(over)
    return SecurityContext(**fields)


SOFIA = _ctx(1, "empleado", "financiera", "interno")
ANGELA = _ctx(3, "empleado", "academica", "interno")
LAURA = _ctx(4, "supervisor", "financiera", "confidencial", ("auditoria_interna",))
CARLOS = _ctx(5, "supervisor", "academica", "confidencial", ("comite_disciplinario",))
DIEGO = _ctx(6, "administrador", "institucional", "confidencial")


class FakeSubjectStore:
    """Espejo de acxes/db/seed.sql. Los atributos se pueden cambiar en cada prueba."""

    def __init__(self) -> None:
        self.records = {
            SOFIA.user_id: SubjectRecord(("empleado",), "financiera", ()),
            ANGELA.user_id: SubjectRecord(("empleado",), "academica", ()),
            LAURA.user_id: SubjectRecord(("supervisor",), "financiera", ("auditoria_interna",)),
            CARLOS.user_id: SubjectRecord(("supervisor",), "academica", ("comite_disciplinario",)),
            DIEGO.user_id: SubjectRecord(("administrador",), "institucional", ()),
        }
        self.error: Exception | None = None

    def lookup(self, user_id: UUID) -> SubjectRecord | None:
        if self.error is not None:
            raise self.error
        return self.records.get(user_id)


# Escrito a mano desde documents/MATRIZ_ACCESO.md y P1
ESPERADO = {
    "Sofía": (SOFIA, {"institucional", "financiera"}, Sensitivity.interno, ()),
    "Ángela": (ANGELA, {"institucional", "academica"}, Sensitivity.interno, ()),
    "Laura": (
        LAURA,
        {"institucional", "financiera"},
        Sensitivity.confidencial,
        ("auditoria_interna",),
    ),
    "Carlos": (
        CARLOS,
        {"institucional", "academica"},
        Sensitivity.confidencial,
        ("comite_disciplinario",),
    ),
    "Diego": (
        DIEGO,
        {"institucional", "academica", "financiera"},
        Sensitivity.confidencial,
        (),
    ),
}


@pytest.fixture
def store() -> FakeSubjectStore:
    return FakeSubjectStore()


@pytest.fixture
def pdp(store) -> PolicyDecisionPoint:
    return PolicyDecisionPoint(store)


@pytest.mark.parametrize("nombre", list(ESPERADO))
@pytest.mark.parametrize("action", ["search", "read"])
def test_predicado_esperado_por_persona(pdp, nombre, action):
    ctx, depts, max_level, tags = ESPERADO[nombre]
    decision = pdp.evaluate(ctx, action, "documentos")

    assert decision.allowed and decision.reason == "ok"
    assert decision.policy_version == VERSION
    assert set(decision.predicate.allowed_depts) == depts
    assert decision.predicate.max_sensitivity == max_level
    assert decision.predicate.owner_id == ctx.user_id
    assert decision.predicate.acl_tags == tags
    assert decision.claims_drift == ()


def test_la_version_activa_coincide_con_la_de_la_base(pdp):
    assert pdp.policy_version == VERSION
    seed = Path(__file__).resolve().parents[2] / "acxes" / "db" / "seed.sql"
    assert f"'{VERSION}'" in seed.read_text(encoding="utf-8")


def test_el_rol_y_la_dependencia_de_la_base_quedan_en_la_decision(pdp):
    decision = pdp.evaluate(LAURA, "search", "documentos")
    assert (decision.role, decision.dept) == ("supervisor", "financiera")


def test_nunca_emite_restringido(pdp):
    for ctx, *_ in ESPERADO.values():
        assert pdp.evaluate(ctx, "search", "documentos").predicate.max_sensitivity < (
            Sensitivity.restringido
        )


def test_orden_de_la_sensibilidad():
    assert (
        Sensitivity.publico
        < Sensitivity.interno
        < Sensitivity.confidencial
        < Sensitivity.restringido
    )
    assert [s.name for s in Sensitivity] == ["publico", "interno", "confidencial", "restringido"]


def _deny_reason(pdp, ctx, action="search", resource="documentos") -> str:
    decision = pdp.evaluate(ctx, action, resource)
    assert decision.decision == "deny"
    assert decision.predicate is None and not decision.allowed
    return decision.reason


def test_la_version_del_contexto_debe_coincidir(pdp):
    ctx = SOFIA.model_copy(update={"policy_version": "2026-01-01.1"})
    assert _deny_reason(pdp, ctx) == "policy_version"


# La base prevalece: los claims del token no conceden ni quitan nada y solo se anotan
@pytest.mark.parametrize(
    "over, drift",
    [
        ({"roles": ("administrador",), "clearance": "confidencial"}, ("roles", "clearance")),
        ({"roles": ()}, ("roles",)),
        ({"roles": ("empleado", "supervisor")}, ("roles",)),
        ({"dept": "academica"}, ("dept",)),
        ({"dept": "rectoria"}, ("dept",)),
        ({"clearance": "restringido"}, ("clearance",)),
        ({"acl_tags": ("comite_disciplinario", "auditoria_interna")}, ("acl_tags",)),
    ],
)
def test_los_claims_del_token_no_cambian_la_decision(pdp, over, drift):
    decision = pdp.evaluate(SOFIA.model_copy(update=over), "search", "documentos")

    assert decision.allowed
    assert decision.role == "empleado"
    assert set(decision.predicate.allowed_depts) == {"institucional", "financiera"}
    assert decision.predicate.max_sensitivity == Sensitivity.interno
    assert decision.predicate.acl_tags == ()
    assert decision.claims_drift == drift


def test_revocar_una_etiqueta_en_la_base_surte_efecto_con_el_mismo_token(pdp, store):
    assert pdp.evaluate(CARLOS, "read", "documentos").predicate.acl_tags == (
        "comite_disciplinario",
    )
    store.records[CARLOS.user_id] = SubjectRecord(("supervisor",), "academica", ())

    decision = pdp.evaluate(CARLOS, "read", "documentos")
    assert decision.predicate.acl_tags == ()
    assert decision.claims_drift == ("acl_tags",)


def test_degradar_el_rol_en_la_base_surte_efecto_con_el_mismo_token(pdp, store):
    store.records[LAURA.user_id] = SubjectRecord(("empleado",), "financiera", ())

    decision = pdp.evaluate(LAURA, "search", "documentos")
    assert decision.role == "empleado"
    assert decision.predicate.max_sensitivity == Sensitivity.interno
    assert decision.predicate.acl_tags == ()


def test_conceder_una_etiqueta_en_la_base_surte_efecto_de_inmediato(pdp, store):
    store.records[SOFIA.user_id] = SubjectRecord(
        ("empleado",), "financiera", ("auditoria_interna",)
    )
    assert pdp.evaluate(SOFIA, "search", "documentos").predicate.acl_tags == ("auditoria_interna",)


@pytest.mark.parametrize(
    "record, reason",
    [
        (SubjectRecord((), "financiera", ()), "roles"),
        (SubjectRecord(("superusuario",), "financiera", ()), "roles"),
        (SubjectRecord(("empleado", "supervisor"), "financiera", ()), "roles"),
        (SubjectRecord(("empleado",), "rectoria", ()), "dept"),
    ],
)
def test_denegaciones_por_atributos_de_la_base(pdp, store, record, reason):
    store.records[SOFIA.user_id] = record
    assert _deny_reason(pdp, SOFIA) == reason


def test_usuario_inexistente_en_la_base_se_deniega(pdp):
    ctx = SOFIA.model_copy(update={"user_id": UUID(_USER.format(9))})
    assert _deny_reason(pdp, ctx) == "unknown_user"


def test_fallo_del_almacen_deniega(pdp, store):
    store.error = TimeoutError("statement_timeout")
    assert _deny_reason(pdp, SOFIA) == "subject_error"


def test_un_rol_repetido_en_la_base_cuenta_como_uno(pdp, store):
    store.records[SOFIA.user_id] = SubjectRecord(("empleado", "empleado"), "financiera", ())
    assert pdp.evaluate(SOFIA, "search", "documentos").allowed


@pytest.mark.parametrize("action, resource", [("delete", "documentos"), ("search", "nomina")])
def test_accion_o_recurso_no_permitidos(pdp, action, resource):
    assert _deny_reason(pdp, SOFIA, action, resource) == "action"


def test_sin_archivo_de_politica_deniega_todo(store, tmp_path):
    pdp = PolicyDecisionPoint(store, tmp_path / "2026-09-21.1.yaml")
    assert pdp.policy_version is None
    assert _deny_reason(pdp, SOFIA) == "no_policy"


@pytest.mark.parametrize(
    "contenido",
    [
        "version: [",  # YAML roto
        "version: '2026-09-21.1'\n",  # faltan campos
        ACTIVE_POLICY.read_text(encoding="utf-8").replace(
            "max_sensitivity: interno", "max_sensitivity: restringido"
        ),
        ACTIVE_POLICY.read_text(encoding="utf-8") + "\nextra: 1\n",
        ACTIVE_POLICY.read_text(encoding="utf-8").replace(
            "depts: [institucional]\n    own_dept: true\n  supervisor",
            "depts: [rectoria]\n    own_dept: true\n  supervisor",
        ),
    ],
)
def test_politica_invalida_deniega_todo(store, tmp_path, contenido):
    path = tmp_path / "2026-09-21.1.yaml"
    path.write_text(contenido, encoding="utf-8")
    pdp = PolicyDecisionPoint(store, path)
    assert pdp.policy_version is None
    assert _deny_reason(pdp, SOFIA) == "no_policy"


def test_el_nombre_del_archivo_debe_ser_la_version(store, tmp_path):
    path = tmp_path / "2026-09-22.1.yaml"
    path.write_text(ACTIVE_POLICY.read_text(encoding="utf-8"), encoding="utf-8")
    assert PolicyDecisionPoint(store, path).policy_version is None


def test_tiempo_agotado_deniega(store):
    ticks = iter([0.0, 0.6])
    pdp = PolicyDecisionPoint(store, clock=lambda: next(ticks), timeout_s=0.5)
    assert _deny_reason(pdp, SOFIA) == "timeout"


def test_excepcion_interna_deniega(pdp, monkeypatch):
    def boom(*_):
        raise RuntimeError("fallo")

    monkeypatch.setattr(pdp, "_evaluate", boom)
    assert _deny_reason(pdp, SOFIA) == "error"


def test_predicate_allows_aplica_las_tres_reglas():
    yo = UUID(_USER.format(1))
    otro = UUID(_USER.format(2))
    p = Predicate(("institucional", "financiera"), Sensitivity.interno, yo, ("auditoria_interna",))

    assert p.allows("financiera", "interno", None, ())
    assert not p.allows("financiera", "confidencial", None, ())
    assert not p.allows("academica", "publico", None, ())
    # Propiedad hasta confidencial, en cualquier dependencia
    assert p.allows("academica", "confidencial", yo, ())
    assert not p.allows("academica", "confidencial", otro, ())
    # Restringido solo por etiqueta, nunca por dependencia ni por tope
    assert p.allows("financiera", "restringido", None, ("auditoria_interna",))
    assert not p.allows("financiera", "restringido", None, ())
    assert not Predicate(("financiera",), Sensitivity.restringido, yo, ()).allows(
        "financiera", "restringido", None, ()
    )
