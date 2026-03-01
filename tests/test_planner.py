"""
Tests for the Planner feature set:
  - Chain-of-thought extraction (_extract_thinking, _build_result)
  - ModelSource.CLI_CLAUDE_CODE enum value
  - ExecutionResult.thinking_text field
  - ClaudeCodeProvider (mocked subprocess)
  - plan_with_claude() / plan_with_local() planning modes
  - SSE API endpoints: /planner/claude, /planner/local, /planner/cancel, /planner/status

No live LLMs, no live `claude` CLI required — all I/O is mocked.
"""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 1. Schemas — ModelSource + ExecutionResult.thinking_text
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_model_source_cli_claude_code(self):
        from app.models.schemas import ModelSource
        assert ModelSource.CLI_CLAUDE_CODE == "cli:claude_code"

    def test_execution_result_has_thinking_text(self):
        from app.models.schemas import ExecutionResult, RoutingDecision, ContextTier
        decision = RoutingDecision(
            selected_model="test-model",
            context_size=4096,
            context_tier=ContextTier.EXECUTION,
            temperature=0.1,
            routing_reason="test",
        )
        result = ExecutionResult(
            decision=decision,
            response_text="Hello world",
            thinking_text="I am thinking...",
        )
        assert result.thinking_text == "I am thinking..."
        assert result.response_text == "Hello world"

    def test_execution_result_thinking_text_optional(self):
        from app.models.schemas import ExecutionResult, RoutingDecision, ContextTier
        decision = RoutingDecision(
            selected_model="test-model",
            context_size=4096,
            context_tier=ContextTier.EXECUTION,
            temperature=0.1,
            routing_reason="test",
        )
        result = ExecutionResult(decision=decision, response_text="Hi")
        assert result.thinking_text is None


# ---------------------------------------------------------------------------
# 2. _extract_thinking — regex logic
# ---------------------------------------------------------------------------

class TestExtractThinking:
    def _fn(self, text):
        from app.models.executor import _extract_thinking
        return _extract_thinking(text)

    def test_no_think_block(self):
        clean, thinking = self._fn("Hello world")
        assert clean == "Hello world"
        assert thinking is None

    def test_single_think_block_stripped(self):
        text = "<think>I am reasoning here.</think>\nThe answer is 42."
        clean, thinking = self._fn(text)
        assert "<think>" not in clean
        assert "The answer is 42." in clean
        assert thinking == "I am reasoning here."

    def test_multiple_think_blocks(self):
        text = "<think>Step 1</think> middle <think>Step 2</think> end"
        clean, thinking = self._fn(text)
        assert "Step 1" not in clean
        assert "Step 2" not in clean
        assert "middle" in clean
        assert "end" in clean
        assert "Step 1" in thinking
        assert "Step 2" in thinking

    def test_multiline_think_block(self):
        text = "<think>\nLine A\nLine B\n</think>\nResult"
        clean, thinking = self._fn(text)
        assert "Line A" in thinking
        assert "Line B" in thinking
        assert "Result" in clean

    def test_empty_think_block(self):
        text = "<think></think>output"
        clean, thinking = self._fn(text)
        # Empty block — no thinking captured (strip produces "")
        assert "output" in clean

    def test_text_with_only_think_block(self):
        text = "<think>all thinking</think>"
        clean, thinking = self._fn(text)
        assert clean == ""
        assert thinking == "all thinking"


# ---------------------------------------------------------------------------
# 3. _build_result — thinking extraction via response object
# ---------------------------------------------------------------------------

class TestBuildResult:
    def _make_decision(self):
        from app.models.schemas import RoutingDecision, ContextTier
        return RoutingDecision(
            selected_model="test",
            context_size=4096,
            context_tier=ContextTier.EXECUTION,
            temperature=0.1,
            routing_reason="test",
        )

    def _make_response(self, content, reasoning_content=None):
        """Build a minimal LiteLLM-shaped response object."""
        msg = MagicMock()
        msg.content = content
        if reasoning_content is not None:
            msg.reasoning_content = reasoning_content
        else:
            # hasattr returns False when attribute doesn't exist
            del msg.reasoning_content
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage = None
        return resp

    def test_plain_response_no_thinking(self):
        from app.models.executor import _build_result
        resp = self._make_response("Hello world")
        result = _build_result(
            response=resp,
            decision=self._make_decision(),
            elapsed_ms=100,
            retry_count=0,
            escalation_count=0,
        )
        assert result.response_text == "Hello world"
        assert result.thinking_text is None

    def test_think_block_extracted(self):
        from app.models.executor import _build_result
        resp = self._make_response("<think>My reasoning</think>\nFinal answer")
        result = _build_result(
            response=resp,
            decision=self._make_decision(),
            elapsed_ms=100,
            retry_count=0,
            escalation_count=0,
        )
        assert result.thinking_text == "My reasoning"
        assert "<think>" not in result.response_text
        assert "Final answer" in result.response_text

    def test_reasoning_content_field(self):
        from app.models.executor import _build_result
        resp = self._make_response("The answer is 42.", reasoning_content="Deep thoughts")
        result = _build_result(
            response=resp,
            decision=self._make_decision(),
            elapsed_ms=100,
            retry_count=0,
            escalation_count=0,
        )
        assert result.thinking_text == "Deep thoughts"
        assert result.response_text == "The answer is 42."

    def test_reasoning_content_plus_think_block_merged(self):
        from app.models.executor import _build_result
        resp = self._make_response(
            "<think>block thinking</think>\nAnswer",
            reasoning_content="prefix thinking",
        )
        result = _build_result(
            response=resp,
            decision=self._make_decision(),
            elapsed_ms=100,
            retry_count=0,
            escalation_count=0,
        )
        assert "prefix thinking" in result.thinking_text
        assert "block thinking" in result.thinking_text
        assert "Answer" in result.response_text


