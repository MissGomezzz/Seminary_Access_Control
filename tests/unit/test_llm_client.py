import pytest

from acxes.config import Settings
from acxes.orchestrator.llm_client import LLMMessage, MockLLMClient, build_llm_client


def test_default_client_is_mock(monkeypatch):
    monkeypatch.delenv("LLM_CLIENT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_client == "mock"
    assert isinstance(build_llm_client(settings), MockLLMClient)


def test_mock_is_deterministic_and_offline():
    client = MockLLMClient("hola")
    out = client.complete("sistema", [LLMMessage("user", "pregunta")])
    assert out.text == "hola"
    assert out.tool_calls == ()


def test_real_client_not_available_yet():
    settings = Settings(_env_file=None, llm_client="real")
    with pytest.raises(NotImplementedError):
        build_llm_client(settings)


def test_api_key_is_not_exposed_in_repr():
    settings = Settings(_env_file=None, llm_api_key="secreto-de-prueba")
    assert "secreto-de-prueba" not in repr(settings)
