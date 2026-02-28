"""
Mission Control — Text Chunker
================================
Splits text into overlapping word-based chunks.
Word count used as proxy for token count (avoids tokenizer dependency).

Defaults: 512 words per chunk, 64-word overlap.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextChunk:
    index: int
    text: str
    word_count: int


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[TextChunk]:
    """
    Split text into overlapping chunks by word count.

    Args:
        text       -- input text (any language)
        chunk_size -- target words per chunk
        overlap    -- words shared between adjacent chunks

    Returns list of TextChunk, empty list if text is blank.
    """
    if not text or not text.strip():
        return []

    words = text.split()
    if not words:
        return []

    chunks: list[TextChunk] = []
    start = 0
    index = 0
    step = max(1, chunk_size - overlap)

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_words = words[start:end]
        chunks.append(TextChunk(
            index=index,
            text=" ".join(chunk_words),
            word_count=len(chunk_words),
        ))
        if end >= len(words):
            break
        start += step
        index += 1

    return chunks


def chunk_code_file(
    text: str,
    file_path: str = "",
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[TextChunk]:
    """
    Chunk a code file. Tries to split on class/function boundaries first.
    Falls back to fixed-size chunking if no boundaries found.
    """
    import re

    # Try to find class/function/def boundaries
    boundary_pattern = re.compile(
        r"^(class |def |async def |function |export function |fn |pub fn )",
        re.MULTILINE,
    )
    matches = list(boundary_pattern.finditer(text))

    if len(matches) < 2:
        # No useful boundaries — use fixed-size
        return chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    # Split into logical sections at boundaries
    sections: list[str] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)

    # Merge small sections and split large ones
    chunks: list[TextChunk] = []
    index = 0
    buffer = ""

    for section in sections:
        candidate = (buffer + "\n\n" + section).strip() if buffer else section
        if len(candidate.split()) <= chunk_size:
            buffer = candidate
        else:
            if buffer:
                chunks.append(TextChunk(index=index, text=buffer, word_count=len(buffer.split())))
                index += 1
                buffer = ""
            # Section itself may be large — chunk it
            for sub in chunk_text(section, chunk_size=chunk_size, overlap=overlap):
                chunks.append(TextChunk(index=index, text=sub.text, word_count=sub.word_count))
                index += 1

    if buffer:
        chunks.append(TextChunk(index=index, text=buffer, word_count=len(buffer.split())))

    return chunks if chunks else chunk_text(text, chunk_size=chunk_size, overlap=overlap)
