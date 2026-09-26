"""Pruebas del cliente de Groq con transporte simulado. Sin red y sin gasto."""

import json

import httpx
import pytest

from acxes.orchestrator.groq_client import GroqLLMClient
from acxes.orchestrator.llm_client import (
    LLMInfrastructureError,
    LLMMessage,
    ToolCall,
    ToolSpec,
)
from acxes.orchestrator.tool_catalog import tool_specs
from tests.unit.test_llm_client import _groq_settings

CLAVE = "clave-de-prueba"


def _client(handler, **overrides) -> tuple[GroqLLMClient, list[float]]:
    esperas: list[float] = []
    client = GroqLLMClient(
        _groq_settings(**overrides),
        transport=httpx.MockTransport(handler),
        sleep=esperas.append,
    )
    return client, esperas


def _ok(message: dict, usage: dict | None = None) -> httpx.Response:
    body = {"choices": [{"message": message}], "usage": usage or {}}
    return httpx.Response(200, json=body)


def test_peticion_con_formato_openai_y_herramientas():
    vistas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return _ok({"content": "hola"}, {"prompt_tokens": 10, "completion_tokens": 3})

    client, _ = _client(handler, llm_temperature=0.0, llm_max_tokens=256)
    resp = client.complete("sistema", [LLMMessage("user", "pregunta")], tool_specs())

    req = vistas[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {CLAVE}"
    body = json.loads(req.content)
    assert body["model"] == "modelo-de-prueba"
    assert body["temperature"] == 0.0 and body["max_tokens"] == 256
    assert body["messages"][0] == {"role": "system", "content": "sistema"}
    assert body["messages"][1] == {"role": "user", "content": "pregunta"}
    assert body["tool_choice"] == "auto"
    nombres = [t["function"]["name"] for t in body["tools"]]
    assert nombres == ["buscar_documentos", "leer_documento"]
    assert resp.text == "hola"
    assert resp.usage.prompt_tokens == 10 and resp.usage.completion_tokens == 3


def test_sin_herramientas_no_se_envia_tool_choice():
    vistas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return _ok({"content": "hola"})

    client, _ = _client(handler)
    client.complete("s", [LLMMessage("user", "p")])

    body = json.loads(vistas[0].content)
    assert "tools" not in body and "tool_choice" not in body


def test_el_modo_json_pide_response_format_solo_cuando_se_activa():
    vistas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return _ok({"content": "{}"})

    client, _ = _client(handler)
    client.complete("s", [LLMMessage("user", "p")])
    client.complete("s", [LLMMessage("user", "p")], json_mode=True)

    assert "response_format" not in json.loads(vistas[0].content)
    assert json.loads(vistas[1].content)["response_format"] == {"type": "json_object"}


def test_un_modelo_explicito_sustituye_al_del_agente():
    vistas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return _ok({"content": "hola"})

    client = GroqLLMClient(
        _groq_settings(), model="otro-modelo", transport=httpx.MockTransport(handler)
    )
    client.complete("s", [LLMMessage("user", "p")])

    assert json.loads(vistas[0].content)["model"] == "otro-modelo"


def test_las_llamadas_de_herramienta_se_analizan_y_se_reenvian_con_su_id():
    vistas: list[httpx.Request] = []
    respuestas = [
        _ok(
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_9",
                        "type": "function",
                        "function": {
                            "name": "buscar_documentos",
                            "arguments": '{"keywords": ["a", "b", "c"]}',
                        },
                    }
                ],
            }
        ),
        _ok({"content": "listo"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return respuestas.pop(0)

    client, _ = _client(handler)
    primera = client.complete("s", [LLMMessage("user", "p")], tool_specs())
    assert primera.tool_calls == (
        ToolCall(id="call_9", name="buscar_documentos", arguments={"keywords": ["a", "b", "c"]}),
    )

    historial = [
        LLMMessage("user", "p"),
        LLMMessage("assistant", "", tool_calls=primera.tool_calls),
        LLMMessage("tool", '{"resultados": []}', tool_call_id="call_9"),
    ]
    client.complete("s", historial, tool_specs())

    mensajes = json.loads(vistas[1].content)["messages"]
    assert mensajes[2]["role"] == "assistant" and mensajes[2]["content"] is None
    assert mensajes[2]["tool_calls"][0]["id"] == "call_9"
    assert json.loads(mensajes[2]["tool_calls"][0]["function"]["arguments"]) == {
        "keywords": ["a", "b", "c"]
    }
    assert mensajes[3] == {
        "role": "tool",
        "tool_call_id": "call_9",
        "content": '{"resultados": []}',
    }


def test_argumentos_que_no_son_json_se_marcan_con_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(
            {
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "buscar_documentos", "arguments": "{no es json"},
                    }
                ]
            }
        )

    client, _ = _client(handler)
    resp = client.complete("s", [LLMMessage("user", "p")], tool_specs())

    assert resp.tool_calls[0].error is not None
    assert resp.tool_calls[0].arguments == {}


