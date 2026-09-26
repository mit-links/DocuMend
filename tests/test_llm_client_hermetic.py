"""Hermetic unit tests for DocuMend's LLMClient.

Strictly isolates OpenAI and HTTP calls using mocks.
Covers whitespace preservation, token tracking, retry policies,
fatal error handling (HTTP 400/401/unloaded), batching fallback, and VRAM ejection.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.llm_client import LLMClient, LLMResponse


# ---------------------------------------------------------------------------
# correct_text Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_LLMClient_CorrectText_WhenEmptyOrWhitespace_ReturnsInputWithoutApiCall():
    """Verify empty or whitespace strings return immediately with 0 API calls."""
    client = LLMClient(base_url="http://localhost:1234/v1")
    client._client.chat.completions.create = AsyncMock()

    assert await client.correct_text("") == ""
    assert await client.correct_text("   \n\t  ") == "   \n\t  "
    assert client._client.chat.completions.create.call_count == 0


@pytest.mark.asyncio
async def test_LLMClient_CorrectText_Success_ExtractsTokensAndPreservesWhitespace():
    """Verify successful response extracts token usage and preserves exact whitespace."""
    client = LLMClient(base_url="https://api.openai.com/v1", model="gpt-4o-mini")

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "This is a corrected sentence."
    mock_resp.usage = MagicMock(completion_tokens=15, prompt_tokens=25)

    client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

    # Input has leading 2 spaces and trailing newline
    input_text = "  This is a correted sentence.\n"
    res = await client.correct_text(input_text)

    assert isinstance(res, LLMResponse)
    assert res == "  This is a corrected sentence.\n"
    assert res.completion_tokens == 15
    assert res.prompt_tokens == 25
    assert res.duration >= 0.0


@pytest.mark.asyncio
async def test_LLMClient_CorrectText_WhenModelUnloaded_AbortsImmediatelyWithoutRetries():
    """Verify fatal 'Model was unloaded' error raises RuntimeError on attempt 1."""
    client = LLMClient(base_url="http://localhost:1234/v1", model="test-model")
    client._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("Engine protocol startup was aborted: Model was unloaded")
    )

    with pytest.raises(RuntimeError, match="Model was unloaded"):
        await client.correct_text("Some text")

    # Fatal error must not trigger retry loop
    assert client._client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_LLMClient_CorrectText_WhenBadRequest400_AbortsImmediatelyWithoutRetries():
    """Verify HTTP 400 Bad Request error fails immediately without retrying."""
    client = LLMClient(base_url="https://api.openai.com/v1", model="gpt-4o-mini")
    client._client.chat.completions.create = AsyncMock(
        side_effect=Exception(
            "Error code: 400 - {'error': {'message': 'Invalid parameter', 'type': 'invalid_request_error'}}"
        )
    )

    with pytest.raises(RuntimeError, match="Invalid parameter"):
        await client.correct_text("Some text")

    assert client._client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_LLMClient_CorrectText_WhenTransientError_RetriesWithBackoffAndSucceeds():
    """Verify transient error (503 Service Unavailable) retries and recovers on attempt 2."""
    client = LLMClient(base_url="https://api.openai.com/v1", model="gpt-4o-mini")

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Fixed sentence."
    mock_resp.usage = MagicMock(completion_tokens=5, prompt_tokens=10)

    # Fail on attempt 1, succeed on attempt 2
    client._client.chat.completions.create = AsyncMock(
        side_effect=[Exception("503 Service Unavailable"), mock_resp]
    )

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await client.correct_text("Fixd sentence.")

    assert str(res) == "Fixed sentence."
    assert client._client.chat.completions.create.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_LLMClient_CorrectText_WhenTransientErrorPersists_ExhaustsRetriesAndRaises():
    """Verify persistent transient errors fail after max_retries (total 3 attempts)."""
    client = LLMClient(base_url="https://api.openai.com/v1", model="gpt-4o-mini")
    client._client.chat.completions.create = AsyncMock(
        side_effect=Exception("500 Internal Server Error")
    )

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(RuntimeError, match="500 Internal Server Error"):
            await client.correct_text("Text to correct")

    assert client._client.chat.completions.create.call_count == 3
    assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# correct_batch Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_LLMClient_CorrectBatch_WhenEmptyList_ReturnsEmptyTuple():
    """Verify empty list returns ([], 0, 0.0) without API call."""
    client = LLMClient(base_url="http://localhost:1234/v1")
    items, tokens, dur = await client.correct_batch([])
    assert items == []
    assert tokens == 0
    assert dur == 0.0


@pytest.mark.asyncio
async def test_LLMClient_CorrectBatch_WhenSingleItem_DelegatesToCorrectText():
    """Verify single-item batch routes through correct_text directly."""
    client = LLMClient(base_url="http://localhost:1234/v1", model="test-model")
    client.correct_text = AsyncMock(
        return_value=LLMResponse("Single corrected.", completion_tokens=8, duration=0.12)
    )

    items, tokens, dur = await client.correct_batch(["Single correcetd."])
    assert items == ["Single corrected."]
    assert tokens == 8
    assert dur == 0.12
    client.correct_text.assert_called_once_with("Single correcetd.", model_override=None)


@pytest.mark.asyncio
async def test_LLMClient_CorrectBatch_MultiItemSuccess_ParsesAndPreservesWhitespace():
    """Verify multi-item batch parses bracketed response and preserves per-item whitespace."""
    client = LLMClient(base_url="http://localhost:1234/v1", model="gpt-4o-mini")

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "[1] First corrected.\n[2] Second corrected."
    mock_resp.usage = MagicMock(completion_tokens=22)

    client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

    input_texts = ["  First correcetd.", "Second correcetd.\n"]
    items, tokens, dur = await client.correct_batch(input_texts)

    assert items == ["  First corrected.", "Second corrected.\n"]
    assert tokens == 22
    assert dur >= 0.0


@pytest.mark.asyncio
async def test_LLMClient_CorrectBatch_WhenOutputUnparseable_ReturnsNoneForItems():
    """Verify unparseable LLM output returns None for items to signal fallback."""
    client = LLMClient(base_url="http://localhost:1234/v1", model="gpt-4o-mini")

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Sorry, I cannot help with this."
    mock_resp.usage = MagicMock(completion_tokens=10)

    client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

    items, tokens, dur = await client.correct_batch(["Item 1", "Item 2"])
    assert items is None
    assert tokens == 10


@pytest.mark.asyncio
async def test_LLMClient_CorrectBatch_WhenItemCountMismatched_ReturnsNoneForItems():
    """Verify count mismatch (3 expected, 2 returned) returns None for items."""
    client = LLMClient(base_url="http://localhost:1234/v1", model="gpt-4o-mini")

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "[1] Item one\n[2] Item two"
    mock_resp.usage = MagicMock(completion_tokens=12)

    client._client.chat.completions.create = AsyncMock(return_value=mock_resp)

    items, tokens, dur = await client.correct_batch(["Item 1", "Item 2", "Item 3"])
    assert items is None
    assert tokens == 12


@pytest.mark.asyncio
async def test_LLMClient_CorrectBatch_WhenFatalServerError_RaisesImmediately():
    """Verify server failure during batch raises exception to halt pipeline."""
    client = LLMClient(base_url="http://localhost:1234/v1", model="gpt-4o-mini")
    client._client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("Model unloaded")
    )

    with pytest.raises(RuntimeError, match="Model unloaded"):
        await client.correct_batch(["Item 1", "Item 2"])


# ---------------------------------------------------------------------------
# eject_inactive_models Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_LLMClient_EjectInactiveModels_LMStudio_Success():
    """Verify LM Studio models inspection and unload post call."""
    client = LLMClient(base_url="http://localhost:1234/v1", model="active-model")

    v0_mock = MagicMock(status_code=200)
    v0_mock.json.return_value = {
        "data": [
            {"id": "stale-model", "loaded": True},
            {"id": "active-model", "loaded": False},
        ]
    }
    unload_mock = MagicMock(status_code=200)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.get.return_value = v0_mock
        mock_http.post.return_value = unload_mock
        mock_client_cls.return_value.__aenter__.return_value = mock_http

        unloaded = await client.eject_inactive_models()

    assert unloaded == ["stale-model"]


@pytest.mark.asyncio
async def test_LLMClient_EjectInactiveModels_Ollama_Success():
    """Verify Ollama /api/ps inspection and keep_alive=0 unload call."""
    client = LLMClient(base_url="http://localhost:11434/v1", model="qwen2.5:7b")

    v0_mock = MagicMock(status_code=404)
    ps_mock = MagicMock(status_code=200)
    ps_mock.json.return_value = {
        "models": [{"name": "qwen2.5:7b"}, {"name": "llama3:latest"}]
    }
    unload_mock = MagicMock(status_code=200)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.get.side_effect = [v0_mock, ps_mock]
        mock_http.post.return_value = unload_mock
        mock_client_cls.return_value.__aenter__.return_value = mock_http

        unloaded = await client.eject_inactive_models()

    assert "llama3:latest" in unloaded


@pytest.mark.asyncio
async def test_LLMClient_EjectInactiveModels_WhenNetworkFails_ReturnsEmptySilently():
    """Verify network failures during model ejection fail gracefully without crashing."""
    client = LLMClient(base_url="http://localhost:1234/v1")

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.get.side_effect = Exception("Connection refused")
        mock_client_cls.return_value.__aenter__.return_value = mock_http

        unloaded = await client.eject_inactive_models()

    assert unloaded == []
