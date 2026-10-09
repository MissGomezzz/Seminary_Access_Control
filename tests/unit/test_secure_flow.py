from uuid import UUID

from acxes.orchestrator.llm_client import LLMResponse, ToolCall, Usage
from acxes.orchestrator.secure import SecureAgent
from acxes.output_guard import guard_output
from acxes.retrieval.types import ChunkHit
from acxes.security_context import SecurityContext
from acxes.tool_gateway import ToolGateway

CTX = SecurityContext(
    user_id=UUID("00000000-0000-4000-a000-000000000001"),
    roles=("empleado",),
    dept="financiera",
    clearance="interno",
    session_id="s-1",
    policy_version="2026-09-21.1",
)


class _Decision:
    allowed = True


class _PDP:
    def evaluate(self, ctx, action, resource):
        assert ctx is CTX
        assert action == "search"
        assert resource == "documentos"
        return _Decision()


class _Retrieval:
    def search(self, ctx, decision, keywords):
        assert ctx is CTX
        assert keywords == ["salario", "propio", "pago"]
        return [ChunkHit("chunk-01", "doc-1", "Nómina", "Salario propio")]


def test_gateway_valida_esquema_y_pasa_contexto_fuera_de_banda():
    gateway = ToolGateway(_PDP(), _Retrieval())

    result = gateway.execute(
        CTX,
        ToolCall("c1", "buscar_documentos", {"keywords": ["salario", "propio", "pago"]}),
    )

    assert result["resultados"][0]["chunk_id"] == "chunk-01"
    assert gateway.execute(CTX, ToolCall("c2", "ejecutar_sql", {})) == {
        "error": "herramienta desconocida: ejecutar_sql"
    }
    assert gateway.execute(
        CTX, ToolCall("c3", "buscar_documentos", {"keywords": ["a", "b", "c"], "user_id": "x"})
    ) == {"error": "argumentos inválidos"}


def test_guard_bloquea_canario_y_fuente_fantasma_y_redacta_pii():
    assert guard_output("dato ACXES-CNRY-A1S7O3FI", ("chunk-01",)).status == "blocked"
    assert guard_output("dato [chunk-99]", ("chunk-01",)).status == "blocked"
    result = guard_output("dato [chunk-01], mail a@ejemplo.com", ("chunk-01",))
    assert result.status == "redacted"
    assert "a@ejemplo.com" not in result.text


class _LLM:
    def __init__(self):
        self.calls = 0

    def complete(self, system, messages, tools=(), *, json_mode=False):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                "",
                (ToolCall("c1", "buscar_documentos", {"keywords": ["salario", "propio", "pago"]}),),
                Usage(1, 2),
            )
        return LLMResponse("Información [chunk-01].", usage=Usage(3, 4))


def test_secure_agent_produce_turn_result_y_no_expone_contexto_al_llm():
    llm = _LLM()
    agent = SecureAgent(llm, ToolGateway(_PDP(), _Retrieval()))

    result = agent.responder(CTX, "¿Cuál es mi salario?")

    assert result.text == "Información [chunk-01]."
    assert result.chunk_ids == ("chunk-01",)
    assert result.prompt_tokens == 4
    assert result.completion_tokens == 6
    assert "00000000" not in agent._historial[0].content
