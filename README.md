# DocuMend

A lightweight, privacy-first web application for automated grammar and spell checking of Microsoft Word (`.docx`) documents. Works with **any OpenAI-compatible LLM runtime**—including local engines (LM Studio, Ollama, vLLM, LocalAI) and commercial cloud APIs (Google Gemini, OpenAI ChatGPT, Anthropic Claude).

DocuMend guarantees **strict formatting preservation**: inline bold, italic, underline, font families, font sizes, colors, subscripts, and superscripts are preserved across edits using sequence-matching character diffs.

---

## Key Features

- **Model & Provider Agnostic:** Works with any local or remote OpenAI-compatible endpoint (`/v1`), with built-in presets for **LM Studio**, **Ollama**, **Google Gemini**, **ChatGPT**, and **Claude**.
- **Dual Output Modes:** Choose between **Direct Edit** (`edit`, ready-to-use in-place replacements) and **Suggestions** (`suggest`, standard Word Track Changes `<w:ins>` / `<w:del>` for review in Microsoft Word, LibreOffice Writer, or Google Docs).
- **Formatting Preservation:** Keeps inline styles intact—including bold, italics, underlines, font families, sizes, colors, subscripts, and superscripts.
- **Full Document Coverage:** Accurately corrects body paragraphs, bullet lists, and tables without altering document layouts.
- **Multilingual Copyediting:** Focuses strictly on spelling, grammar, and punctuation while preserving the original language without translation.
- **Fast & Responsive:** Parallel processing and dynamic batching accelerate throughput, with automatic GPU memory management for local runtimes.
- **Privacy First:** When paired with a local LLM runtime, no document data is sent anywhere outside of the machine. Files are processed strictly in-memory with zero disk footprint, console logs omit text excerpts, and API keys are never written to disk.

---

## Architecture Overview

```
                      +-----------------------------------+
                      |      Web UI (Tailwind + SSE)     |
                      +-----------------+-----------------+
                                        | (HTTP / SSE)
                                        v
                      +-----------------------------------+
                      |      FastAPI Backend & Router     |
                      |          (app/api/routes)         |
                      +--------+------------------+-------+
                               |                  |
              +----------------v----+      +------v-----------------+
              |  Job & SSE Manager  |      |   DocxProcessor Engine  |
              | (app/api/job_mgr)   |      |  (app/core/docx_proc)   |
              +---------------------+      +------+-----------------+
                                                  |
                  +-------------------------------+-------------------------------+
                  |                               |                               |
                  v                               v                               v
    +---------------------------+   +---------------------------+   +---------------------------+
    |   Element Extraction &    |   |     RunStyle Aligner      |   |        LLM Client         |
    |      Batch Chunking       |   |    (app/core/run_align)   |   |   (app/core/llm_client)   |
    +---------------------------+   +---------------------------+   +-------------+-------------+
                                                                                  | (OpenAI /v1)
                                                                                  v
                                                            +-----------------------------------+
                                                            |  LM Studio / Ollama / Gemini /... |
                                                            +-----------------------------------+
```

---

## Provider Presets & Configuration

DocuMend includes built-in presets accessible directly from the UI header:

| Provider | Server Base URL | Default Port / Path | API Key Requirement |
|---|---|---|---|
| **LM Studio** *(Default)* | `http://localhost:1234/v1` | Port `1234` | Set to `not-needed` |
| **Ollama** | `http://localhost:11434/v1` | Port `11434` | Set to `not-needed` |
| **Google Gemini** | `https://generativelanguage.googleapis.com/v1beta/openai/` | HTTPS | Google AI Studio Key |
| **ChatGPT (OpenAI)** | `https://api.openai.com/v1` | HTTPS | OpenAI API Key (`sk-...`) |
| **Claude (Anthropic)** | `https://api.anthropic.com/v1` | HTTPS | Anthropic Console Key |

Local endpoints (LM Studio, Ollama) require no external internet connection—**no document data is sent anywhere outside of your machine**. Uploaded documents are buffered and edited in RAM (up to 100 MB) with zero temporary files written to disk, server logs do not output text excerpts, and cross-origin browser requests are blocked.

