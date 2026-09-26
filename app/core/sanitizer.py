"""Sanitization utilities for cleaning LLM copyediting outputs."""
import re
from typing import List, Optional


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


def parse_batched_output(raw_output: str, expected_count: int) -> Optional[list[str]]:
    """Parse a batched copyediting response with numbered items: [1] ... [2] ...

    Returns a list of extracted item strings if all items 1..expected_count are
    present in sequence, or None if the output could not be cleanly partitioned.
    """
    if not raw_output or expected_count <= 0:
        return None

    text = raw_output.strip()

    # 1. Remove wrapping code blocks if present
    code_block_match = re.search(r"^```(?:[a-zA-Z0-9_\-]+)?\s*\n?(.*?)\n?```$", text, flags=re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # 2. Find all item markers matching ^\s*\[(\d+)\]
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
