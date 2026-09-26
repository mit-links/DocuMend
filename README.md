# DocuMend

A lightweight, local, and privacy-preserving web application for automated grammar and spell checking of Microsoft Word (`.docx`) documents. Works with **any OpenAI-compatible LLM server** (e.g., LM Studio, Ollama, vLLM, LocalAI) while strictly preserving document styles, tables, and inline formatting (bold, italic, underline, fonts, and colors).

---

## Features

- **Runtime-Agnostic:** Compatible with any local or remote OpenAI-compatible API (`/v1`). Pre-configured for LM Studio (`:1234`) and Ollama (`:11434`).
- **Formatting Preservation:** Uses a token-level diff alignment engine (`difflib`) to preserve inline bold, italic, font styles, and colors even across edited text.
- **Tables & Multilingual:** Checks body paragraphs and table cells while maintaining table layout and preserving original language (e.g., English, German, French) without unwanted translation.
- **Real-time UX:** Server-Sent Events (SSE) stream live paragraph counters and snippet previews with automatic file download upon completion.
- **Help Pop-ups:** Contextual information buttons `(i)` on every input field explaining expected values and common defaults.

---

## Prerequisites

- **Python:** 3.10 or higher
- **LLM Server:** Any running OpenAI-compatible server (e.g. [LM Studio](https://lmstudio.ai/) running on port 1234, or [Ollama](https://ollama.ai/) on port 11434).

---

## Quickstart Setup

### Windows (PowerShell / Command Prompt)

```powershell
# 1. Clone repository
git clone https://github.com/mit-links/DocuMend.git
cd DocuMend

# 2. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the application (default: port 8000)
python -m app.main

# Or specify a custom port
python -m app.main --port 8080
```

### Linux / macOS (Bash)

```bash
# 1. Clone repository
git clone https://github.com/mit-links/DocuMend.git
cd DocuMend

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the application (default: port 8000)
python3 -m app.main

# Or specify a custom port
python3 -m app.main --port 8080
```

Open your browser at **[http://localhost:8000](http://localhost:8000)** (or your specified port).

---

## Server CLI Options

You can configure the server port, host, and reload mode via command-line arguments:

| Option | Flag | Default | Description |
|---|---|---|---|
| `--port` | `-p` | `8000` | Port to bind the web server to |
| `--host` | `-H` | `127.0.0.1` | Host address to bind to (`0.0.0.0` for LAN access) |
| `--reload` | | `False` | Enable auto-reload for development |

```bash
# Example: bind to port 8080
python -m app.main --port 8080

# Example: allow network access on port 9000
python -m app.main --host 0.0.0.0 --port 9000
```

---

## Usage

1. **Verify LLM Server:** Enter your server's base URL (defaults to `http://localhost:1234/v1`) and click **Connect & Fetch**.
2. **Select Model:** Choose an active loaded model from the dropdown.
3. **Upload File:** Drag and drop your `.docx` file into the upload zone.
4. **Correct:** Click **Correct Document**. Watch real-time progress as each paragraph and table cell is checked.
5. **Download:** The corrected document automatically downloads to your browser with all formatting preserved.

---

## Running Tests

To run the offline unit test suite:

```bash
pytest -v
```