For cloud providers, requests are sent directly to the configured provider API; keys are held strictly in memory for the duration of the request and are never written to disk.

---

## Quickstart Setup

### Prerequisites
- **Python:** 3.10, 3.11, or 3.12
- **LLM Runtime:** [LM Studio](https://lmstudio.ai/), [Ollama](https://ollama.ai/), or a cloud API key.

### Installation

#### Windows (PowerShell)
```powershell
# 1. Clone repository
git clone https://github.com/mit-links/DocuMend.git
cd DocuMend

# 2. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the server (default: port 8000)
python -m app.main
```

#### Linux & macOS (Bash)
```bash
# 1. Clone repository
git clone https://github.com/mit-links/DocuMend.git
cd DocuMend

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the server (default: port 8000)
python3 -m app.main
```

Open your browser at **`http://localhost:8000`**.

---

## Configuration & Environment Variables

All settings can be configured via environment variables or a `.env` file using the `DOCUMEND_` prefix:

| Environment Variable | CLI Flag | Default | Description |
|---|---|---|---|
| `DOCUMEND_HOST` | `--host`, `-H` | `127.0.0.1` | Network interface to bind (`0.0.0.0` for LAN access) |
| `DOCUMEND_PORT` | `--port`, `-p` | `8000` | Port to bind the HTTP web server |
| `DOCUMEND_DEFAULT_BASE_URL` | — | `http://localhost:1234/v1` | Default LLM server address |
| `DOCUMEND_DEFAULT_API_KEY` | — | `not-needed` | Default API key |
| `DOCUMEND_DEFAULT_MODEL` | — | `""` *(Auto-detect)* | Default model ID |
| `DOCUMEND_CONCURRENCY_LIMIT`| — | `1` | Number of simultaneous LLM requests |
| `DOCUMEND_REQUEST_TIMEOUT` | — | `90.0` | Timeout per LLM call in seconds |
| `DOCUMEND_TEMPERATURE` | — | `0.0` | Sampling temperature (0.0 for deterministic edits) |
| `DOCUMEND_SPOOL_MAX_SIZE` | — | `104857600` (100 MB) | Max upload size buffered in RAM before disk spooling |

### CLI Options Example
```bash
# Run on port 8080 with auto-reload for development
python -m app.main --port 8080 --reload

# Allow access across local area network
python -m app.main --host 0.0.0.0 --port 9000
```

---

## Usage Guide

1. **Configure Connection:**
   - Click a preset (e.g., **LM Studio** or **Google Gemini**).
   - Enter your API Key if using a cloud model.
   - Click **Connect & Fetch** to automatically discover available models.
2. **Select Active Model:**
   - Choose your preferred model from the dropdown (e.g., `Qwen2.5-7B-Instruct`, `gemini-1.5-flash`).
3. **Upload Document:**
   - Drag & drop any `.docx` file into the upload dropzone.
4. **Set Concurrency:**
   - Keep default `1` for local GPUs, or increase to `2-8` for cloud endpoints or multi-GPU servers.
5. **Start Correction:**
   - Click **Correct Document**. Real-time progress and live snippets display as items are verified.
   - To interrupt, click **Stop** at any time.
6. **Download:**
   - Upon completion, your corrected document automatically downloads with all original formatting preserved.

---

## API Reference

The backend exposes a clean REST and Server-Sent Events API:

- `GET /api/models?base_url=...&api_key=...`: Query and filter available chat models from the server.
- `POST /api/models/eject`: Unload inactive models to free GPU VRAM.
- `POST /api/process`: Upload `.docx` file and start background correction job.
- `GET /api/jobs/{job_id}`: Get job status, processed items count, and performance stats.
- `GET /api/jobs/{job_id}/stream`: Real-time Server-Sent Events (SSE) progress stream.
- `POST /api/jobs/{job_id}/cancel`: Cancel an active job.
- `GET /api/jobs/{job_id}/download`: Download the corrected `.docx` document.

---

## Testing

DocuMend includes a comprehensive, hermetic unit test suite covering extraction, run alignment, batch parsing, SSE broadcasting, and error handling:

```bash
# Run full offline test suite
pytest -v
```

---

## License

Distributed under the MIT License. See `LICENSE` for details.
