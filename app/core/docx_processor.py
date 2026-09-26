"""DOCX document processor for DocuMend.

Extracts paragraphs and table cells, runs LLM spell/grammar correction
with concurrency throttling, and updates the document in-place.
"""

import asyncio
import io
import logging
from typing import Callable, List, Optional, Tuple
import docx

from app.core.llm_client import LLMClient
from app.core.run_aligner import update_paragraph_with_corrected_text

logger = logging.getLogger(__name__)


class DocxProcessor:
    """Handles parsing, batching, and updating of DOCX documents."""

    def __init__(self, llm_client: LLMClient, concurrency_limit: int = 2):
        self.llm_client = llm_client
        self.concurrency_limit = concurrency_limit
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    def extract_processable_paragraphs(self, doc: docx.Document) -> List[Tuple[str, docx.text.paragraph.Paragraph]]:
        """Extract all non-empty paragraphs from document body and tables.

        Returns a list of (element_type, paragraph_object).
        """
        items = []

        # 1. Body paragraphs
        for p in doc.paragraphs:
            if p.text and p.text.strip():
                items.append(("paragraph", p))

        # 2. Table cells
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        if p.text and p.text.strip():
                            items.append(("table_cell", p))

        return items

    async def process_document(
        self,
        docx_bytes: bytes,
        model_override: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str, bool], None]] = None,
    ) -> bytes:
        """Process a DOCX document in-place and return the updated bytes."""
        input_stream = io.BytesIO(docx_bytes)
        doc = docx.Document(input_stream)

        processable = self.extract_processable_paragraphs(doc)
        total_count = len(processable)
        body_count = sum(1 for t, _ in processable if t == "paragraph")
        table_count = sum(1 for t, _ in processable if t == "table_cell")
        logger.info(
            f"Extracted {total_count} processable elements from DOCX: "
            f"{body_count} body paragraph(s), {table_count} table cell(s)."
        )

        if total_count == 0:
            logger.warning("No processable text elements found in document.")
            if progress_callback:
                progress_callback(0, 0, "No text found to process", True)
            return docx_bytes

        processed_count = 0

        async def process_single_item(item_type: str, p: docx.text.paragraph.Paragraph):
            nonlocal processed_count
            original_text = p.text
            snippet = (original_text[:60] + "...") if len(original_text) > 60 else original_text

            async with self.semaphore:
                try:
                    corrected = await self.llm_client.correct_text(original_text, model_override=model_override)
                    update_paragraph_with_corrected_text(p, corrected)
                except Exception as e:
                    logger.error(f"Error processing item snippet '{snippet}': {e}")
                finally:
                    processed_count += 1
                    if progress_callback:
                        progress_callback(
                            processed_count,
                            total_count,
                            snippet,
                            processed_count >= total_count,
                        )

        # Process paragraphs concurrently within semaphore bounds
        tasks = [process_single_item(item_type, p) for item_type, p in processable]
        await asyncio.gather(*tasks)

        # Save reconstructed document to memory buffer
        output_stream = io.BytesIO()
        doc.save(output_stream)
        output_stream.seek(0)
        return output_stream.getvalue()
