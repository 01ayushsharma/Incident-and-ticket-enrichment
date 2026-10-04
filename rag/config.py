"""Configuration for the RAG pipeline."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    document_path: str = str(REPO_ROOT / "rag" / "documents")
    vector_store_path: str = str(REPO_ROOT / ".index" / "chroma")
    vector_store_collection: str = "support_corpus"

    # all-MiniLM-L6-v2 exported to ONNX, served by chromadb. ~79MB, no torch.
    embedding_model: str = "all-MiniLM-L6-v2-onnx"

    # Chunking. Sized so a chunk is a coherent answer unit rather than a
    # sentence: roughly 200 tokens with enough overlap to survive a heading
    # boundary falling mid-argument.
    chunk_size: int = 800
    chunk_overlap: int = 120
    min_chunk_chars: int = 80

    # Retrieval.
    top_k: int = 5
    candidate_multiplier: int = 4
    dense_weight: float = 0.6
    # Measured separation on this corpus: on-topic queries score 0.53 to
    # 0.65, off-topic noise 0.05 to 0.26. 0.32 sits in the gap with margin
    # on both sides. Re-measure if the corpus or the embedding changes.
    min_score: float = 0.32

    @property
    def lexical_weight(self) -> float:
        return 1.0 - self.dense_weight


_settings: RagSettings | None = None


def get_settings() -> RagSettings:
    global _settings
    if _settings is None:
        _settings = RagSettings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
