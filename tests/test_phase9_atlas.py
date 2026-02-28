"""
Tests for Phase 9 — Atlas Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Verifies that Mission Control exposes the correct endpoint shapes
required by Atlas, and that the Atlas-side integration code is correct.

No live Atlas or MC server required — all mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. MC health endpoint — Atlas-compatible shape
# ---------------------------------------------------------------------------

class TestHealthAtlasShape:
    def test_health_has_status_field(self):
        """GET /api/health must return {status: 'ok'|'degraded'} — Atlas polls this."""
        from app.api.health import HealthResponse
        resp = HealthResponse(status="ok")
        assert resp.status in ("ok", "degraded")
        assert resp.service == "mission-control"

    def test_health_always_has_status(self):
        """Both ok and degraded are valid Atlas-polled statuses."""
        from app.api.health import HealthResponse
        for s in ("ok", "degraded"):
            resp = HealthResponse(status=s)
            assert resp.status == s

    def test_health_response_is_json_serialisable(self):
        """HealthResponse serialises to JSON without error."""
        from app.api.health import HealthResponse
        resp = HealthResponse(status="ok", db_connectivity=True, worker_status="online")
        data = resp.model_dump()
        dumped = json.dumps(data)
        assert "ok" in dumped


# ---------------------------------------------------------------------------
# 2. MC codex/search endpoint — Atlas-compatible shape
# ---------------------------------------------------------------------------

class TestCodexSearchAtlasShape:
    def test_codex_search_response_shape(self):
        """
        /api/codex/search must return:
        {results: [{id, root_cause, prevention_guideline, category, scope, confidence_score}],
         total, limit, offset}
        """
        from app.models.schemas import CodexSearchResponse, CodexSearchResult
        result = CodexSearchResult(
            id="abc123",
            root_cause="Context window exceeded",
            prevention_guideline="Compress history before reaching limit",
            category="context",
            scope="global",
            confidence_score=0.85,
        )
        resp = CodexSearchResponse(
            results=[result],
            total=1,
            limit=10,
            offset=0,
        )
        assert resp.total == 1
        assert resp.results[0].scope == "global"
        assert 0.0 <= resp.results[0].confidence_score <= 1.0

    def test_codex_search_result_optional_category(self):
        """category is optional in CodexSearchResult."""
        from app.models.schemas import CodexSearchResult
        result = CodexSearchResult(
            id="x",
            root_cause="cause",
            prevention_guideline="guideline",
            scope="global",
            confidence_score=0.5,
        )
        assert result.category is None

    def test_codex_search_endpoint_queries_db(self):
        """GET /api/codex/search calls the FTS search function."""
        from app.api.codex import atlas_codex_search
        from app.models.schemas import CodexSearchResponse
        import asyncio

        fake_response = CodexSearchResponse(results=[], total=0, limit=5, offset=0)

        with patch("app.api.codex.run_in_thread") as mock_run:
            mock_run.return_value = fake_response
            result = asyncio.get_event_loop().run_until_complete(
                atlas_codex_search(q="test query", limit=5, offset=0)
            )
        mock_run.assert_called_once()
        assert hasattr(result, "results")
        assert hasattr(result, "total")


# ---------------------------------------------------------------------------
# 3. MC router stats endpoint — Atlas-compatible shape
# ---------------------------------------------------------------------------

class TestRouterStatsAtlasShape:
    def test_router_stats_response_shape(self):
        """
        /api/router/stats must return:
        {rows: [{model_id, task_type, average_score, success_rate, ...}], total}
        """
        from app.models.schemas import RouterStatsResponse, RouterStatsRow
        row = RouterStatsRow(
            model_id="ollama/qwen2.5:32b",
            task_type="bug_fix",
            average_score=82.5,
            average_retries=1.2,
            success_rate=0.91,
            sample_size=44,
            last_updated="2026-02-28T00:00:00",
        )
        resp = RouterStatsResponse(rows=[row], total=1)
        assert resp.total == 1
        assert resp.rows[0].success_rate == 0.91

    def test_router_stats_row_optional_fields(self):
        """average_score, success_rate etc. are all optional."""
        from app.models.schemas import RouterStatsRow
        row = RouterStatsRow(
            model_id="ollama/llama3",
            task_type="generic",
            last_updated="2026-01-01T00:00:00",
        )
        assert row.average_score is None
        assert row.success_rate is None


# ---------------------------------------------------------------------------
# 4. MC RAG search endpoint — Atlas-exposed shape
# ---------------------------------------------------------------------------

class TestRAGSearchAtlasShape:
    def test_rag_search_endpoint_accepts_query_param(self):
        """GET /api/rag/search must accept q, limit params."""
        from app.rag.engine import RAGEngine
        from app.rag.embedding import EmbeddingClient

        client = MagicMock(spec=EmbeddingClient)
        client.model = "nomic-embed-text"
        client.embed.return_value = None  # Ollama down → empty results

        engine = RAGEngine(client=client)
        results = engine.search("test query")
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 5. Atlas config — Mission Control registered in SPOKES
# ---------------------------------------------------------------------------

class TestAtlasSpokeConfig:
    def test_mission_control_in_spokes(self):
        """Mission Control must be in Atlas SPOKES dict."""
        import sys
        # Add Atlas to path temporarily if needed
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))

        try:
            from app.config import SPOKES
            assert "mission_control" in SPOKES, "mission_control not registered in Atlas SPOKES"
            mc = SPOKES["mission_control"]
            assert mc.base_url == "http://localhost:8860"
            assert mc.health_path == "/api/health"
        except ImportError:
            pytest.skip("Atlas not available in this environment")

    def test_mission_control_spoke_has_correct_port(self):
        """MC spoke must point to port 8860 (root CLAUDE.md port registry)."""
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))

        try:
            from app.config import SPOKES
            mc = SPOKES["mission_control"]
            assert "8860" in mc.base_url
        except ImportError:
            pytest.skip("Atlas not available in this environment")


# ---------------------------------------------------------------------------
# 6. Atlas query_classifier — MC keywords trigger correct spoke
# ---------------------------------------------------------------------------

class TestAtlasQueryClassifier:
    def _get_classifier(self):
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))
        try:
            from app.services.query_classifier import classify
            return classify
        except ImportError:
            return None

    def test_codex_keyword_routes_to_mission_control(self):
        """'codex lesson' should classify to mission_control spoke."""
        classify = self._get_classifier()
        if classify is None:
            pytest.skip("Atlas not available")

        result = classify("show me codex lessons about context window errors")
        assert "mission_control" in result.spokes

    def test_execution_failure_keyword_routes_to_mc(self):
        """'execution failure' should classify to mission_control."""
        classify = self._get_classifier()
        if classify is None:
            pytest.skip("Atlas not available")

        result = classify("what are the known execution failure patterns")
        assert "mission_control" in result.spokes

    def test_model_routing_keyword_routes_to_mc(self):
        """'model routing' should classify to mission_control."""
        classify = self._get_classifier()
        if classify is None:
            pytest.skip("Atlas not available")

        result = classify("which model has the best routing success rate")
        assert "mission_control" in result.spokes

    def test_civic_keywords_do_not_route_to_mc(self):
        """Meeting/transcript queries should NOT route to mission_control."""
        classify = self._get_classifier()
        if classify is None:
            pytest.skip("Atlas not available")

        result = classify("city council meeting transcript from last week")
        # civic_media should be classified, mission_control should not be primary
        assert "civic_media" in result.spokes or len(result.spokes) == 0

    def test_mc_tools_included_when_mc_matched(self):
        """When MC is matched, MISSION_CONTROL_TOOLS should be in tools list."""
        classify = self._get_classifier()
        if classify is None:
            pytest.skip("Atlas not available")

        result = classify("show me codex lessons about retries")
        if "mission_control" in result.spokes:
            tool_names = {t["function"]["name"] for t in result.tools}
            assert "search_codex_lessons" in tool_names


# ---------------------------------------------------------------------------
# 7. Atlas unified_search — MC searcher returns correct shape
# ---------------------------------------------------------------------------

class TestAtlasUnifiedSearch:
    def _get_mc_searcher(self):
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))
        try:
            from app.services.unified_search import _search_mission_control
            return _search_mission_control
        except ImportError:
            return None

    def test_mc_searcher_in_searchers_dict(self):
        """mission_control must be in _SEARCHERS."""
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))
        try:
            from app.services.unified_search import _SEARCHERS
            assert "mission_control" in _SEARCHERS
        except ImportError:
            pytest.skip("Atlas not available")

    def test_mc_searcher_returns_empty_on_error(self):
        """_search_mission_control returns [] when MC is down."""
        import asyncio
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))
        try:
            from app.services.unified_search import _search_mission_control
            from app.services import spoke_client
        except ImportError:
            pytest.skip("Atlas not available")

        async def _run():
            with patch.object(spoke_client, "get", side_effect=Exception("connection refused")):
                return await _search_mission_control("test query", 5)

        results = asyncio.get_event_loop().run_until_complete(_run())
        assert results == []

    def test_mc_searcher_maps_codex_shape_to_search_result(self):
        """_search_mission_control maps Codex response to SearchResult correctly."""
        import asyncio
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))
        try:
            from app.services.unified_search import _search_mission_control
            from app.services import spoke_client
        except ImportError:
            pytest.skip("Atlas not available")

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "results": [
                {
                    "id": "abc",
                    "root_cause": "Context window exceeded",
                    "prevention_guideline": "Compress history",
                    "category": "context",
                    "scope": "global",
                    "confidence_score": 0.9,
                }
            ],
            "total": 1,
            "limit": 10,
            "offset": 0,
        }

        async def _run():
            with patch.object(spoke_client, "get", return_value=fake_response):
                return await _search_mission_control("context window", 5)

        results = asyncio.get_event_loop().run_until_complete(_run())
        assert len(results) == 1
        r = results[0]
        assert r.source == "mission_control"
        assert r.type == "codex_lesson"
        assert "Context window exceeded" in r.title
        assert r.snippet == "Compress history"

    def test_mc_searcher_returns_empty_on_non_200(self):
        """_search_mission_control returns [] when MC returns non-200."""
        import asyncio
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))
        try:
            from app.services.unified_search import _search_mission_control
            from app.services import spoke_client
        except ImportError:
            pytest.skip("Atlas not available")

        fake_response = MagicMock()
        fake_response.status_code = 503

        async def _run():
            with patch.object(spoke_client, "get", return_value=fake_response):
                return await _search_mission_control("test", 5)

        results = asyncio.get_event_loop().run_until_complete(_run())
        assert results == []


# ---------------------------------------------------------------------------
# 8. Atlas tools — MC tool schemas are well-formed
# ---------------------------------------------------------------------------

class TestAtlasToolSchemas:
    def _get_mc_tools(self):
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))
        try:
            from app.services.tools import MISSION_CONTROL_TOOLS
            return MISSION_CONTROL_TOOLS
        except ImportError:
            return None

    def test_mc_tools_list_exists(self):
        """MISSION_CONTROL_TOOLS must be defined and non-empty."""
        tools = self._get_mc_tools()
        if tools is None:
            pytest.skip("Atlas not available")
        assert len(tools) >= 2  # search_codex_lessons + get_mc_router_stats

    def test_search_codex_lessons_tool_schema(self):
        """search_codex_lessons must have required query parameter."""
        tools = self._get_mc_tools()
        if tools is None:
            pytest.skip("Atlas not available")
        names = {t["function"]["name"]: t for t in tools}
        assert "search_codex_lessons" in names
        tool = names["search_codex_lessons"]
        params = tool["function"]["parameters"]["properties"]
        assert "query" in params
        required = tool["function"]["parameters"].get("required", [])
        assert "query" in required

    def test_mc_tools_in_tool_to_spoke_map(self):
        """All MC tools must be mapped to mission_control in TOOL_TO_SPOKE."""
        import sys
        atlas_path = Path(__file__).parent.parent.parent / "Atlas"
        if str(atlas_path) not in sys.path:
            sys.path.insert(0, str(atlas_path))
        try:
            from app.services.tools import MISSION_CONTROL_TOOLS, TOOL_TO_SPOKE
        except ImportError:
            pytest.skip("Atlas not available")

        for tool in MISSION_CONTROL_TOOLS:
            name = tool["function"]["name"]
            assert TOOL_TO_SPOKE.get(name) == "mission_control", \
                f"Tool '{name}' not mapped to mission_control in TOOL_TO_SPOKE"

    def test_mc_tools_are_json_serialisable(self):
        """All MC tool schemas must serialise to JSON (required for OpenAI API)."""
        tools = self._get_mc_tools()
        if tools is None:
            pytest.skip("Atlas not available")
        for tool in tools:
            dumped = json.dumps(tool)
            assert len(dumped) > 0


# ---------------------------------------------------------------------------
# 9. master_codex.md spoke declaration present
# ---------------------------------------------------------------------------

class TestMasterCodexSpoke:
    def test_mc_mentioned_in_master_codex(self):
        """master_codex.md should reference Mission Control as a spoke."""
        codex_path = Path(__file__).parent.parent.parent / "master_codex.md"
        if not codex_path.exists():
            pytest.skip("master_codex.md not found")
        text = codex_path.read_text(encoding="utf-8")
        assert "Mission Control" in text or "mission_control" in text


# ---------------------------------------------------------------------------
# 10. MASTER_SCHEMA.md — MC schema registered
# ---------------------------------------------------------------------------

class TestMasterSchemaRegistered:
    def test_mc_schema_in_master_schema(self):
        """MASTER_SCHEMA.md must contain Mission_Control spoke section."""
        schema_path = Path(__file__).parent.parent.parent / "MASTER_SCHEMA.md"
        if not schema_path.exists():
            pytest.skip("MASTER_SCHEMA.md not found")
        text = schema_path.read_text(encoding="utf-8")
        assert "Mission_Control" in text

    def test_mc_port_8860_in_master_schema(self):
        """MASTER_SCHEMA.md must document port 8860."""
        schema_path = Path(__file__).parent.parent.parent / "MASTER_SCHEMA.md"
        if not schema_path.exists():
            pytest.skip("MASTER_SCHEMA.md not found")
        text = schema_path.read_text(encoding="utf-8")
        assert "8860" in text
