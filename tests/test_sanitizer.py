from app.core.sanitizer import sanitize_llm_output


def test_sanitize_clean_text():
    assert sanitize_llm_output("Hello world.", "Hello wrld.") == "Hello world."


def test_sanitize_markdown_fence():
    raw = "```markdown\nThis is corrected text.\n```"
    assert sanitize_llm_output(raw, "This is text.") == "This is corrected text."


def test_sanitize_code_fence():
    raw = "```\nThis is corrected text.\n```"
    assert sanitize_llm_output(raw, "This is text.") == "This is corrected text."


def test_sanitize_preambles():
    raw = "Here is the corrected text: This is the result."
    assert sanitize_llm_output(raw) == "This is the result."

    raw2 = "Sure! Here is the corrected text:\nThis is the result."
    assert sanitize_llm_output(raw2) == "This is the result."

    raw3 = "Corrected version: Single sentence."
    assert sanitize_llm_output(raw3) == "Single sentence."


def test_sanitize_suffixes():
    raw = "This is corrected.\n\nNote: I fixed the grammar."
    assert sanitize_llm_output(raw) == "This is corrected."

    raw2 = "This is corrected.\n\nExplanation: Typos fixed."
    assert sanitize_llm_output(raw2) == "This is corrected."


def test_sanitize_wrapping_quotes():
    raw = '"This sentence has quotes."'
    orig = "This sentnce has quotes."
    assert sanitize_llm_output(raw, orig) == "This sentence has quotes."

    # If original had quotes, do not strip
    orig_with_quotes = '"This sentnce has quotes."'
    assert sanitize_llm_output(raw, orig_with_quotes) == '"This sentence has quotes."'


def test_sanitize_empty_fallback():
    assert sanitize_llm_output("", "Original text") == "Original text"
    assert sanitize_llm_output("   ", "Original text") == "Original text"
