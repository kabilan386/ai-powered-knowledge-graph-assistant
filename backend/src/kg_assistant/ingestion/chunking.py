from uuid import NAMESPACE_URL, uuid5

from kg_assistant.core.exceptions import IngestionError
from kg_assistant.models.documents import Chunk, ExtractedPage


class ChunkingService:
    """Fixed character windows, with overlap within each page and global chunk indices."""

    def __init__(self, chunk_size: int, chunk_overlap: int, max_chunks: int) -> None:
        if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size or max_chunks <= 0:
            raise ValueError("Require chunk_size > overlap >= 0 and max_chunks > 0")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_chunks = max_chunks

    def chunk(self, pages: list[ExtractedPage], document_id: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        for page in pages:
            if not page.text.strip():
                continue
            start = 0
            while start < len(page.text):
                end = min(start + self.chunk_size, len(page.text))
                text = page.text[start:end]
                if text.strip():
                    if len(chunks) >= self.max_chunks:
                        raise IngestionError(
                            "chunk_limit", "Document exceeds the chunk limit.", 413
                        )
                    index = len(chunks)
                    chunks.append(
                        Chunk(
                            id=str(uuid5(NAMESPACE_URL, f"{document_id}:{index}")),
                            document_id=document_id,
                            text=text,
                            chunk_index=index,
                            page_number=page.page_number,
                        )
                    )
                if end == len(page.text):
                    break
                start = end - self.chunk_overlap
        return chunks
