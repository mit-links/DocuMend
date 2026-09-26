"""Extended unit tests for DocuMend's run aligner engine.

Tests preservation of all RunStyle attributes: font name, font size,
RGB colors, highlight color, underline, bold, italic, subscript, superscript,
strike, and difflib sequence matching across word insertions and deletions.
"""

import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt, RGBColor

from app.core.run_aligner import (
    RunStyle,
    align_and_reconstruct_runs,
    apply_run_style,
    extract_run_style,
    update_paragraph_with_corrected_text,
)


def test_RunAligner_ExtractAndApplyRunStyle_AllAttributesPreserved():
    """Verify extract_run_style and apply_run_style preserve all formatting properties."""
    doc = docx.Document()
    p = doc.add_paragraph()
    r = p.add_run("Styled run")
    r.bold = True
    r.italic = True
    r.underline = True
    r.font.name = "Arial"
    r.font.size = Pt(14)
    r.font.color.rgb = RGBColor(255, 0, 0)
    r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    r.font.subscript = True
    r.font.strike = True

    style = extract_run_style(r)
    assert style.bold is True
    assert style.italic is True
    assert style.underline is True
    assert style.font_name == "Arial"
    assert style.font_size == Pt(14)
    assert style.color_rgb == "FF0000"
    assert style.highlight_color == WD_COLOR_INDEX.YELLOW
    assert style.subscript is True
    assert style.strike is True

    # Apply onto a fresh run and verify
    p2 = doc.add_paragraph()
    r2 = p2.add_run("Target run")
    apply_run_style(r2, style)

    assert r2.bold is True
    assert r2.italic is True
    assert r2.underline is True
    assert r2.font.name == "Arial"
    assert r2.font.size == Pt(14)
    assert str(r2.font.color.rgb) == "FF0000"
    assert r2.font.highlight_color == WD_COLOR_INDEX.YELLOW
    assert r2.font.subscript is True
    assert r2.font.strike is True


def test_RunAligner_WordInsertions_InheritsAdjacentStyle():
    """Verify inserted words inherit style from the preceding adjacent run."""
    # Original: "The " (plain) + "cat" (bold) + " sat." (plain)
    # Corrected: "The big fat cat sat." -> "big fat " should be plain, "cat" bold
    runs_data = [
        ("The ", RunStyle(bold=False)),
        ("cat", RunStyle(bold=True)),
        (" sat.", RunStyle(bold=False)),
    ]
    corrected = "The big fat cat sat."
    result = align_and_reconstruct_runs(runs_data, corrected)

    reconstructed = "".join(t for t, _ in result)
    assert reconstructed == corrected

    # "cat" must remain bold
    bold_chunks = [t for t, s in result if s.bold is True]
    assert "".join(bold_chunks).strip() == "cat"


def test_RunAligner_WordDeletions_PreservesRemainingRuns():
    """Verify deleting words preserves styles of unaffected spans."""
    # Original: "A " (plain) + "very very" (italic) + " good result." (plain)
    # Corrected: "A very good result."
    runs_data = [
        ("A ", RunStyle(italic=False)),
        ("very very", RunStyle(italic=True)),
        (" good result.", RunStyle(italic=False)),
    ]
    corrected = "A very good result."
    result = align_and_reconstruct_runs(runs_data, corrected)

    reconstructed = "".join(t for t, _ in result)
    assert reconstructed == corrected

    italic_chunks = [t for t, s in result if s.italic is True]
    assert "".join(italic_chunks).strip() == "very"


def test_RunAligner_IdenticalText_ReturnsFalseWithoutModifyingParagraph():
    """Verify update_paragraph returns False if text is identical."""
    doc = docx.Document()
    p = doc.add_paragraph()
    p.add_run("Already perfect text.")

    modified = update_paragraph_with_corrected_text(p, "Already perfect text.")
    assert modified is False


def test_RunAligner_ParagraphWithoutRuns_SetsTextDirectly():
    """Verify paragraph with empty runs updates paragraph.text directly."""
    doc = docx.Document()
    p = doc.add_paragraph()
    assert len(p.runs) == 0

    modified = update_paragraph_with_corrected_text(p, "New text.")
    assert modified is True
    assert p.text == "New text."
