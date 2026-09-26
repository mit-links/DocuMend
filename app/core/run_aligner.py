"""Run formatting preservation and sequence-matching diff engine for python-docx.

Ensures that inline formatting (bold, italic, underline, fonts, colors, sub/superscript)
is preserved even when text is modified by LLM corrections.
"""

from dataclasses import dataclass
import difflib
from typing import Any, Optional
import docx.text.paragraph
import docx.text.run
from docx.shared import RGBColor


@dataclass(frozen=True)
class RunStyle:
    """Represents inline formatting attributes of a Word Run."""

    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underline: Optional[bool] = None
    font_name: Optional[str] = None
    font_size: Optional[Any] = None
    color_rgb: Optional[str] = None
    theme_color: Optional[Any] = None
    highlight_color: Optional[Any] = None
    style_name: Optional[str] = None
    subscript: Optional[bool] = None
    superscript: Optional[bool] = None
    strike: Optional[bool] = None


def _safe_get(obj: Any, *attrs: str, default: Any = None) -> Any:
    """Safely retrieves nested attributes without raising exceptions.

    Args:
        obj: Root object to inspect.
        *attrs: Attribute sequence to traverse.
        default: Fallback value if any attribute is missing or raises AttributeError.

    Returns:
        The resolved attribute value, or default.
    """
    curr = obj
    for attr in attrs:
        try:
            curr = getattr(curr, attr, None)
            if curr is None:
                return default
        except (AttributeError, ValueError, TypeError):
            return default
    return curr


def extract_run_style(run: docx.text.run.Run) -> RunStyle:
    """Extract styling attributes from a python-docx Run object.

    Args:
        run: The Word Run element to extract formatting from.

    Returns:
        RunStyle snapshot containing font, weight, decorations, and colors.
    """
    rgb = _safe_get(run, "font", "color", "rgb")
    color_str = str(rgb) if rgb is not None else None
    theme_color = _safe_get(run, "font", "color", "theme_color")
    highlight = _safe_get(run, "font", "highlight_color")
    style_name = _safe_get(run, "style", "name")
    font_name = _safe_get(run, "font", "name")
    font_size = _safe_get(run, "font", "size")
    subscript = _safe_get(run, "font", "subscript")
    superscript = _safe_get(run, "font", "superscript")
    strike = _safe_get(run, "font", "strike")

    return RunStyle(
        bold=run.bold,
        italic=run.italic,
        underline=run.underline,
        font_name=font_name,
        font_size=font_size,
        color_rgb=color_str,
        theme_color=theme_color,
        highlight_color=highlight,
        style_name=style_name,
        subscript=subscript,
        superscript=superscript,
        strike=strike,
    )


def apply_run_style(run: docx.text.run.Run, style: RunStyle) -> None:
    """Apply a RunStyle back onto a python-docx Run object.

    Args:
        run: The target Word Run element to style.
        style: The RunStyle attributes to apply.
    """
    if style.bold is not None:
        run.bold = style.bold
    if style.italic is not None:
        run.italic = style.italic
    if style.underline is not None:
        run.underline = style.underline
    if style.font_name is not None:
        run.font.name = style.font_name
    if style.font_size is not None:
        run.font.size = style.font_size
    if style.color_rgb is not None:
        try:
            run.font.color.rgb = RGBColor.from_string(style.color_rgb)
        except (ValueError, AttributeError):
            pass
    if style.theme_color is not None:
        try:
            run.font.color.theme_color = style.theme_color
        except (ValueError, AttributeError):
            pass
    if style.highlight_color is not None:
        try:
            run.font.highlight_color = style.highlight_color
        except (ValueError, AttributeError):
            pass
    if style.style_name is not None:
        try:
            run.style = style.style_name
        except (ValueError, AttributeError, KeyError):
            pass
    if style.subscript is not None:
        run.font.subscript = style.subscript
    if style.superscript is not None:
        run.font.superscript = style.superscript
    if style.strike is not None:
        run.font.strike = style.strike


