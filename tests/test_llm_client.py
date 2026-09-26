import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.llm_client import LLMClient


def test_base_url_normalization():
    # LM Studio without /v1
    c1 = LLMClient(base_url="http://localhost:1234")
    assert c1.base_url == "http://localhost:1234/v1"

    # LM Studio with /v1
    c2 = LLMClient(base_url="http://localhost:1234/v1")
    assert c2.base_url == "http://localhost:1234/v1"

    # Ollama without /v1
    c3 = LLMClient(base_url="http://localhost:11434")
    assert c3.base_url == "http://localhost:11434/v1"

    # Google Gemini OpenAI compatibility endpoint
    c4 = LLMClient(base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    assert c4.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"

    c5 = LLMClient(base_url="https://generativelanguage.googleapis.com/v1beta/openai")
    assert c5.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"

    # ChatGPT (OpenAI)
    c6 = LLMClient(base_url="https://api.openai.com/v1")
    assert c6.base_url == "https://api.openai.com/v1"

    # Claude (Anthropic)
    c7 = LLMClient(base_url="https://api.anthropic.com/v1", api_key="sk-ant-test")
    assert c7.base_url == "https://api.anthropic.com/v1"
    assert c7._client.default_headers.get("anthropic-version") == "2023-06-01"
    assert c7._client.default_headers.get("x-api-key") == "sk-ant-test"


@pytest.mark.asyncio
async def test_list_models_gemini_filtering_and_sorting():
    client = LLMClient(base_url="https://generativelanguage.googleapis.com/v1beta/openai", api_key="test-key")

    # Mock response.data from models.list()
    mock_data = [
        MagicMock(id="models/gemini-3.8-live"),       # WebSocket only, must be filtered
        MagicMock(id="models/text-embedding-004"),     # Embedding only, must be filtered
        MagicMock(id="models/imagen-3.0-generate-002"),# Image only, must be filtered
        MagicMock(id="models/aqa"),                   # AQA only, must be filtered
        MagicMock(id="models/gemini-1.5-pro"),         # Valid chat model
        MagicMock(id="models/gemini-2.5-flash"),       # Valid fast chat model
        MagicMock(id="models/gemini-2.0-flash"),       # Valid fast chat model
        MagicMock(id="models/gemini-1.5-flash"),       # Valid fast chat model
    ]

    mock_resp = MagicMock()
    mock_resp.data = mock_data
    client._client.models.list = AsyncMock(return_value=mock_resp)

    models = await client.list_models()

    # Ensure live, embed, imagen, and aqa models are excluded
    assert "gemini-3.8-live" not in models
    assert "models/gemini-3.8-live" not in models
    assert "text-embedding-004" not in models
    assert "imagen-3.0-generate-002" not in models
    assert "aqa" not in models

    # Ensure valid models are present without 'models/' prefix
    assert "gemini-2.5-flash" in models
    assert "gemini-2.0-flash" in models
    assert "gemini-1.5-flash" in models
    assert "gemini-1.5-pro" in models

    # Ensure flash models are prioritized to the top
    assert models[0].startswith("gemini-") and "flash" in models[0]
    assert models[1].startswith("gemini-") and "flash" in models[1]
    assert models[2].startswith("gemini-") and "flash" in models[2]
    # Pro model follows flash models
    assert models.index("gemini-1.5-pro") > models.index("gemini-1.5-flash")


@pytest.mark.asyncio
async def test_call_chat_completions_cloud_vs_local():
    client = LLMClient(base_url="http://localhost:1234/v1")
    client._client.chat.completions.create = AsyncMock()

    messages = [{"role": "user", "content": "Hello"}]

    # Test cloud model: gemini-2.5-flash -> must NOT append <think> assistant message
    await client._call_chat_completions(messages, active_model="gemini-2.5-flash")
    sent_msgs_gemini = client._client.chat.completions.create.call_args.kwargs["messages"]
    assert len(sent_msgs_gemini) == 1
    assert sent_msgs_gemini[0]["role"] == "user"

    # Test cloud model: gpt-4o-mini -> must NOT append <think> assistant message
    await client._call_chat_completions(messages, active_model="gpt-4o-mini")
    sent_msgs_gpt = client._client.chat.completions.create.call_args.kwargs["messages"]
    assert len(sent_msgs_gpt) == 1
    assert sent_msgs_gpt[0]["role"] == "user"

    # Test cloud model: claude-3-5-haiku -> must NOT append <think> assistant message
    await client._call_chat_completions(messages, active_model="claude-3-5-haiku-20241022")
    sent_msgs_claude = client._client.chat.completions.create.call_args.kwargs["messages"]
    assert len(sent_msgs_claude) == 1
    assert sent_msgs_claude[0]["role"] == "user"

    # Test local model: qwen2.5-7b -> must append <think> assistant message for reasoning suppression
    await client._call_chat_completions(messages, active_model="qwen2.5-7b-instruct")
    sent_msgs_qwen = client._client.chat.completions.create.call_args.kwargs["messages"]
    assert len(sent_msgs_qwen) == 2
    assert sent_msgs_qwen[1]["role"] == "assistant"
    assert "<think>" in sent_msgs_qwen[1]["content"]
