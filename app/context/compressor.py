"""
Mission Control — Context Compressor (Phase 3)
================================================
Compresses conversation history to fit within a token budget.

Phase 3 strategy: first-N + last-M retention (no LLM call required).
  - Keep all system messages (they carry instructions)
  - Keep the first `head_count` user+assistant turns (establishes context)
  - Keep the last `tail_count` turns (most recent exchange)
  - Middle turns are replaced with a summary placeholder

Phase 5+: LLM-assisted summarisation of middle turns.

Token estimation: 1 token ≈ 4 characters (rough but dependency-free).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.database.init import get_connection

log = get_logger("context.compressor")

CHARS_PER_TOKEN = 4  # Conservative estimate for English/code content


def estimate_tokens(text: str) -> int:
    """Rough token estimate: characters / 4."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def messages_tokens(messages: list[dict]) -> int:
    """Total token estimate for a message list."""
    return sum(estimate_tokens(m.get("content", "")) for m in messages)


class ContextCompressor:
    """
    Compresses conversation history to fit within a token budget.

    Usage:
        compressor = ContextCompressor()
        result = compressor.compress(
            task_id="01J...",
            messages=[...],
            max_tokens=8000,
        )
        # result["messages"] is the compressed list
        # result["summary"] is the dropped-content summary
    """

    def compress(
        self,
        task_id: str,
        messages: list[dict],
        max_tokens: int = 8000,
        head_turns: int = 2,
        tail_turns: int = 4,
    ) -> dict:
        """
        Compress messages to fit within max_tokens.

        Strategy:
          1. If already within budget → return as-is
          2. Extract system messages (always kept)
          3. Keep first head_turns + last tail_turns non-system turns
          4. Summarise dropped turns into a single assistant message
          5. Persist to context_compressions table

        Returns dict with keys: task_id, original_messages, compressed_tokens,
                                summary, messages.
        """
        original_count = len(messages)
        original_tokens = messages_tokens(messages)

        if original_tokens <= max_tokens:
            return {
                "task_id": task_id,
                "original_messages": original_count,
                "compressed_tokens": original_tokens,
                "summary": "",
                "messages": messages,
            }

        # Partition: system vs conversational
        system_msgs = [m for m in messages if m.get("role") == "system"]
        conv_msgs   = [m for m in messages if m.get("role") != "system"]

        # Keep head and tail of conversational turns
        head = conv_msgs[:head_turns]
        tail = conv_msgs[-tail_turns:] if len(conv_msgs) > head_turns + tail_turns else []
        dropped = conv_msgs[head_turns: len(conv_msgs) - len(tail)]

        # Build summary of dropped content
        if dropped:
            summary_parts = []
            for msg in dropped:
                role = msg.get("role", "?")
                content = msg.get("content", "")
                snippet = content[:200].replace("\n", " ")
                if len(content) > 200:
                    snippet += "..."
                summary_parts.append(f"[{role}]: {snippet}")
            summary = (
                f"[Context compressed — {len(dropped)} messages omitted]\n"
                + "\n".join(summary_parts)
            )
            placeholder = {"role": "assistant", "content": summary}
        else:
            summary = ""
            placeholder = None

        # Reconstruct compressed message list
        compressed: list[dict] = system_msgs + head
        if placeholder:
            compressed.append(placeholder)
        compressed.extend(tail)

        compressed_tokens = messages_tokens(compressed)

        # Persist to DB
        self._persist(task_id, original_tokens, compressed_tokens, summary)

        log.info(
            "Context compressed",
            task_id=task_id,
            original_messages=original_count,
            dropped=len(dropped),
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
        )

        return {
            "task_id": task_id,
            "original_messages": original_count,
            "compressed_tokens": compressed_tokens,
            "summary": summary,
            "messages": compressed,
        }

    def _persist(
        self,
        task_id: str,
        original_tokens: int,
        compressed_tokens: int,
        summary_text: str,
    ) -> None:
        """Store the compression event. Best-effort — failures are logged, not raised."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn = get_connection()
            try:
                # Count prior compressions for this task
                round_num = conn.execute(
                    "SELECT COUNT(*) + 1 AS next FROM context_compressions WHERE task_id = ?",
                    (task_id,),
                ).fetchone()["next"]

                conn.execute(
                    """
                    INSERT INTO context_compressions
                        (id, task_id, compression_round, original_tokens,
                         compressed_tokens, summary_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        task_id,
                        round_num,
                        original_tokens,
                        compressed_tokens,
                        summary_text,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            log.warning("Failed to persist compression event", task_id=task_id, exc=str(exc))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_compressor = ContextCompressor()


def compress_messages(
    task_id: str,
    messages: list[dict],
    max_tokens: int = 8000,
) -> dict:
    """Convenience wrapper for ContextCompressor.compress()."""
    return _compressor.compress(task_id, messages, max_tokens=max_tokens)