# ---------------------------------------------------------------------------
# 4. ClaudeCodeProvider
# ---------------------------------------------------------------------------

class TestClaudeCodeProvider:
    def test_is_available_true_when_claude_on_path(self):
        from app.models.claude_code_provider import ClaudeCodeProvider
        with patch("shutil.which", return_value="/usr/bin/claude"):
            assert ClaudeCodeProvider.is_available() is True

    def test_is_available_false_when_not_found(self):
        from app.models.claude_code_provider import ClaudeCodeProvider
        with patch("shutil.which", return_value=None):
            assert ClaudeCodeProvider.is_available() is False

    def test_run_task_returns_stdout(self):
        from app.models.claude_code_provider import ClaudeCodeProvider
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("Hello from claude", "")
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            provider = ClaudeCodeProvider()
            result = provider.run_task("Write hello world")

        assert result.response_text == "Hello from claude"
        assert result.cancelled is False
        assert result.duration_ms >= 0

    def test_run_task_cli_not_found(self):
        from app.models.claude_code_provider import ClaudeCodeProvider
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            provider = ClaudeCodeProvider()
            result = provider.run_task("test prompt")
        assert "not found" in result.response_text.lower()
        assert result.cancelled is False

    def test_run_plan_yields_output_events(self):
        from app.models.claude_code_provider import ClaudeCodeProvider
        stdout_lines = "Line one\nLine two\n"
        mock_proc = MagicMock()
        mock_proc.stdout = StringIO(stdout_lines)
        mock_proc.stderr = StringIO("")
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            provider = ClaudeCodeProvider()
            events = list(provider.run_plan("Plan something"))

        output_events = [e for e in events if e.event_type == "output"]
        done_events = [e for e in events if e.event_type == "done"]
        assert len(output_events) == 2
        assert output_events[0].content == "Line one"
        assert output_events[1].content == "Line two"
        assert len(done_events) == 1

    def test_run_plan_classifies_thinking_lines(self):
        from app.models.claude_code_provider import ClaudeCodeProvider
        stdout_lines = "[thinking] I need to think about this\nRegular output\n"
        mock_proc = MagicMock()
        mock_proc.stdout = StringIO(stdout_lines)
        mock_proc.stderr = StringIO("")
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            provider = ClaudeCodeProvider()
            events = list(provider.run_plan("Plan something"))

        thinking_events = [e for e in events if e.event_type == "thinking"]
        output_events = [e for e in events if e.event_type == "output"]
        assert len(thinking_events) == 1
        assert "I need to think" in thinking_events[0].content
        assert len(output_events) == 1
        assert output_events[0].content == "Regular output"

    def test_run_plan_cli_not_found(self):
        from app.models.claude_code_provider import ClaudeCodeProvider
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            provider = ClaudeCodeProvider()
            events = list(provider.run_plan("test"))
        assert any(e.event_type == "error" for e in events)

    def test_cancel_terminates_process(self):
        from app.models.claude_code_provider import ClaudeCodeProvider
        mock_proc = MagicMock()
        provider = ClaudeCodeProvider()
        provider._process = mock_proc
        provider.cancel()
        mock_proc.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# 5. plan_with_claude()
# ---------------------------------------------------------------------------

