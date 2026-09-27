"""WordprocessingML Track Changes (Revisions) engine for DOCX documents.

Generates standard OpenXML <w:ins> and <w:del> revision markup compatible with
Microsoft Word, LibreOffice Writer, and Google Docs.
"""

from datetime import datetime, timezone
import difflib
import logging
import re
import threading
from typing import Any, Optional
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import docx.text.paragraph
import docx.text.run

from app.core.run_aligner import (
    _TOKEN_PATTERN,
    RunStyle,
    apply_run_style,
    extract_run_style,
)

logger = logging.getLogger(__name__)


def _create_run_element(
    paragraph: docx.text.paragraph.Paragraph,
    text: str,
    style: RunStyle,
    is_del: bool = False,
) -> Any:
    """Creates a Word run (<w:r>) element with styling and text.

    Args:
        paragraph: Parent paragraph context for the Run wrapper.
        text: Text string to store in the run.
        style: Inline formatting attributes to apply.
        is_del: If True, uses <w:delText>; otherwise uses <w:t>.

    Returns:
        The generated CT_R OxmlElement.
    """
    r_elem = OxmlElement("w:r")
    run = docx.text.run.Run(r_elem, paragraph)
    apply_run_style(run, style)

    text_tag = "w:delText" if is_del else "w:t"
    t_elem = OxmlElement(text_tag)
    if text.startswith(" ") or text.endswith(" ") or "  " in text or "\t" in text or "\n" in text:
        t_elem.set(qn("xml:space"), "preserve")
    t_elem.text = text
    r_elem.append(t_elem)
    return r_elem


def _create_del_container(
    revision_id: str,
    author: str,
    date_str: str,
    runs: list[Any],
) -> Any:
    """Wraps runs into an OpenXML <w:del> revision element."""
    del_elem = OxmlElement("w:del")
    del_elem.set(qn("w:id"), revision_id)
    del_elem.set(qn("w:author"), author)
    del_elem.set(qn("w:date"), date_str)
    for r in runs:
        del_elem.append(r)
    return del_elem


def _create_ins_container(
    revision_id: str,
    author: str,
    date_str: str,
    runs: list[Any],
) -> Any:
    """Wraps runs into an OpenXML <w:ins> revision element."""
    ins_elem = OxmlElement("w:ins")
    ins_elem.set(qn("w:id"), revision_id)
    ins_elem.set(qn("w:author"), author)
    ins_elem.set(qn("w:date"), date_str)
    for r in runs:
        ins_elem.append(r)
    return ins_elem


def _slice_styled_spans(
    text: str,
    start_char: int,
    end_char: int,
    char_styles: list[RunStyle],
) -> list[tuple[str, RunStyle]]:
    """Partitions a character slice into chunks sharing identical RunStyles.

    Args:
        text: The full source string.
        start_char: Inclusive starting character index.
        end_char: Exclusive ending character index.
        char_styles: Character-by-character style mapping.

    Returns:
        List of (chunk_text, RunStyle) tuples.
    """
    if start_char >= end_char:
        return []

    chunks: list[tuple[str, RunStyle]] = []
    current_style = char_styles[start_char]
    current_chars = [text[start_char]]

    for idx in range(start_char + 1, end_char):
        style = char_styles[idx]
        if style == current_style:
            current_chars.append(text[idx])
        else:
            chunks.append(("".join(current_chars), current_style))
            current_style = style
            current_chars = [text[idx]]

    if current_chars:
        chunks.append(("".join(current_chars), current_style))

    return chunks


