"""Sanitization utilities for cleaning LLM copyediting outputs."""

import re
from typing import Optional

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

# Precompiled regexes
RE_THINK = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
RE_UNCLOSED_THINK = re.compile(r"^<think>.*?(?:\n|$)", flags=re.DOTALL | re.IGNORECASE)
RE_STRAY_THINK = re.compile(r"</think>", flags=re.IGNORECASE)
RE_CODE_BLOCK = re.compile(r"^```(?:[a-zA-Z0-9_\-]+)?\s*\n?(.*?)\n?```$", flags=re.DOTALL)
RE_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_xml_characters(text: str) -> str:
    """Removes ASCII control characters illegal in OpenXML 1.0 documents.

    Args:
        text: String containing potentially invalid XML control characters.

    Returns:
        Sanitized string containing only valid OpenXML characters.
    """
    if not text:
        return ""
    return RE_XML_ILLEGAL.sub("", text)


def strip_reasoning_tags(text: str) -> str:
    """Removes model reasoning tags such as <think>...</think>.

    Args:
        text: Raw output string from an LLM.

    Returns:
        String with all reasoning blocks removed.
    """
    if not text or "<think" not in text.lower():
        return text
    text = RE_THINK.sub("", text).strip()
    text = RE_UNCLOSED_THINK.sub("", text).strip()
    text = RE_STRAY_THINK.sub("", text).strip()
    return text


def strip_markdown_fence(text: str) -> str:
    """Strips wrapping markdown code blocks (e.g. ```text ... ```).

    Args:
        text: Text that may be wrapped in triple backtick fences.

    Returns:
        Text extracted from within code fence, or original text.
    """
    match = RE_CODE_BLOCK.search(text.strip())
    if match:
        return match.group(1).strip()
    return text.strip()


def preserve_whitespace(original: str, cleaned: str) -> str:
    """Reapplies leading and trailing whitespace from the original text to the cleaned text.

    Args:
        original: The original string before processing.
        cleaned: The processed string with corrections.

    Returns:
        Cleaned string enclosed in the original leading and trailing whitespace.
    """
    if not original:
        return cleaned
    leading_ws = original[: len(original) - len(original.lstrip())]
    trailing_ws = original[len(original.rstrip()) :]
    return f"{leading_ws}{cleaned}{trailing_ws}"


def sanitize_llm_output(raw_output: str, original_text: str = "") -> str:
    """Clean and sanitize LLM copyediting output.

    Removes reasoning tags (<think>), markdown formatting fences, conversational
    preambles, unwanted wrapping quotes, illegal XML control characters, and
    explanatory notes.

    Args:
        raw_output: Raw text output from LLM.
        original_text: Optional original source text to prevent removing legitimate quotes
            or text starting with conversational phrases.

    Returns:
        Sanitized string ready for insertion into document.
    """
    if not raw_output:
        return original_text

    text = clean_xml_characters(raw_output.strip())

    # 1. Remove reasoning / <think> tags first
    text = strip_reasoning_tags(text)

    # 2. Remove conversational notes / suffixes at the end
    for pattern in SUFFIX_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL).strip()

    # 3. Iteratively remove conversational preambles at the beginning
    # Verify the original text didn't start with the preamble before stripping it
    changed = True
    iterations = 0
    orig_stripped = original_text.strip() if original_text else ""
    while changed and iterations < 5:
        changed = False
        iterations += 1
        for pattern in PREAMBLE_PATTERNS:
            match_clean = re.match(pattern, text, flags=re.IGNORECASE)
            if match_clean:
                if orig_stripped and re.match(pattern, orig_stripped, flags=re.IGNORECASE):
                    # Original text legitimately started with this phrase; keep it
                    continue
                text = text[match_clean.end() :].strip()
                changed = True

    # 4. Remove Markdown code blocks AFTER preambles are gone
    text = strip_markdown_fence(text)

    # 5. Remove wrapping quotation marks if LLM wrapped the entire output
    # but original text wasn't wrapped in quotes
    if len(text) >= 2:
        if (text.startswith('"') and text.endswith('"')) or (
            text.startswith("'") and text.endswith("'")
        ):
            original_has_quotes = bool(
                orig_stripped
                and (
                    (orig_stripped.startswith('"') and orig_stripped.endswith('"'))
                    or (orig_stripped.startswith("'") and orig_stripped.endswith("'"))
                )
            )
            if not original_has_quotes:
                text = text[1:-1].strip()

    # 6. Sanity check: if output is unexpectedly empty or vanished, fallback to original
    if not text.strip() and orig_stripped:
        return original_text

    return text


def parse_batched_output(raw_output: str, expected_count: int) -> Optional[list[str]]:
    """Parse a batched copyediting response with numbered items: [1] ... [2] ...

    Args:
        raw_output: Raw multi-item response from LLM.
        expected_count: Number of expected items in batch.

    Returns:
        List of extracted item strings if all items 1..expected_count are
        present in sequence, or None if the output could not be cleanly partitioned.
    """
    if not raw_output or expected_count <= 0:
        return None

    text = clean_xml_characters(raw_output.strip())
    text = strip_reasoning_tags(text)
    text = strip_markdown_fence(text)

    # Find all item markers matching ^\s*\[(\d+)\]
    pattern = re.compile(r"^\s*\[(\d+)\]\s*(.*)$", re.MULTILINE)
    matches = list(pattern.finditer(text))

    # Also handle patterns without brackets if the model outputs '1. ' or '1) '
    if len(matches) != expected_count:
        alt_pattern = re.compile(r"^\s*(?:\[|\b)(\d+)(?:\]|\.|\))\s*(.*)$", re.MULTILINE)
        alt_matches = list(alt_pattern.finditer(text))
        if len(alt_matches) == expected_count:
            matches = alt_matches
        else:
            return None

    results = []
    for i, match in enumerate(matches):
        idx = int(match.group(1))
        # Ensure sequential 1-based indexing: 1, 2, 3...
        if idx != i + 1:
            return None

        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        item_text = (match.group(2) + "\n" + text[start_pos:end_pos]).strip()
        # Clean any trailing notes from the final item
        if i == len(matches) - 1:
            for s_pat in SUFFIX_PATTERNS:
                item_text = re.sub(s_pat, "", item_text, flags=re.IGNORECASE | re.DOTALL).strip()
        results.append(item_text)

    return results if len(results) == expected_count else None