class TestPlanWithClaude:
    def test_collects_events_and_returns_result(self):
        from app.models.claude_code_provider import PlanEvent
        from app.models.planner import plan_with_claude

        fake_events = [
            PlanEvent(event_type="thinking", content="Thinking step"),
            PlanEvent(event_type="output", content="Output line"),
            PlanEvent(event_type="done", content="Full response"),
        ]

        with patch("app.models.planner.ClaudeCodeProvider") as MockProvider:
            instance = MockProvider.return_value
            instance.run_plan.return_value = iter(fake_events)

            collected: list[PlanEvent] = []
            result = plan_with_claude(
                prompt="Design a system",
                on_event=collected.append,
            )

        assert len(collected) == 3
        assert result.thinking_text == "Thinking step"
        assert "Output line" in result.response_text
        assert result.model_used == "claude"
        assert result.cancelled is False

    def test_cancelled_flag_set(self):
        from app.models.claude_code_provider import PlanEvent
        from app.models.planner import plan_with_claude

        fake_events = [
            PlanEvent(event_type="cancelled", content="Session cancelled."),
        ]

        with patch("app.models.planner.ClaudeCodeProvider") as MockProvider:
            instance = MockProvider.return_value
            instance.run_plan.return_value = iter(fake_events)

            result = plan_with_claude(prompt="test", on_event=lambda e: None)

        assert result.cancelled is True

    def test_multiple_thinking_chunks_joined(self):
        from app.models.claude_code_provider import PlanEvent
        from app.models.planner import plan_with_claude

        fake_events = [
            PlanEvent(event_type="thinking", content="Part A"),
            PlanEvent(event_type="thinking", content="Part B"),
            PlanEvent(event_type="done", content=""),
        ]

        with patch("app.models.planner.ClaudeCodeProvider") as MockProvider:
            instance = MockProvider.return_value
            instance.run_plan.return_value = iter(fake_events)

            result = plan_with_claude(prompt="test", on_event=lambda e: None)

        assert result.thinking_text is not None
        assert "Part A" in result.thinking_text
        assert "Part B" in result.thinking_text


# ---------------------------------------------------------------------------
# 6. plan_with_local()
# ---------------------------------------------------------------------------

class TestPlanWithLocal:
    def _make_chunk(self, content: str):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = content
        return chunk

    def test_plain_output_no_thinking(self):
        from app.models.planner import plan_with_local
        from app.models.schemas import ContextTier, RoutingDecision

        decision = RoutingDecision(
            selected_model="ollama/qwen2.5:7b",
            context_size=4096,
            context_tier=ContextTier.EXECUTION,
            temperature=0.1,
            routing_reason="test",
        )

        chunks = [self._make_chunk("Hello "), self._make_chunk("world")]

        with patch("app.router.adaptive.get_router") as mock_router_fn:
            mock_router = MagicMock()
            mock_router.select.return_value = decision
            mock_router.complete.return_value = iter(chunks)
            mock_router_fn.return_value = mock_router

            collected = []
            result = plan_with_local(
                prompt="test",
                on_event=collected.append,
                model_class="reasoning_model",
            )

        output_events = [e for e in collected if e.event_type == "output"]
        assert "Hello " in "".join(e.content for e in output_events)
        assert result.thinking_text is None
        assert "Hello " in result.response_text

    def test_think_block_streamed_as_thinking_events(self):
        from app.models.planner import plan_with_local
        from app.models.schemas import ContextTier, RoutingDecision

        decision = RoutingDecision(
            selected_model="ollama/deepseek-r1:7b",
            context_size=4096,
            context_tier=ContextTier.EXECUTION,
            temperature=0.1,
            routing_reason="test",
        )

        # Simulate streaming a response with <think> blocks
        chunks = [
            self._make_chunk("<think>"),
            self._make_chunk("my reasoning"),
            self._make_chunk("</think>"),
            self._make_chunk("final answer"),
        ]

        with patch("app.router.adaptive.get_router") as mock_router_fn:
            mock_router = MagicMock()
            mock_router.select.return_value = decision
            mock_router.complete.return_value = iter(chunks)
            mock_router_fn.return_value = mock_router

            collected = []
            result = plan_with_local(
                prompt="test",
                on_event=collected.append,
            )

        thinking_events = [e for e in collected if e.event_type == "thinking"]
        output_events = [e for e in collected if e.event_type == "output"]

        assert "my reasoning" in "".join(e.content for e in thinking_events)
        assert "final answer" in "".join(e.content for e in output_events)
        assert result.thinking_text is not None
        assert "my reasoning" in result.thinking_text

    def test_router_error_emits_error_event(self):
        from app.models.planner import plan_with_local

        with patch("app.router.adaptive.get_router") as mock_router_fn:
            mock_router = MagicMock()
            mock_router.select.side_effect = RuntimeError("No models available")
            mock_router_fn.return_value = mock_router

            collected = []
            result = plan_with_local(prompt="test", on_event=collected.append)

        error_events = [e for e in collected if e.event_type == "error"]
        assert len(error_events) >= 1
        assert "Router error" in error_events[0].content

    def test_litellm_not_installed_emits_error(self):
        from app.models.planner import plan_with_local
        import sys

        # Temporarily hide litellm from imports
        original = sys.modules.get("litellm")
        sys.modules["litellm"] = None  # type: ignore[assignment]
        try:
            collected = []
            result = plan_with_local(prompt="test", on_event=collected.append)
        finally:
            if original is not None:
                sys.modules["litellm"] = original
            else:
                del sys.modules["litellm"]

        error_events = [e for e in collected if e.event_type == "error"]
        assert any("litellm" in e.content.lower() for e in error_events)


