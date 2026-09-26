"""Run formatting preservation and sequence-matching diff engine for python-docx.

Ensures that inline formatting (bold, italic, underline, fonts, colors)
is preserved even when text is corrected by the LLM.
"""

from dataclasses import dataclass
import difflib
from typing import Any, List, Optional, Tuple
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
    highlight_color: Optional[Any] = None
    style_name: Optional[str] = None


def extract_run_style(run) -> RunStyle:
    """Extract styling attributes from a python-docx Run object."""
    color_str = None
    try:
        if run.font.color and run.font.color.rgb:
            color_str = str(run.font.color.rgb)
    except Exception:
        pass

    highlight = None
    try:
        highlight = run.font.highlight_color
    except Exception:
        pass

    style_name = None
    try:
        if run.style and run.style.name:
            style_name = run.style.name
    except Exception:
        pass

    font_name = None
    try:
        font_name = run.font.name
    except Exception:
        pass

    font_size = None
    try:
        font_size = run.font.size
    except Exception:
        pass

    return RunStyle(
        bold=run.bold,
        italic=run.italic,
        underline=run.underline,
        font_name=font_name,
        font_size=font_size,
        color_rgb=color_str,
        highlight_color=highlight,
        style_name=style_name,
    )


def apply_run_style(run, style: RunStyle) -> None:
    """Apply a RunStyle back onto a python-docx Run object."""
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
        except Exception:
            pass
    if style.highlight_color is not None:
        try:
            run.font.highlight_color = style.highlight_color
        except Exception:
            pass
    if style.style_name is not None:
        try:
            run.style = style.style_name
        except Exception:
            pass


def align_and_reconstruct_runs(
    original_runs_data: List[Tuple[str, RunStyle]],
    corrected_text: str,
) -> List[Tuple[str, RunStyle]]:
    """Map corrections to original runs using difflib sequence matching.

    Returns a list of (text_chunk, RunStyle) to be recreated in the paragraph.
    """
    original_text = "".join(text for text, _ in original_runs_data)

    # If text is unchanged or corrected text is identical, return original structure
    if original_text == corrected_text:
        return original_runs_data

    # If there were no runs, or original was empty
    if not original_runs_data or not original_text:
        default_style = original_runs_data[0][1] if original_runs_data else RunStyle()
        return [(corrected_text, default_style)]

    # If all runs had the exact same style, we can just return one run with that style
    first_style = original_runs_data[0][1]
    all_same_style = all(style == first_style for _, style in original_runs_data)
    if all_same_style:
        return [(corrected_text, first_style)]

    # Map each character in original_text to its RunStyle
    char_styles: List[RunStyle] = []
    for text, style in original_runs_data:
        char_styles.extend([style] * len(text))

    # Use SequenceMatcher to find aligned blocks
    matcher = difflib.SequenceMatcher(None, original_text, corrected_text)
    corrected_char_styles: List[RunStyle] = [RunStyle()] * len(corrected_text)

    for tag, alo, ahi, blo, bhi in matcher.get_opcodes():
        if tag == "equal":
            for i in range(bhi - blo):
                corrected_char_styles[blo + i] = char_styles[alo + i]
        elif tag == "replace":
            # Map replacement characters to the replaced original span
            orig_len = max(ahi - alo, 1)
            repl_len = bhi - blo
            for i in range(repl_len):
                orig_offset = min(int((i / repl_len) * orig_len), orig_len - 1)
                corrected_char_styles[blo + i] = char_styles[alo + orig_offset]
        elif tag == "insert":
            # Inherit style from preceding character, or following if at start
            if alo > 0 and alo - 1 < len(char_styles):
                inherited_style = char_styles[alo - 1]
            elif alo < len(char_styles):
                inherited_style = char_styles[alo]
            else:
                inherited_style = char_styles[-1] if char_styles else RunStyle()

            for i in range(bhi - blo):
                corrected_char_styles[blo + i] = inherited_style
        elif tag == "delete":
            # Nothing to add for deleted characters
            pass

    # Group consecutive characters with identical RunStyle into chunks
    chunks: List[Tuple[str, RunStyle]] = []
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


def update_paragraph_with_corrected_text(paragraph, corrected_text: str) -> bool:
    """Update a Word paragraph with corrected text, preserving run formatting.

    Returns True if paragraph was modified, False otherwise.
    """
    if not paragraph.runs:
        if paragraph.text != corrected_text:
            paragraph.text = corrected_text
            return True
        return False

    original_text = "".join(r.text for r in paragraph.runs)
    if original_text == corrected_text:
        return False

    original_runs_data = [(r.text, extract_run_style(r)) for r in paragraph.runs]
    new_chunks = align_and_reconstruct_runs(original_runs_data, corrected_text)

    # Clear existing runs without resetting paragraph properties
    paragraph.text = ""

    # Re-add runs with aligned styling
    for chunk_text, style in new_chunks:
        run = paragraph.add_run(chunk_text)
        apply_run_style(run, style)

    return True