def test_reintenta_ante_429_respetando_retry_after():
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        if intentos["n"] < 3:
            return httpx.Response(429, headers={"retry-after": "2"}, text="límite")
        return _ok({"content": "ok"})

    client, esperas = _client(handler)
    resp = client.complete("s", [LLMMessage("user", "p")])

    assert resp.text == "ok"
    assert intentos["n"] == 3
    assert esperas == [2.0, 2.0]


def test_error_generico_sin_clave_ni_cuerpo_tras_agotar_los_reintentos():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"detalle interno con {CLAVE}")

    client, esperas = _client(handler, llm_max_retries=2)
    with pytest.raises(LLMInfrastructureError) as info:
        client.complete("s", [LLMMessage("user", "p")])

    assert info.value.status_code == 503
    assert CLAVE not in str(info.value) and "detalle interno" not in str(info.value)
    assert len(esperas) == 2


def test_un_error_de_cliente_no_se_reintenta():
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        return httpx.Response(400, text="mal pedido")

    client, esperas = _client(handler)
    with pytest.raises(LLMInfrastructureError) as info:
        client.complete("s", [LLMMessage("user", "p")])

    assert intentos["n"] == 1 and esperas == []
    assert info.value.status_code == 400


def test_fallo_de_red_se_reintenta_y_luego_es_error_generico():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión", request=request)

    client, esperas = _client(handler, llm_max_retries=1)
    with pytest.raises(LLMInfrastructureError):
        client.complete("s", [LLMMessage("user", "p")])

    assert len(esperas) == 1


def test_respuesta_inesperada_es_error_de_infraestructura():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    client, _ = _client(handler)
    with pytest.raises(LLMInfrastructureError, match="inesperada"):
        client.complete("s", [LLMMessage("user", "p")])


def test_el_esquema_de_las_herramientas_es_cerrado_y_sin_identidad():
    specs: tuple[ToolSpec, ...] = tool_specs()

    for spec in specs:
        props = spec.parameters["properties"]
        assert spec.parameters["additionalProperties"] is False
        assert not {"user_id", "role", "roles", "dept", "clearance", "sql"} & set(props)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.groq.com/openai/v1",
        "https://api.groq.com/openai/v1/",
        "https://api.groq.com/openai/v1/chat/completions",
        "https://api.groq.com/openai/v1/chat/completions/",
    ],
)
def test_la_url_base_se_normaliza_y_el_endpoint_no_se_duplica(base_url):
    vistas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return _ok({"content": "hola"})

    client, _ = _client(handler, llm_base_url=base_url)
    client.complete("s", [LLMMessage("user", "p")])

    assert str(vistas[0].url) == "https://api.groq.com/openai/v1/chat/completions"


def test_un_404_informa_el_codigo_y_el_mensaje_de_groq_sin_reintentar():
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        cuerpo = {"error": {"message": "The model `x` does not exist", "code": "model_not_found"}}
        return httpx.Response(404, json=cuerpo)

    client, esperas = _client(handler)
    with pytest.raises(LLMInfrastructureError) as info:
        client.complete("s", [LLMMessage("user", "p")])

    assert info.value.status_code == 404
    assert "model_not_found" in str(info.value) and "does not exist" in str(info.value)
    assert intentos["n"] == 1 and esperas == []


def test_el_detalle_del_error_no_incluye_la_clave_y_se_trunca():
    def handler(request: httpx.Request) -> httpx.Response:
        mensaje = f"clave {CLAVE} rechazada " + "x" * 500
        return httpx.Response(401, json={"error": {"message": mensaje, "code": "invalid"}})

    client, _ = _client(handler)
    with pytest.raises(LLMInfrastructureError) as info:
        client.complete("s", [LLMMessage("user", "p")])

    assert CLAVE not in str(info.value)
    assert len(str(info.value)) < 300


def test_un_4xx_sin_json_cae_al_mensaje_generico():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<html>no encontrado</html>")

    client, _ = _client(handler)
    with pytest.raises(LLMInfrastructureError) as info:
        client.complete("s", [LLMMessage("user", "p")])

    assert str(info.value) == "El servicio del modelo respondió con estado 404"