# ---------------------------------------------------------------------------
# 7. SSE API endpoints
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client():
    """TestClient with a fresh app (no DB needed for planner routes)."""
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


class TestPlannerAPI:
    def test_status_returns_inactive_at_start(self, app_client):
        resp = app_client.get("/planner/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False
        assert data["session_id"] is None

    def test_cancel_no_active_session(self, app_client):
        resp = app_client.post(
            "/planner/cancel",
            json={"session_id": "nonexistent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] is False

    def test_claude_endpoint_streams_sse(self, app_client):
        """Mock plan_with_claude so no real claude CLI is needed.

        plan_with_claude is imported locally inside the route handler, so we
        patch it at the source module (app.models.planner).
        """
        from app.models.claude_code_provider import PlanEvent

        fake_events = [
            PlanEvent(event_type="thinking", content="Thinking…"),
            PlanEvent(event_type="output", content="Plan step 1"),
            PlanEvent(event_type="done", content="Plan step 1"),
        ]

        with patch("app.models.planner.plan_with_claude") as mock_plan:
            def fake_plan(prompt, on_event, timeout_s=300):
                from app.models.planner import PlanResult
                for ev in fake_events:
                    on_event(ev)
                return PlanResult(
                    response_text="Plan step 1",
                    thinking_text="Thinking…",
                    events=fake_events,
                    duration_ms=100,
                    model_used="claude",
                )
            mock_plan.side_effect = fake_plan

            resp = app_client.post(
                "/planner/claude",
                json={"prompt": "Plan a REST API"},
                headers={"Accept": "text/event-stream"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        raw = resp.text
        event_types = []
        for line in raw.splitlines():
            if line.startswith("event:"):
                event_types.append(line.split(":", 1)[1].strip())

        assert "done" in event_types

    def test_local_endpoint_streams_sse(self, app_client):
        """Mock plan_with_local so no real LiteLLM call is made."""
        from app.models.claude_code_provider import PlanEvent

        fake_events_local = [
            PlanEvent(event_type="thinking", content="Local thinking"),
            PlanEvent(event_type="output", content="Local output"),
            PlanEvent(event_type="done", content="Local output"),
        ]

        with patch("app.models.planner.plan_with_local") as mock_plan:
            def fake_plan(prompt, on_event, model_class="reasoning_model", timeout_s=300):
                from app.models.planner import PlanResult
                for ev in fake_events_local:
                    on_event(ev)
                return PlanResult(
                    response_text="Local output",
                    thinking_text="Local thinking",
                    events=fake_events_local,
                    duration_ms=200,
                    model_used="ollama/deepseek-r1:7b",
                )
            mock_plan.side_effect = fake_plan

            resp = app_client.post(
                "/planner/local",
                json={"prompt": "Plan something", "model_class": "reasoning_model"},
                headers={"Accept": "text/event-stream"},
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        raw = resp.text
        event_types = []
        for line in raw.splitlines():
            if line.startswith("event:"):
                event_types.append(line.split(":", 1)[1].strip())

        assert "done" in event_types

    def test_done_event_data_shape(self, app_client):
        """Verify the done event has the required fields."""
        from app.models.claude_code_provider import PlanEvent

        fake_events = [
            PlanEvent(event_type="done", content="Result"),
        ]

        with patch("app.models.planner.plan_with_claude") as mock_plan:
            def fake_plan(prompt, on_event, timeout_s=300):
                from app.models.planner import PlanResult
                for ev in fake_events:
                    on_event(ev)
                return PlanResult(
                    response_text="Result",
                    thinking_text=None,
                    events=fake_events,
                    duration_ms=50,
                    model_used="claude",
                )
            mock_plan.side_effect = fake_plan

            resp = app_client.post(
                "/planner/claude",
                json={"prompt": "test"},
            )

        assert resp.status_code == 200
        raw = resp.text

        # Find the done data line
        done_data = None
        lines = raw.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "event: done":
                # Next data: line
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("data:"):
                        done_data = json.loads(lines[j][5:].strip())
                        break
                break

        assert done_data is not None
        assert "response_text" in done_data
        assert "duration_ms" in done_data
        assert "model_used" in done_data
        assert done_data["model_used"] == "claude"
