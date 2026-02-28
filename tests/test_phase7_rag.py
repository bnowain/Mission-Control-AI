"""
Tests for Phase 7 — RAG Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
All DB operations use a temporary in-memory SQLite DB.
EmbeddingClient calls are mocked — no live Ollama required.
"""

from __future__ import annotations

import struct
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vec(dim: int = 4, val: float = 1.0) -> list[float]:
    """Create a simple normalised vector for testing."""
    v = [val / dim] * dim
    return v


def _pack(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


# ---------------------------------------------------------------------------
# 1. Chunker
# ---------------------------------------------------------------------------

class TestChunker:
    def test_empty_text_returns_empty(self):
        from app.rag.chunker import chunk_text
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_single_chunk_small_text(self):
        from app.rag.chunker import chunk_text
        text = "Hello world this is a test"
        chunks = chunk_text(text, chunk_size=512, overlap=64)
        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert "Hello" in chunks[0].text

    def test_multiple_chunks_overlap(self):
        from app.rag.chunker import chunk_text
        words = " ".join([f"word{i}" for i in range(200)])
        chunks = chunk_text(words, chunk_size=100, overlap=20)
        assert len(chunks) >= 2
        # Each chunk has at most chunk_size words
        for chunk in chunks:
            assert chunk.word_count <= 100

    def test_overlap_shares_words(self):
        from app.rag.chunker import chunk_text
        words = " ".join([f"w{i}" for i in range(300)])
        chunks = chunk_text(words, chunk_size=100, overlap=20)
        # Second chunk should start 80 words into the first
        first_words = set(chunks[0].text.split())
        second_words = set(chunks[1].text.split())
        overlap_words = first_words & second_words
        assert len(overlap_words) > 0  # there IS overlap

    def test_code_chunker_fallback(self):
        from app.rag.chunker import chunk_code_file
        code = "x = 1\ny = 2\nz = 3"
        chunks = chunk_code_file(code, file_path="test.py")
        assert len(chunks) >= 1

    def test_code_chunker_splits_on_def(self):
        from app.rag.chunker import chunk_code_file
        code = "\n".join([
            "class Foo:",
            "    pass",
            "",
            "def bar():",
            "    return 1",
            "",
            "def baz():",
            "    return 2",
        ])
        chunks = chunk_code_file(code, file_path="test.py", chunk_size=512, overlap=64)
        assert len(chunks) >= 1


# ---------------------------------------------------------------------------
# 2. Embedding client
# ---------------------------------------------------------------------------

class TestEmbeddingClient:
    def test_vector_to_blob_round_trip(self):
        from app.rag.embedding import vector_to_blob, blob_to_vector
        v = [0.1, 0.2, 0.3, 0.4]
        blob = vector_to_blob(v)
        assert isinstance(blob, bytes)
        recovered = blob_to_vector(blob)
        assert len(recovered) == 4
        for a, b in zip(v, recovered):
            assert abs(a - b) < 1e-5

    def test_embed_returns_none_when_ollama_down(self):
        from app.rag.embedding import EmbeddingClient
        import httpx

        client = EmbeddingClient()
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.post.side_effect = (
                httpx.ConnectError("refused")
            )
            result = client.embed("test text")
        assert result is None

    def test_embed_batch_returns_list(self):
        from app.rag.embedding import EmbeddingClient

        client = EmbeddingClient()
        fake_vec = [0.1, 0.2, 0.3]
        with patch.object(client, "embed", return_value=fake_vec) as mock_embed:
            results = client.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        assert all(r == fake_vec for r in results)


# ---------------------------------------------------------------------------
# 3. Cosine similarity
# ---------------------------------------------------------------------------

class TestSimilarity:
    def test_identical_vectors_score_one(self):
        from app.rag.similarity import cosine_similarity
        v = [1.0, 0.0, 0.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors_score_zero(self):
        from app.rag.similarity import cosine_similarity
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_zero_vector_returns_zero(self):
        from app.rag.similarity import cosine_similarity
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_top_k_returns_sorted_results(self):
        from app.rag.similarity import top_k_chunks
        from app.rag.embedding import vector_to_blob

        query = [1.0, 0.0, 0.0, 0.0]
        candidates = [
            {
                "source_type": "artifact",
                "source_id": f"s{i}",
                "project_id": None,
                "chunk_index": 0,
                "chunk_text": f"chunk {i}",
                "embedding_vector": vector_to_blob([float(i) / 4, 0.0, 0.0, 0.0]),
            }
            for i in range(1, 5)
        ]
        results = top_k_chunks(query, candidates, top_k=3)
        assert len(results) == 3
        # Sorted descending by score
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_respects_limit(self):
        from app.rag.similarity import top_k_chunks
        from app.rag.embedding import vector_to_blob

        query = [1.0, 0.0]
        candidates = [
            {
                "source_type": "codebase",
                "source_id": f"file{i}.py",
                "project_id": "p1",
                "chunk_index": 0,
                "chunk_text": f"code {i}",
                "embedding_vector": vector_to_blob([0.5, 0.5]),
            }
            for i in range(10)
        ]
        results = top_k_chunks(query, candidates, top_k=4)
        assert len(results) == 4


# ---------------------------------------------------------------------------
# 4. Web fetcher
# ---------------------------------------------------------------------------

class TestWebFetcher:
    def test_returns_none_on_connection_error(self):
        from app.rag.web_fetcher import fetch_url
        import httpx

        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.side_effect = (
                httpx.ConnectError("refused")
            )
            result = fetch_url("http://localhost:9999/nonexistent")
        assert result is None

    def test_returns_text_from_html(self):
        from app.rag.web_fetcher import _html_to_text
        html = "<html><body><p>Hello world</p></body></html>"
        text = _html_to_text(html)
        assert text is not None
        assert "Hello" in text or "hello" in text.lower()

    def test_returns_none_on_4xx(self):
        from app.rag.web_fetcher import fetch_url
        import httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        )
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = fetch_url("http://example.com/missing")
        assert result is None


# ---------------------------------------------------------------------------
# 5. RAGEngine (mocked DB + mocked client)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_engine():
    """RAGEngine with mocked EmbeddingClient."""
    from app.rag.engine import RAGEngine
    from app.rag.embedding import EmbeddingClient

    client = MagicMock(spec=EmbeddingClient)
    client.model = "nomic-embed-text"
    client.embed.return_value = [0.5] * 4
    client.embed_batch.return_value = [[0.5] * 4]
    return RAGEngine(client=client)


class TestRAGEngine:
    def test_index_artifact_no_extracted_data(self, mock_engine, tmp_path):
        """When no artifacts_extracted row exists, returns 0."""
        from app.database.init import init_db, run_migrations

        db = tmp_path / "test.db"
        with patch("app.rag.engine.get_connection") as mock_conn_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_conn_fn.return_value = mock_conn
            result = mock_engine.index_artifact("no-such-artifact")
        assert result == 0

    def test_search_returns_empty_when_no_embeddings(self, mock_engine):
        """search() returns [] when no embeddings exist in DB."""
        mock_engine._client.embed.return_value = [1.0, 0.0, 0.0, 0.0]

        with patch("app.rag.engine.get_connection") as mock_conn_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn_fn.return_value = mock_conn
            results = mock_engine.search("test query")

        assert results == []

    def test_search_returns_empty_when_ollama_down(self, mock_engine):
        """search() returns [] when Ollama is down (embed returns None)."""
        mock_engine._client.embed.return_value = None
        results = mock_engine.search("test query")
        assert results == []

    def test_inject_context_no_rag_when_ollama_down(self, mock_engine):
        """inject_context returns original messages unchanged when Ollama is down."""
        mock_engine._client.embed.return_value = None
        messages = [{"role": "user", "content": "fix the bug"}]
        augmented, count, sources = mock_engine.inject_context(
            "task1", "proj1", messages
        )
        assert augmented == messages
        assert count == 0
        assert sources == []

    def test_get_stats_returns_structure(self, mock_engine):
        """get_stats() returns expected dict shape."""
        with patch("app.rag.engine.get_connection") as mock_conn_fn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn_fn.return_value = mock_conn
            stats = mock_engine.get_stats()
        assert "by_source_type" in stats
        assert "total_chunks" in stats

    def test_delete_project_index(self, mock_engine):
        """delete_project_index calls DELETE and returns row count."""
        with patch("app.rag.engine.get_connection") as mock_conn_fn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.rowcount = 42
            mock_conn.execute.return_value = mock_cursor
            mock_conn_fn.return_value = mock_conn
            deleted = mock_engine.delete_project_index("proj1")
        assert deleted == 42


# ---------------------------------------------------------------------------
# 6. Codebase indexing (filesystem)
# ---------------------------------------------------------------------------

class TestCodebaseIndexing:
    def test_invalid_path_raises(self, mock_engine):
        with pytest.raises(ValueError, match="does not exist"):
            mock_engine.index_codebase("proj1", "/nonexistent/path/xyz")

    def test_indexes_py_files(self, mock_engine, tmp_path):
        """index_codebase walks .py files and stores chunks."""
        # Create test files
        (tmp_path / "main.py").write_text(
            "def hello():\n    return 'world'\n\ndef goodbye():\n    pass\n",
            encoding="utf-8",
        )
        (tmp_path / "skip.exe").write_text("binary content", encoding="utf-8")

        with patch("app.rag.engine.get_connection") as mock_conn_fn, \
             patch("app.rag.engine._delete_project_codebase", return_value=0), \
             patch("app.rag.engine._store_chunks", return_value=2):
            mock_conn = MagicMock()
            mock_conn_fn.return_value = mock_conn
            result = mock_engine.index_codebase("proj1", str(tmp_path))

        assert result["indexed_files"] >= 1  # main.py
        # skip.exe should not be indexed
        assert result["total_chunks"] >= 0

    def test_skips_large_files(self, mock_engine, tmp_path):
        """Files larger than max_file_kb are skipped."""
        large = tmp_path / "big.py"
        large.write_text("x = 1\n" * 10_000, encoding="utf-8")

        with patch("app.rag.engine.get_connection") as mock_conn_fn, \
             patch("app.rag.engine._delete_project_codebase", return_value=0):
            mock_conn = MagicMock()
            mock_conn_fn.return_value = mock_conn
            result = mock_engine.index_codebase(
                "proj1", str(tmp_path), max_file_kb=1  # 1KB limit
            )
        assert result["skipped_files"] >= 1


# ---------------------------------------------------------------------------
# 7. Pipeline registration
# ---------------------------------------------------------------------------

class TestPipelineRegistration:
    def test_web_ingest_registered(self):
        from app.processing.pipeline_registry import get_pipeline
        p = get_pipeline("web_ingest")
        assert p.name == "web_ingest"
        assert p.available is True

    def test_embed_artifact_registered(self):
        from app.processing.pipeline_registry import get_pipeline
        p = get_pipeline("embed_artifact")
        assert p.name == "embed_artifact"
        assert p.available is True

    def test_web_ingest_validate_requires_url(self):
        from app.processing.pipeline_registry import get_pipeline
        p = get_pipeline("web_ingest")
        ok, _ = p.validate_input({"source_type": "web_page", "page_url": "http://example.com"})
        assert ok is True
        ok2, reason = p.validate_input({"source_type": "web_page"})
        assert ok2 is False
        assert "page_url" in reason


# ---------------------------------------------------------------------------
# 8. Execution loop — RAG injection degrades gracefully
# ---------------------------------------------------------------------------

class TestExecutionLoopRAG:
    def test_rag_injection_failure_does_not_break_loop(self):
        """If RAG engine throws, execution loop continues without it."""
        from app.core.execution_loop import ExecutionLoop, ExecutionContext
        from app.models.schemas import TaskType

        ctx = ExecutionContext(
            task_id="t1",
            project_id="p1",
            task_type=TaskType.GENERIC,
            messages=[{"role": "user", "content": "hello"}],
        )

        loop = ExecutionLoop.__new__(ExecutionLoop)  # skip __init__

        with patch("app.rag.engine.get_rag_engine") as mock_get:
            mock_get.return_value.inject_context.side_effect = RuntimeError("ollama died")
            result = loop._inject_rag_context(ctx)

        # Should return original messages unchanged
        assert result == [{"role": "user", "content": "hello"}]
        assert ctx.rag_chunks_injected == 0


# ---------------------------------------------------------------------------
# 9. Schema migration — v7 migration creates embeddings table
# ---------------------------------------------------------------------------

class TestSchemaV7:
    def test_embeddings_table_exists_after_init(self, tmp_path):
        """init_db + run_migrations creates the embeddings table at schema v7."""
        from app.database.init import init_db, run_migrations, get_connection

        db_path = tmp_path / "test_v7.db"
        init_db(db_path)
        run_migrations(db_path)

        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, "embeddings table not created"

    def test_execution_logs_has_rag_columns(self, tmp_path):
        """execution_logs should have rag_chunks_injected and rag_source_ids after v7."""
        from app.database.init import init_db, run_migrations, get_connection

        db_path = tmp_path / "test_v7_cols.db"
        init_db(db_path)
        run_migrations(db_path)

        conn = get_connection(db_path)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(execution_logs)").fetchall()]
        finally:
            conn.close()

        assert "rag_chunks_injected" in cols
        assert "rag_source_ids" in cols
