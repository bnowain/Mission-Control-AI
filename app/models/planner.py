"""
Mission Control — Planning Modes
=================================
Two planning variants with real-time streaming via on_event callbacks:

1. plan_with_claude()  — uses `claude -p --verbose` (Claude Code subprocess)
2. plan_with_local()   — uses a local reasoning model via LiteLLM with
                         real-time <think> block detection

Both call on_event(PlanEvent) as content arrives so the SSE endpoint can
forward events to the browser without buffering the full response.

Dataclasses are also exported for use by planner_api.py and tests.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.logging import get_logger
from app.models.claude_code_provider import ClaudeCodeProvider
from app.models.claude_code_provider import PlanEvent  # re-export

log = get_logger("planner")


# ---------------------------------------------------------------------------
# Shared dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PlanResult:
    """Final result returned by plan_with_claude() or plan_with_local()."""
    response_text: str
    thinking_text: Optional[str]
    events: list[PlanEvent]
    duration_ms: int
    model_used: str
    cancelled: bool = False


# Callback type alias
OnEvent = Callable[[PlanEvent], None]


# ---------------------------------------------------------------------------
# Claude Code planning mode
# ---------------------------------------------------------------------------

def plan_with_claude(
    prompt: str,
    on_event: OnEvent,
    timeout_s: int = 300,
) -> PlanResult:
    """
    Spawn `claude -p --verbose` and stream events via on_event().

    Returns PlanResult with the full accumulated response.
    """
    provider = ClaudeCodeProvider(timeout_s=timeout_s)
    events: list[PlanEvent] = []
    output_lines: list[str] = []
    thinking_lines: list[str] = []
    cancelled = False
    start = time.perf_counter()

    for event in provider.run_plan(prompt, timeout_s=timeout_s):
        events.append(event)
        on_event(event)

        if event.event_type == "output":
            output_lines.append(event.content)
        elif event.event_type == "thinking":
            thinking_lines.append(event.content)
        elif event.event_type == "cancelled":
            cancelled = True
        elif event.event_type == "done":
            # done.content is the full response from run_plan
            # but we've already accumulated output_lines, use whichever is richer
            if event.content and not output_lines:
                output_lines.append(event.content)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return PlanResult(
        response_text="\n".join(output_lines),
        thinking_text="\n\n".join(thinking_lines) if thinking_lines else None,
        events=events,
        duration_ms=elapsed_ms,
        model_used="claude",
        cancelled=cancelled,
    )


# ---------------------------------------------------------------------------
# Local reasoning model planning mode
# ---------------------------------------------------------------------------

_THINK_OPEN_RE = re.compile(r"<think>", re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"</think>", re.DOTALL)


def plan_with_local(
    prompt: str,
    on_event: OnEvent,
    model_class: str = "reasoning_model",
    timeout_s: int = 300,
) -> PlanResult:
    """
    Stream a local reasoning model via LiteLLM with real-time <think> detection.

    Tokens inside <think>...</think> are emitted as "thinking" events.
    All other tokens are emitted as "output" events.

    Returns PlanResult with full accumulated response + thinking.
    """
    from app.router.adaptive import get_router
    from app.models.schemas import CapabilityClass, TaskType

    router = get_router()

    # Map model_class string → CapabilityClass
    cap_class_map = {
        "reasoning_model": CapabilityClass.REASONING_MODEL,
        "fast_model":      CapabilityClass.FAST_MODEL,
        "coder_model":     CapabilityClass.CODER_MODEL,
        "planner_model":   CapabilityClass.PLANNER_MODEL,
        "heavy_model":     CapabilityClass.HEAVY_MODEL,
    }
    cap_class = cap_class_map.get(model_class, CapabilityClass.REASONING_MODEL)

    try:
        decision = router.select(
            task_type=TaskType.GENERIC,
            retry_count=0,
            force_class=cap_class,
        )
    except Exception as exc:
        err_event = PlanEvent(event_type="error", content=f"Router error: {exc}")
        on_event(err_event)
        return PlanResult(
            response_text="",
            thinking_text=None,
            events=[err_event],
            duration_ms=0,
            model_used=model_class,
            cancelled=False,
        )

    messages = [{"role": "user", "content": prompt}]
    events: list[PlanEvent] = []
    output_parts: list[str] = []
    thinking_parts: list[str] = []
    buffer = ""
    in_think = False
    cancelled = False
    start = time.perf_counter()

    try:
        # Use the AdaptiveRouter (which wraps the LiteLLM Router) so that
        # "reasoning_model" is resolved to the actual configured model.
        # stream=True is passed through router.complete() via **kwargs.
        stream = router.complete(decision, messages, stream=True)

        for chunk in stream:
            delta = ""
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta.content or ""

            if not delta:
                continue

            buffer += delta

            # Process buffer character-by-character for <think> tag detection
            while buffer:
                if not in_think:
                    # Look for opening <think>
                    open_pos = buffer.find("<think>")
                    if open_pos == -1:
                        # No opening tag — emit all as output
                        chunk_content = buffer
                        buffer = ""
                        if chunk_content:
                            output_parts.append(chunk_content)
                            ev = PlanEvent(event_type="output", content=chunk_content)
                            events.append(ev)
                            on_event(ev)
                    else:
                        # Emit text before <think> as output
                        before = buffer[:open_pos]
                        if before:
                            output_parts.append(before)
                            ev = PlanEvent(event_type="output", content=before)
                            events.append(ev)
                            on_event(ev)
                        buffer = buffer[open_pos + len("<think>"):]
                        in_think = True
                else:
                    # Inside <think> block — look for closing </think>
                    close_pos = buffer.find("</think>")
                    if close_pos == -1:
                        # Still inside — emit as thinking
                        chunk_content = buffer
                        buffer = ""
                        if chunk_content:
                            thinking_parts.append(chunk_content)
                            ev = PlanEvent(event_type="thinking", content=chunk_content)
                            events.append(ev)
                            on_event(ev)
                    else:
                        # Close tag found
                        think_content = buffer[:close_pos]
                        if think_content:
                            thinking_parts.append(think_content)
                            ev = PlanEvent(event_type="thinking", content=think_content)
                            events.append(ev)
                            on_event(ev)
                        buffer = buffer[close_pos + len("</think>"):]
                        in_think = False

    except Exception as exc:
        err_event = PlanEvent(event_type="error", content=f"LiteLLM stream error: {exc}")
        events.append(err_event)
        on_event(err_event)
        cancelled = True

    # Flush any remaining buffer
    if buffer:
        if in_think:
            thinking_parts.append(buffer)
            ev = PlanEvent(event_type="thinking", content=buffer)
        else:
            output_parts.append(buffer)
            ev = PlanEvent(event_type="output", content=buffer)
        events.append(ev)
        on_event(ev)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    done_event = PlanEvent(
        event_type="done" if not cancelled else "cancelled",
        content="".join(output_parts),
    )
    events.append(done_event)
    on_event(done_event)

    return PlanResult(
        response_text="".join(output_parts),
        thinking_text="".join(thinking_parts) if thinking_parts else None,
        events=events,
        duration_ms=elapsed_ms,
        model_used=decision.selected_model,
        cancelled=cancelled,
    )
