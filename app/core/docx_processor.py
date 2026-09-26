import asyncio
import io
import logging
import time
from typing import Callable, Dict, List, Optional, Tuple, Any
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
    ) -> Tuple[bytes, Dict[str, Any]]:
        """Process a DOCX document in-place and return (updated_bytes, stats_dict)."""
        start_time = time.time()
        input_stream = io.BytesIO(docx_bytes)
        doc = docx.Document(input_stream)

        processable = self.extract_processable_paragraphs(doc)
        total_count = len(processable)
        body_count = sum(1 for t, _ in processable if t == "paragraph")
        table_count = sum(1 for t, _ in processable if t == "table_cell")
        total_words = sum(len(p.text.split()) for _, p in processable)

        logger.info(
            f"Extracted {total_count} processable elements ({total_words} words) from DOCX: "
            f"{body_count} body paragraph(s), {table_count} table cell(s)."
        )

        if total_count == 0:
            logger.warning("No processable text elements found in document.")
            empty_stats = {
                "elapsed_seconds": round(time.time() - start_time, 2),
                "total_words": 0,
                "words_per_second": 0.0,
                "tokens_per_second": None,
                "total_completion_tokens": None,
                "total_items": 0,
            }
            if progress_callback:
                progress_callback(0, 0, "No text found to process", True)
            return docx_bytes, empty_stats

        processed_count = 0
        total_completion_tokens = 0
        total_gen_time = 0.0

        async def process_single_item(item_type: str, p: docx.text.paragraph.Paragraph):
            nonlocal processed_count, total_completion_tokens, total_gen_time
            original_text = p.text
            snippet = (original_text[:60] + "...") if len(original_text) > 60 else original_text

            async with self.semaphore:
                call_start = time.time()
                try:
                    res = await self.llm_client.correct_text(original_text, model_override=model_override)
                    corrected_text = str(res)
                    tokens = getattr(res, "completion_tokens", None)
                    dur = getattr(res, "duration", time.time() - call_start)

                    if tokens is not None:
                        total_completion_tokens += tokens
                    total_gen_time += dur

                    update_paragraph_with_corrected_text(p, corrected_text)
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

        elapsed_total = time.time() - start_time
        words_per_sec = round(total_words / elapsed_total, 1) if elapsed_total > 0 else 0.0

        tokens_per_sec = None
        if total_completion_tokens > 0 and total_gen_time > 0:
            tokens_per_sec = round(total_completion_tokens / total_gen_time, 1)

        stats = {
            "elapsed_seconds": round(elapsed_total, 2),
            "total_words": total_words,
            "words_per_second": words_per_sec,
            "tokens_per_second": tokens_per_sec,
            "total_completion_tokens": total_completion_tokens if total_completion_tokens > 0 else None,
            "total_items": total_count,
        }

        logger.info(
            f"Document processing completed: {total_words} words checked in {elapsed_total:.2f}s "
            f"({words_per_sec} words/s"
            + (f", {tokens_per_sec} tok/s" if tokens_per_sec is not None else "")
            + ")."
        )

        # Save reconstructed document to memory buffer
        output_stream = io.BytesIO()
        doc.save(output_stream)
        output_stream.seek(0)
        return output_stream.getvalue(), stats
