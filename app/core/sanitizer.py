"""Sanitization utilities for cleaning LLM copyediting outputs."""
import re


# Common conversational prefixes returned by chat models
PREAMBLE_PATTERNS = [
    r"^(?:sure(?:thing)?|certainly|of\s+course)[,!.]?\s*",
    r"^(?:here(?:'s|\s+is)\s+(?:the\s+)?(?:corrected\s+)?(?:text|version|paragraph|sentence|output):?\s*)",
    r"^(?:(?:the\s+)?corrected\s+(?:text|version|sentence|paragraph):?\s*)",
    r"^(?:below\s+is\s+the\s+corrected\s+(?:text|version):?\s*)",
    r"^(?:the\s+corrected\s+(?:text|sentence|paragraph)\s+is:?\s*)",
]

# Common conversational suffixes/notes returned by models
SUFFIX_PATTERNS = [
    r"(?:\n+Note:.*)$",
    r"(?:\n+Explanation:.*)$",
    r"(?:\n+Changes made:.*)$",
    r"(?:\n+\(No (?:errors|changes) (?:found|detected)\.?\))$",
]


def sanitize_llm_output(raw_output: str, original_text: str = "") -> str:
    """Clean and sanitize LLM copyediting output.

    Removes markdown formatting fences, conversational preambles,
    unwanted wrapping quotes, and explanatory notes.
    """
    if not raw_output:
        return original_text

    text = raw_output.strip()

    # 1. Remove Markdown code blocks (e.g. ```text ... ``` or ``` ...)
    code_block_match = re.search(r"^```(?:[a-zA-Z0-9_\-]+)?\s*\n?(.*?)\n?```$", text, flags=re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # 2. Remove conversational notes / suffixes at the end
    for pattern in SUFFIX_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL).strip()

    # 3. Iteratively remove conversational preambles at the beginning
    changed = True
    iterations = 0
    while changed and iterations < 5:
        changed = False
        iterations += 1
        for pattern in PREAMBLE_PATTERNS:
            new_text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
            if new_text != text:
                text = new_text
                changed = True

    # 4. Remove wrapping quotation marks if the LLM wrapped the entire output
    # but original text wasn't wrapped in quotes
    if len(text) >= 2:
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            orig_stripped = original_text.strip()
            original_has_quotes = (
                (orig_stripped.startswith('"') and orig_stripped.endswith('"'))
                or (orig_stripped.startswith("'") and orig_stripped.endswith("'"))
            )
            if not original_has_quotes:
                text = text[1:-1].strip()

    # 5. Sanity check: if output is unexpectedly empty or vanished, fallback to original
    if not text.strip() and original_text.strip():
        return original_text

    return text
