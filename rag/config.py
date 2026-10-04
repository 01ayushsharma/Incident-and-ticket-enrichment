"""Configuration for the RAG pipeline."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env(*names: str) -> AliasChoices:
    """Accept any of ``names`` as the environment variable for a field.

    The settings here are read under two naming conventions that both
    appear in ``.env.example`` and ``docker-compose.yml``: the path-like
    ones are bare (``DOCUMENT_PATH``) while the tuning knobs are prefixed
    (``RAG_TOP_K``). A blanket ``env_prefix`` would break the first group
    and no prefix breaks the second, so each field names its own spellings.
    First match wins, in the order given.
    """
    return AliasChoices(*names)


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    document_path: str = Field(
        default=str(REPO_ROOT / "rag" / "documents"),
        validation_alias=_env("DOCUMENT_PATH", "RAG_DOCUMENT_PATH"),
    )
    vector_store_path: str = Field(
        default=str(REPO_ROOT / ".index" / "chroma"),
        validation_alias=_env("VECTOR_STORE_PATH", "RAG_VECTOR_STORE_PATH"),
    )
    vector_store_collection: str = Field(
        default="support_corpus",
        validation_alias=_env("VECTOR_STORE_COLLECTION", "RAG_VECTOR_STORE_COLLECTION"),
    )

    # all-MiniLM-L6-v2 exported to ONNX, served by chromadb. ~79MB, no torch.
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2-onnx",
        validation_alias=_env("EMBEDDING_MODEL", "RAG_EMBEDDING_MODEL"),
    )
    # Where chromadb unpacks the ONNX model. Set it to a mounted volume so a
    # container starts offline after the first download; left unset, chromadb
    # uses its own default cache location.
    embedding_cache_dir: str | None = Field(
        default=None,
        validation_alias=_env("EMBEDDING_CACHE_DIR", "RAG_EMBEDDING_CACHE_DIR"),
    )

    # Chunking. Sized so a chunk is a coherent answer unit rather than a
    # sentence: roughly 200 tokens with enough overlap to survive a heading
    # boundary falling mid-argument.
    chunk_size: int = Field(default=800, validation_alias=_env("RAG_CHUNK_SIZE", "CHUNK_SIZE"))
    chunk_overlap: int = Field(
        default=120, validation_alias=_env("RAG_CHUNK_OVERLAP", "CHUNK_OVERLAP")
    )
    min_chunk_chars: int = Field(
        default=80, validation_alias=_env("RAG_MIN_CHUNK_CHARS", "MIN_CHUNK_CHARS")
    )

    # Retrieval.
    top_k: int = Field(default=5, validation_alias=_env("RAG_TOP_K", "TOP_K"))
    candidate_multiplier: int = Field(
        default=4, validation_alias=_env("RAG_CANDIDATE_MULTIPLIER", "CANDIDATE_MULTIPLIER")
    )
    dense_weight: float = Field(
        default=0.6, validation_alias=_env("RAG_DENSE_WEIGHT", "DENSE_WEIGHT")
    )
    # Measured separation on this corpus: on-topic queries score 0.53 to
    # 0.65, off-topic noise 0.05 to 0.26. 0.32 sits in the gap with margin
    # on both sides. Re-measure if the corpus or the embedding changes.
    min_score: float = Field(default=0.32, validation_alias=_env("RAG_MIN_SCORE", "MIN_SCORE"))

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