def align_and_reconstruct_runs(
    original_runs_data: list[tuple[str, RunStyle]],
    corrected_text: str,
) -> list[tuple[str, RunStyle]]:
    """Map corrections to original runs using difflib sequence matching.

    Args:
        original_runs_data: List of (run_text, RunStyle) tuples from original paragraph.
        corrected_text: Full corrected text string for the paragraph.

    Returns:
        List of (text_chunk, RunStyle) chunks to recreate in the paragraph.
    """
    original_text = "".join(text for text, _ in original_runs_data)

    # Fast path: text is unchanged
    if original_text == corrected_text:
        return original_runs_data

    # Edge cases: no runs or empty original text
    if not original_runs_data or not original_text:
        default_style = original_runs_data[0][1] if original_runs_data else RunStyle()
        return [(corrected_text, default_style)]

    # Fast path: all runs had identical style
    first_style = original_runs_data[0][1]
    if all(style == first_style for _, style in original_runs_data):
        return [(corrected_text, first_style)]

    # Map each character index in original_text to its corresponding RunStyle
    char_styles: list[RunStyle] = []
    for text, style in original_runs_data:
        char_styles.extend([style] * len(text))

    # Use difflib.SequenceMatcher to calculate optimal block alignments
    matcher = difflib.SequenceMatcher(None, original_text, corrected_text)
    corrected_char_styles: list[RunStyle] = [RunStyle()] * len(corrected_text)

    for tag, orig_start, orig_end, corr_start, corr_end in matcher.get_opcodes():
        if tag == "equal":
            for i in range(corr_end - corr_start):
                corrected_char_styles[corr_start + i] = char_styles[orig_start + i]
        elif tag == "replace":
            # Map replacement characters proportionally to the replaced original span
            orig_len = max(orig_end - orig_start, 1)
            repl_len = corr_end - corr_start
            for i in range(repl_len):
                orig_offset = min(int((i / repl_len) * orig_len), orig_len - 1)
                corrected_char_styles[corr_start + i] = char_styles[orig_start + orig_offset]
        elif tag == "insert":
            # Inherit style from preceding character; if inserted at index 0, take following
            if orig_start > 0 and orig_start - 1 < len(char_styles):
                inherited_style = char_styles[orig_start - 1]
            elif orig_start < len(char_styles):
                inherited_style = char_styles[orig_start]
            else:
                inherited_style = char_styles[-1] if char_styles else RunStyle()

            for i in range(corr_end - corr_start):
                corrected_char_styles[corr_start + i] = inherited_style
        elif tag == "delete":
            pass

    # Group consecutive characters sharing identical styling into cohesive run chunks
    chunks: list[tuple[str, RunStyle]] = []
    if not corrected_char_styles:
        return chunks

    current_style = corrected_char_styles[0]
    current_chars = [corrected_text[0]]

    for char, style in zip(corrected_text[1:], corrected_char_styles[1:]):
        if style == current_style:
            current_chars.append(char)
        else:
            chunks.append(("".join(current_chars), current_style))
            current_style = style
            current_chars = [char]

    if current_chars:
        chunks.append(("".join(current_chars), current_style))

    return chunks


def update_paragraph_with_corrected_text(
    paragraph: docx.text.paragraph.Paragraph,
    corrected_text: str,
) -> bool:
    """Update a Word paragraph with corrected text, preserving run formatting.

    Args:
        paragraph: The python-docx Paragraph element to update.
        corrected_text: The new sanitized text to apply.

    Returns:
        True if the paragraph was modified, False otherwise.
    """
    if not paragraph.runs:
        if paragraph.text != corrected_text:
            paragraph.text = corrected_text
            return True
        return False

    original_text = "".join(r.text for r in paragraph.runs)
    if original_text == corrected_text:
        return False

    # Fast path: single-run paragraph preserves all run and paragraph properties directly
    if len(paragraph.runs) == 1:
        paragraph.runs[0].text = corrected_text
        return True

    original_runs_data = [(r.text, extract_run_style(r)) for r in paragraph.runs]
    new_chunks = align_and_reconstruct_runs(original_runs_data, corrected_text)

    # Remove only w:r child elements without clearing non-run elements (hyperlinks, drawings)
    for r_elem in list(paragraph._p.xpath("./w:r")):
        paragraph._p.remove(r_elem)

    # Re-add runs with aligned styling
    for chunk_text, style in new_chunks:
        if chunk_text:
            run = paragraph.add_run(chunk_text)
            apply_run_style(run, style)

    return True
