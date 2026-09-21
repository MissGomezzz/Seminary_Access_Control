import pytest

from acxes.config import Settings
from acxes.orchestrator.groq_client import GroqLLMClient
from acxes.orchestrator.llm_client import LLMMessage, MockLLMClient, build_llm_client


def _groq_settings(**overrides) -> Settings:
    values = {
        "llm_client": "real",
        "llm_provider": "groq",
        "llm_base_url": "https://api.groq.com/openai/v1",
        "llm_api_key": "clave-de-prueba",
        "llm_model_agent": "modelo-de-prueba",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


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


def test_real_client_requires_the_groq_provider():
    settings = Settings(_env_file=None, llm_client="real")
    with pytest.raises(ValueError, match="LLM_PROVIDER=groq"):
        build_llm_client(settings)


def test_real_client_requires_complete_configuration():
    settings = _groq_settings(llm_api_key="")
    with pytest.raises(ValueError, match="incompleta"):
        build_llm_client(settings)


def test_real_client_builds_the_groq_client():
    assert isinstance(build_llm_client(_groq_settings()), GroqLLMClient)


def test_api_key_is_not_exposed_in_repr():
    settings = Settings(_env_file=None, llm_api_key="secreto-de-prueba")
    assert "secreto-de-prueba" not in repr(settings)


def test_limits_shared_by_b1_and_s_default_to_the_policy_values():
    settings = Settings(_env_file=None)
    assert settings.agent_max_iterations == 4
    assert settings.retrieval_k == 5
