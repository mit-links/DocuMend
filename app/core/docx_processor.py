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

    def chunk_items_into_batches(
        self,
        items: List[Tuple[str, docx.text.paragraph.Paragraph]],
        max_batch_size: int = 6,
        max_batch_words: int = 250,
    ) -> List[List[Tuple[str, docx.text.paragraph.Paragraph]]]:
        """Group consecutive processable items into small batches by count and word limit."""
        batches = []
        current_batch = []
        current_words = 0

        for item in items:
            item_type, p = item
            words = len(p.text.split())
            if current_batch and (
                len(current_batch) >= max_batch_size
                or (current_words + words > max_batch_words and current_words > 0)
            ):
                batches.append(current_batch)
                current_batch = []
                current_words = 0

            current_batch.append(item)
            current_words += words

        if current_batch:
            batches.append(current_batch)

        return batches

    async def process_document(
        self,
        docx_bytes: bytes,
        model_override: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str, bool], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
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

        batches = self.chunk_items_into_batches(processable, max_batch_size=6, max_batch_words=250)
        logger.info(f"Grouped {total_count} elements into {len(batches)} batch(es) for processing.")

        processed_count = 0
        total_completion_tokens = 0
        total_gen_time = 0.0

        async def process_single_paragraph(item_type: str, p: docx.text.paragraph.Paragraph):
            nonlocal processed_count, total_completion_tokens, total_gen_time
            if cancel_check and cancel_check():
                return

            original_text = p.text
            snippet = (original_text[:60] + "...") if len(original_text) > 60 else original_text

            async with self.semaphore:
                if cancel_check and cancel_check():
                    return

                call_start = time.time()
                try:
                    res = await self.llm_client.correct_text(original_text, model_override=model_override)
                    if cancel_check and cancel_check():
                        return

                    corrected_text = str(res)
                    tokens = getattr(res, "completion_tokens", None)
                    dur = getattr(res, "duration", time.time() - call_start)

                    if tokens is not None:
                        total_completion_tokens += tokens
                    total_gen_time += dur

                    update_paragraph_with_corrected_text(p, corrected_text)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if cancel_check and cancel_check():
                        return
                    logger.error(f"Error processing item snippet '{snippet}': {e}")
                finally:
                    if not (cancel_check and cancel_check()):
                        processed_count += 1
                        if progress_callback:
                            progress_callback(
                                processed_count,
                                total_count,
                                snippet,
                                processed_count >= total_count,
                            )

        async def process_batch(batch: List[Tuple[str, docx.text.paragraph.Paragraph]]):
            nonlocal processed_count, total_completion_tokens, total_gen_time
            if cancel_check and cancel_check():
                return

            if len(batch) == 1:
                item_type, p = batch[0]
                await process_single_paragraph(item_type, p)
                return

            texts = [p.text for _, p in batch]
            first_snippet = (texts[0][:50] + "...") if len(texts[0]) > 50 else texts[0]
            batch_desc = f"batch of {len(batch)} items: '{first_snippet}'"

            async with self.semaphore:
                if cancel_check and cancel_check():
                    return

                call_start = time.time()
                corrected_texts = None
                tokens = None
                dur = 0.0

                try:
                    corrected_texts, tokens, dur = await self.llm_client.correct_batch(
                        texts, model_override=model_override
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"Batch correction failed for {batch_desc}: {e}. Falling back to single items.")

                if tokens is not None:
                    total_completion_tokens += tokens
                total_gen_time += dur

                if cancel_check and cancel_check():
                    return

                if corrected_texts is not None and len(corrected_texts) == len(batch):
                    for (_, p), corr in zip(batch, corrected_texts):
                        update_paragraph_with_corrected_text(p, corr)
                        processed_count += 1
                        if progress_callback:
                            snippet = (p.text[:60] + "...") if len(p.text) > 60 else p.text
                            progress_callback(
                                processed_count,
                                total_count,
                                snippet,
                                processed_count >= total_count,
                            )
                else:
                    logger.info(f"Falling back to individual item processing for {batch_desc}")
                    for item_type, p in batch:
                        if cancel_check and cancel_check():
                            return
                        await process_single_paragraph(item_type, p)

        # Process batches concurrently within semaphore bounds
        tasks = [process_batch(b) for b in batches]
        await asyncio.gather(*tasks)

        if cancel_check and cancel_check():
            raise asyncio.CancelledError("Document processing was cancelled.")

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
