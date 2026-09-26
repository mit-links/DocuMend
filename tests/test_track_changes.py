"""Unit tests for WordprocessingML Track Changes (Revisions) engine."""

import io
import docx
from docx.oxml.ns import qn
import pytest

from app.core.run_aligner import RunStyle, apply_run_style
from app.core.track_changes import RevisionManager, _TOKEN_PATTERN


class TestRevisionManager:
    """Test suite for RevisionManager and OpenXML revision generation."""

    def test_token_pattern_roundtrip(self) -> None:
        """Ensures that _TOKEN_PATTERN captures all characters without gaps."""
        sample = "The quick brown fox jumps over the lazy dog! (And 123 symbols: résumé, café)."
        tokens = _TOKEN_PATTERN.findall(sample)
        assert "".join(tokens) == sample

    def test_manager_id_generation(self) -> None:
        """Verifies that revision IDs are unique and monotonically incremented."""
        manager = RevisionManager(author="TestDocuMend")
        assert manager.author == "TestDocuMend"
        assert manager.revisions_count == 0

        id1 = manager.get_next_id()
        id2 = manager.get_next_id()
        assert id1 == "1"
        assert id2 == "2"
        assert manager.revisions_count == 2

    def test_enable_track_revisions(self) -> None:
        """Verifies that <w:trackRevisions/> is added to document settings."""
        doc = docx.Document()
        manager = RevisionManager()
        manager.enable_track_revisions(doc)

        settings_elm = doc.settings.element
        assert settings_elm.find(qn("w:trackRevisions")) is not None

        # Calling it a second time should not duplicate the element
        manager.enable_track_revisions(doc)
        matches = settings_elm.findall(qn("w:trackRevisions"))
        assert len(matches) == 1

    def test_unchanged_paragraph_returns_false(self) -> None:
        """Paragraph with identical text should not be modified."""
        doc = docx.Document()
        p = doc.add_paragraph("This text is completely unchanged.")
        manager = RevisionManager()

        modified = manager.apply_revisions_to_paragraph(p, "This text is completely unchanged.")
        assert modified is False
        assert len(p._p.xpath("./w:del")) == 0
        assert len(p._p.xpath("./w:ins")) == 0
        assert manager.revisions_count == 0

    def test_simple_replacement_creates_del_and_ins(self) -> None:
        """Replacing a misspelled word should emit <w:del> followed by <w:ins>."""
        doc = docx.Document()
        p = doc.add_paragraph("This is a bad error.")
        manager = RevisionManager(author="DocuMendAI", timestamp="2026-09-26T12:00:00Z")

        modified = manager.apply_revisions_to_paragraph(p, "This is a great error.")
        assert modified is True

        dels = p._p.xpath("./w:del")
        assert len(dels) == 1
        assert dels[0].get(qn("w:author")) == "DocuMendAI"
        assert dels[0].get(qn("w:date")) == "2026-09-26T12:00:00Z"

        del_text_nodes = p._p.xpath("./w:del//w:delText")
        assert len(del_text_nodes) == 1
        assert del_text_nodes[0].text == "bad"

        inss = p._p.xpath("./w:ins")
        assert len(inss) == 1
        assert inss[0].get(qn("w:author")) == "DocuMendAI"
        assert inss[0].get(qn("w:date")) == "2026-09-26T12:00:00Z"

        ins_text_nodes = p._p.xpath("./w:ins//w:t")
        assert len(ins_text_nodes) == 1
        assert ins_text_nodes[0].text == "great"

        # Equal text remains normal runs
        runs = p._p.xpath("./w:r")
        assert len(runs) >= 2  # "This is a " and " error."

    def test_pure_deletion(self) -> None:
        """Removing words should generate a <w:del> node without <w:ins>."""
        doc = docx.Document()
        p = doc.add_paragraph("Hello unnecessary world")
        manager = RevisionManager()

        modified = manager.apply_revisions_to_paragraph(p, "Hello world")
        assert modified is True

        dels = p._p.xpath("./w:del")
        assert len(dels) == 1
        del_texts = [node.text for node in p._p.xpath("./w:del//w:delText")]
        assert "unnecessary" in "".join(del_texts)

        inss = p._p.xpath("./w:ins")
        assert len(inss) == 0

    def test_pure_insertion(self) -> None:
        """Adding words should generate a <w:ins> node without <w:del>."""
        doc = docx.Document()
        p = doc.add_paragraph("Hello world")
        manager = RevisionManager()

        modified = manager.apply_revisions_to_paragraph(p, "Hello beautiful world")
        assert modified is True

        dels = p._p.xpath("./w:del")
        assert len(dels) == 0

        inss = p._p.xpath("./w:ins")
        assert len(inss) == 1
        ins_texts = [node.text for node in p._p.xpath("./w:ins//w:t")]
        assert "beautiful" in "".join(ins_texts)

    def test_formatting_preservation_in_revisions(self) -> None:
        """Formatting (bold/italic) should be preserved on runs inside revisions."""
        doc = docx.Document()
        p = doc.add_paragraph()
        r1 = p.add_run("Start ")
        r2 = p.add_run("bold_error")
        apply_run_style(r2, RunStyle(bold=True))
        r3 = p.add_run(" end")

        manager = RevisionManager()
        modified = manager.apply_revisions_to_paragraph(p, "Start bold_fixed end")
        assert modified is True

        dels = p._p.xpath("./w:del")
        assert len(dels) == 1
        # The deleted run inside <w:del> should retain bold formatting
        del_runs = p._p.xpath("./w:del/w:r")
        assert len(del_runs) == 1
        assert del_runs[0].find(qn("w:rPr")) is not None
        assert del_runs[0].find(qn("w:rPr")).find(qn("w:b")) is not None

        inss = p._p.xpath("./w:ins")
        assert len(inss) == 1
        ins_runs = p._p.xpath("./w:ins/w:r")
        assert len(ins_runs) == 1
        assert ins_runs[0].find(qn("w:rPr")) is not None
        assert ins_runs[0].find(qn("w:rPr")).find(qn("w:b")) is not None

    def test_empty_paragraph_without_runs(self) -> None:
        """Paragraph with no runs but text set directly should be handled safely."""
        doc = docx.Document()
        p = doc.add_paragraph()
        p.text = "Old direct text"
        # Clear runs list directly to simulate edge case
        p.runs.clear()

        manager = RevisionManager()
        modified = manager.apply_revisions_to_paragraph(p, "New direct text")
        assert modified is True

        assert len(p._p.xpath("./w:del")) == 1
        assert len(p._p.xpath("./w:ins")) == 1

    def test_docx_roundtrip_fidelity(self) -> None:
        """Documents containing revisions must save and reload with python-docx cleanly."""
        doc = docx.Document()
        manager = RevisionManager(author="DocuMend")
        manager.enable_track_revisions(doc)

        p1 = doc.add_paragraph("First sentence with mispelled word.")
        p2 = doc.add_paragraph("Second sentence with unnecessary words.")

        manager.apply_revisions_to_paragraph(p1, "First sentence with misspelled word.")
        manager.apply_revisions_to_paragraph(p2, "Second sentence.")

        # Save to in-memory bytes
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        # Reload with python-docx
        reloaded_doc = docx.Document(buffer)
        assert len(reloaded_doc.paragraphs) == 2

        # Verify revision elements exist in the reloaded XML
        p1_del = reloaded_doc.paragraphs[0]._p.xpath("./w:del")
        p1_ins = reloaded_doc.paragraphs[0]._p.xpath("./w:ins")
        assert len(p1_del) == 1
        assert len(p1_ins) == 1
