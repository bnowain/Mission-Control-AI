"""
Mission Control — Claude Code Subprocess Provider
==================================================
Wraps `claude -p` (non-interactive CLI mode) as a model provider.
Uses the user's Claude subscription — no API key required.

ModelSource: cli:claude_code

Usage:
    provider = ClaudeCodeProvider()
    result = provider.run_task("Fix the null pointer at line 42.")

    # Streaming planning mode:
    for event in provider.run_plan("Design a REST API for user management."):
        print(event.event_type, event.content)

    # Cancel mid-run:
    provider.cancel()
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Generator, Optional

from app.core.logging import get_logger

log = get_logger("claude_code_provider")

# Default timeout for one-shot run_task() calls (seconds)
DEFAULT_TIMEOUT_S: int = 300


@dataclass
class ClaudeCodeResult:
    """Result from a completed ClaudeCodeProvider.run_task() call."""
    response_text: str
    thinking_text: Optional[str]   # extracted from --verbose thinking lines
    duration_ms: int
    cancelled: bool = False


@dataclass
class PlanEvent:
    """Single streaming event emitted by run_plan()."""
    event_type: str   # "thinking" | "output" | "tool_use" | "error" | "done" | "cancelled"
    content: str
    timestamp: float = field(default_factory=time.time)


# Regex to detect Claude Code verbose thinking lines
# Example: [thinking] Let me analyze the requirements...
_THINKING_RE = re.compile(r"^\[thinking\]\s*(.+)$", re.IGNORECASE)
_TOOL_RE = re.compile(r"^\[tool(?:_use)?\]\s*(.+)$", re.IGNORECASE)

# Diff line detection — standard unified diff format
# Lines starting with +++ / --- are file headers; + / - are added/removed lines
_DIFF_HEADER_RE = re.compile(r"^(\+\+\+|---)\s+")
_DIFF_ADD_RE = re.compile(r"^\+(?!\+\+)")     # + but not +++
_DIFF_DEL_RE = re.compile(r"^-(?!--)")         # - but not ---
_DIFF_HUNK_RE = re.compile(r"^@@\s+-\d")       # @@ -N,N +N,N @@ context


class ClaudeCodeProvider:
    """
    Subprocess wrapper for `claude -p`.

    Thread-safe cancel via cancel().
    """

    def __init__(self, timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Return True if `claude` is on PATH."""
        return shutil.which("claude") is not None

    def cancel(self) -> None:
        """Terminate the running subprocess, if any."""
        with self._lock:
            proc = self._process
        if proc is not None:
            try:
                proc.terminate()
                # Give it 2s to exit, then kill
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception as exc:  # noqa: BLE001
                log.warning("cancel() error", exc=str(exc))

    # ------------------------------------------------------------------
    # One-shot task execution
    # ------------------------------------------------------------------

    def run_task(self, prompt: str) -> ClaudeCodeResult:
        """
        Execute `claude -p "<prompt>"` and return the result.
        Blocks until completion or timeout.
        """
        start = time.perf_counter()
        cancelled = False

        cmd = ["claude", "-p", prompt]
        log.info("ClaudeCodeProvider.run_task starting", cmd=cmd[0])

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            with self._lock:
                self._process = proc

            try:
                stdout, stderr = proc.communicate(timeout=self._timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, _ = proc.communicate()
                log.warning("ClaudeCodeProvider timeout", timeout_s=self._timeout_s)
                cancelled = True

            if proc.returncode not in (0, None) and not cancelled:
                log.warning(
                    "claude -p non-zero exit",
                    returncode=proc.returncode,
                    stderr=stderr[:500] if stderr else "",
                )

        except FileNotFoundError:
            log.error("claude CLI not found on PATH")
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ClaudeCodeResult(
                response_text="[Error: claude CLI not found. Install Claude Code first.]",
                thinking_text=None,
                duration_ms=elapsed_ms,
                cancelled=False,
            )
        finally:
            with self._lock:
                self._process = None

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        response_text = (stdout or "").strip()

        return ClaudeCodeResult(
            response_text=response_text,
            thinking_text=None,
            duration_ms=elapsed_ms,
            cancelled=cancelled,
        )

    # ------------------------------------------------------------------
    # Streaming planning mode
    # ------------------------------------------------------------------

    def run_plan(
        self,
        prompt: str,
        timeout_s: Optional[int] = None,
    ) -> Generator[PlanEvent, None, None]:
        """
        Execute `claude -p --verbose "<prompt>"` and yield PlanEvent objects
        as output lines arrive.

        Yields:
            PlanEvent with event_type in:
                "thinking"  — verbose thinking line
                "tool_use"  — tool invocation indicator
                "output"    — regular output content
                "error"     — stderr line
                "done"      — final event, content = full response
                "cancelled" — if cancel() was called
        """
        effective_timeout = timeout_s or self._timeout_s
        cmd = ["claude", "-p", "--verbose", prompt]
        log.info("ClaudeCodeProvider.run_plan starting")

        output_lines: list[str] = []
        cancelled = False

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            with self._lock:
                self._process = proc

        except FileNotFoundError:
            yield PlanEvent(
                event_type="error",
                content="claude CLI not found. Install Claude Code first.",
            )
            return

        # Read stderr in a daemon thread so it doesn't block
        stderr_lines: list[str] = []

        def _read_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stripped = line.rstrip("\n")
                if stripped:
                    stderr_lines.append(stripped)

        t = threading.Thread(target=_read_stderr, daemon=True)
        t.start()

        # Read stdout line-by-line and classify
        deadline = time.time() + effective_timeout
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if time.time() > deadline:
                    proc.terminate()
                    cancelled = True
                    break

                line = raw_line.rstrip("\n")

                # Classify the line
                thinking_match = _THINKING_RE.match(line)
                tool_match = _TOOL_RE.match(line)

                if thinking_match:
                    yield PlanEvent(event_type="thinking", content=thinking_match.group(1))
                elif tool_match:
                    yield PlanEvent(event_type="tool_use", content=tool_match.group(1))
                elif (
                    _DIFF_HEADER_RE.match(line)
                    or _DIFF_ADD_RE.match(line)
                    or _DIFF_DEL_RE.match(line)
                    or _DIFF_HUNK_RE.match(line)
                ):
                    # Diff line — send as file_diff so the UI can color-code it
                    output_lines.append(line)
                    yield PlanEvent(event_type="file_diff", content=line)
                elif line:
                    output_lines.append(line)
                    yield PlanEvent(event_type="output", content=line)

        except Exception as exc:  # noqa: BLE001
            log.error("run_plan stdout read error", exc=str(exc))
            yield PlanEvent(event_type="error", content=str(exc))
            cancelled = True

        finally:
            with self._lock:
                self._process = None

        # Wait for stderr thread
        t.join(timeout=2)

        # Emit any stderr as error events (non-empty)
        for err_line in stderr_lines:
            yield PlanEvent(event_type="error", content=err_line)

        if cancelled:
            yield PlanEvent(event_type="cancelled", content="Session cancelled.")
        else:
            full_response = "\n".join(output_lines)
            yield PlanEvent(event_type="done", content=full_response)
