"""Local SentenceTransformer embedding provider adapter."""
from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """Real local embedding adapter backed by sentence-transformers."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        if not model_name or not model_name.strip():
            raise ValueError("EMBEDDING_MODEL must be set to a valid sentence-transformers model.")
        self.model_name = model_name.strip()
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device="cpu")
            dim = self._model.get_sentence_embedding_dimension()
            if dim is None or int(dim) <= 0:
                raise RuntimeError(f"Invalid embedding dimension returned for {self.model_name}: {dim}")
            self.dimensions = int(dim)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize local SentenceTransformer model '{self.model_name}': {exc}"
            ) from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = self._model.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return [[float(x) for x in row] for row in vectors]
        except Exception as exc:
            raise RuntimeError(f"Failed to embed {len(texts)} documents: {exc}") from exc

    def embed_query(self, question: str) -> list[float]:
        if not question or not question.strip():
            raise ValueError("Query text must not be empty.")
        try:
            vector = self._model.encode(
                question,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return [float(x) for x in vector]
        except Exception as exc:
            raise RuntimeError(f"Failed to embed query: {exc}") from exc