class RevisionManager:
    """Manages document-level revisions, unique IDs, and track-changes formatting."""

    def __init__(
        self,
        author: str = "DocuMend",
        timestamp: Optional[str] = None,
    ) -> None:
        """Initializes RevisionManager with author and ISO-8601 UTC timestamp.

        Args:
            author: Name of the author attributed to revisions.
            timestamp: Optional ISO timestamp string (defaults to current UTC time).
        """
        self.author = author
        self.timestamp = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._next_id = 1
        self._revisions_count = 0
        self._lock = threading.Lock()

    @property
    def revisions_count(self) -> int:
        """Returns the total number of revision elements generated."""
        with self._lock:
            return self._revisions_count

    def get_next_id(self) -> str:
        """Generates a monotonically increasing unique revision identifier."""
        with self._lock:
            rev_id = str(self._next_id)
            self._next_id += 1
            self._revisions_count += 1
            return rev_id

    def enable_track_revisions(self, doc: docx.Document) -> None:
        """Configures document settings to enable Track Changes in Word, LibreOffice, and Google Docs.

        Args:
            doc: The python-docx Document instance.
        """
        try:
            settings_elm = doc.settings.element
            if settings_elm.find(qn("w:trackRevisions")) is None:
                settings_elm.append(OxmlElement("w:trackRevisions"))
        except Exception as e:
            logger.warning(f"Failed to enable trackRevisions in document settings: {e}")

    def apply_revisions_to_paragraph(
        self,
        paragraph: docx.text.paragraph.Paragraph,
        corrected_text: str,
    ) -> bool:
        """Transforms a paragraph into tracked changes representing the corrections.

        Tokenizes original and corrected text into word/punctuation tokens, computes
        opcodes with SequenceMatcher, and inserts <w:ins> and <w:del> revision nodes
        while preserving original formatting.

        Args:
            paragraph: The python-docx Paragraph element to modify.
            corrected_text: The corrected text string proposed by LLM.

        Returns:
            True if revisions were applied, False if text was identical.
        """
        if not paragraph.runs:
            if paragraph.text != corrected_text:
                orig_text = paragraph.text
                paragraph.text = ""
                if orig_text:
                    del_r = _create_run_element(paragraph, orig_text, RunStyle(), is_del=True)
                    paragraph._p.append(
                        _create_del_container(
                            self.get_next_id(), self.author, self.timestamp, [del_r]
                        )
                    )
                if corrected_text:
                    ins_r = _create_run_element(paragraph, corrected_text, RunStyle(), is_del=False)
                    paragraph._p.append(
                        _create_ins_container(
                            self.get_next_id(), self.author, self.timestamp, [ins_r]
                        )
                    )
                return True
            return False

        original_text = "".join(r.text for r in paragraph.runs)
        if original_text == corrected_text:
            return False

        # Build character-to-RunStyle mapping from existing runs
        char_styles: list[RunStyle] = []
        for r in paragraph.runs:
            style = extract_run_style(r)
            char_styles.extend([style] * len(r.text))

        if not char_styles:
            char_styles = [RunStyle()] * len(original_text)

        orig_tokens = _TOKEN_PATTERN.findall(original_text)
        corr_tokens = _TOKEN_PATTERN.findall(corrected_text)

        # Calculate character boundary spans for each original token
        orig_spans: list[tuple[int, int]] = []
        curr_offset = 0
        for tok in orig_tokens:
            orig_spans.append((curr_offset, curr_offset + len(tok)))
            curr_offset += len(tok)

        matcher = difflib.SequenceMatcher(None, orig_tokens, corr_tokens)
        new_elements: list[Any] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                start_c = orig_spans[i1][0]
                end_c = orig_spans[i2 - 1][1]
                chunks = _slice_styled_spans(original_text, start_c, end_c, char_styles)
                for chunk_text, style in chunks:
                    if chunk_text:
                        new_elements.append(
                            _create_run_element(paragraph, chunk_text, style, is_del=False)
                        )

            elif tag == "delete":
                start_c = orig_spans[i1][0]
                end_c = orig_spans[i2 - 1][1]
                chunks = _slice_styled_spans(original_text, start_c, end_c, char_styles)
                del_runs = [
                    _create_run_element(paragraph, t, s, is_del=True)
                    for t, s in chunks
                    if t
                ]
                if del_runs:
                    new_elements.append(
                        _create_del_container(
                            self.get_next_id(), self.author, self.timestamp, del_runs
                        )
                    )

            elif tag == "insert":
                inserted_text = "".join(corr_tokens[j1:j2])
                if inserted_text:
                    if i1 > 0 and i1 - 1 < len(orig_spans):
                        ref_char = orig_spans[i1 - 1][1] - 1
                        inherited_style = (
                            char_styles[ref_char] if ref_char < len(char_styles) else RunStyle()
                        )
                    elif i1 < len(orig_spans):
                        ref_char = orig_spans[i1][0]
                        inherited_style = (
                            char_styles[ref_char] if ref_char < len(char_styles) else RunStyle()
                        )
                    else:
                        inherited_style = char_styles[-1] if char_styles else RunStyle()

                    ins_run = _create_run_element(
                        paragraph, inserted_text, inherited_style, is_del=False
                    )
                    new_elements.append(
                        _create_ins_container(
                            self.get_next_id(), self.author, self.timestamp, [ins_run]
                        )
                    )

            elif tag == "replace":
                # 1. Output deletion first
                start_c = orig_spans[i1][0]
                end_c = orig_spans[i2 - 1][1]
                chunks = _slice_styled_spans(original_text, start_c, end_c, char_styles)
                del_runs = [
                    _create_run_element(paragraph, t, s, is_del=True)
                    for t, s in chunks
                    if t
                ]
                if del_runs:
                    new_elements.append(
                        _create_del_container(
                            self.get_next_id(), self.author, self.timestamp, del_runs
                        )
                    )

                # 2. Output insertion next
                inserted_text = "".join(corr_tokens[j1:j2])
                if inserted_text:
                    if i1 < len(orig_spans):
                        ref_char = orig_spans[i1][0]
                        inherited_style = (
                            char_styles[ref_char] if ref_char < len(char_styles) else RunStyle()
                        )
                    elif i1 > 0 and i1 - 1 < len(orig_spans):
                        ref_char = orig_spans[i1 - 1][1] - 1
                        inherited_style = (
                            char_styles[ref_char] if ref_char < len(char_styles) else RunStyle()
                        )
                    else:
                        inherited_style = char_styles[-1] if char_styles else RunStyle()

                    ins_run = _create_run_element(
                        paragraph, inserted_text, inherited_style, is_del=False
                    )
                    new_elements.append(
                        _create_ins_container(
                            self.get_next_id(), self.author, self.timestamp, [ins_run]
                        )
                    )

        # Remove existing run and revision elements while preserving paragraph properties (pPr)
        for child in list(paragraph._p):
            if child.tag in (qn("w:r"), qn("w:ins"), qn("w:del")):
                paragraph._p.remove(child)

        # Append new runs and revision markup
        for elem in new_elements:
            paragraph._p.append(elem)

        return True
