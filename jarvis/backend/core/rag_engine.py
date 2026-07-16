from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from jarvis.backend.core.vector_store import VectorStoreInterface


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RAGConfig:
    """Configuration for RAG engine."""
    chunk_size: int = 512
    chunk_overlap: int = 100
    embed_batch_size: int = 32
    rerank_enabled: bool = False
    top_k: int = 5


@dataclass(slots=True, frozen=True)
class RAGResult:
    """A single RAG search result."""
    content: str
    source: str
    score: float
    metadata: dict[str, Any]


class DocumentChunker:
    """Chunks documents into embeddings-friendly pieces."""

    def __init__(self, chunk_size: int = 512, overlap: int = 100) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        """Split text into overlapping chunks with metadata."""
        chunks = []
        words = text.split()
        current_chunk = []
        current_size = 0

        for word in words:
            word_size = len(word.split())
            if current_size + word_size > self.chunk_size:
                if current_chunk:
                    chunk_text = " ".join(current_chunk)
                    chunks.append((chunk_text, metadata or {}))
                    current_chunk = current_chunk[-self.overlap // 4 :]
                    current_size = sum(len(w.split()) for w in current_chunk)

            current_chunk.append(word)
            current_size += word_size

        if current_chunk:
            chunks.append((" ".join(current_chunk), metadata or {}))

        return chunks


class RAGEngine:
    """Local RAG orchestration over vector store."""

    def __init__(
        self, vector_store: VectorStoreInterface, config: RAGConfig | None = None
    ) -> None:
        self.vector_store = vector_store
        self.config = config or RAGConfig()
        self.chunker = DocumentChunker(
            chunk_size=self.config.chunk_size, overlap=self.config.chunk_overlap
        )

    def ingest_text(
        self,
        text: str,
        source_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Ingest and chunk plain text, returning chunk count."""
        full_metadata = {"source": source_id, **(metadata or {})}
        chunks = self.chunker.chunk_text(text, full_metadata)
        count = 0
        for chunk_text, chunk_meta in chunks:
            result = self.vector_store.upsert_document(
                document_id=f"{source_id}_{count}",
                content=chunk_text,
                metadata=chunk_meta,
            )
            if result:
                count += 1
        logger.info(f"Ingested {count} chunks from {source_id}")
        return count

    def query(self, text: str, top_k: int | None = None, collection: str = "documents") -> list[RAGResult]:
        """Query the vector store for relevant documents."""
        k = top_k or self.config.top_k
        if not self.vector_store.enabled:
            return []

        results = self.vector_store.query(collection, text, limit=k)
        return [
            RAGResult(
                content=r.content,
                source=r.metadata.get("source", "unknown"),
                score=r.score or 0.0,
                metadata=r.metadata,
            )
            for r in results
        ]

    def delete_source(self, source_id: str, collection: str = "documents") -> None:
        """Delete all documents from a source."""
        try:
            self.vector_store.delete(collection, source_id)
            logger.info(f"Deleted documents from {source_id}")
        except Exception as exc:
            logger.error(f"Failed to delete {source_id}: {exc}")

    def format_for_context(self, results: list[RAGResult]) -> list[str]:
        """Format RAG results for inclusion in LM context."""
        formatted = []
        for result in results:
            source_info = f"[{result.source}]" if result.source else "[Unknown Source]"
            confidence = f"(confidence: {result.score:.2f})" if result.score > 0 else ""
            formatted.append(f"{source_info} {result.content} {confidence}")
        return formatted
