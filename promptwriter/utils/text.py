import os
import re
from datetime import datetime


def truncate_filename(filepath, max_length=40):
    filename = os.path.basename(filepath)
    if max_length <= 0:
        return ""
    if len(filename) <= max_length:
        return filename

    stem, extension = os.path.splitext(filename)
    available_stem_length = max_length - len(extension) - 3
    if available_stem_length <= 0:
        return f"...{filename[-max(0, max_length - 3):]}"
    prefix_length = (available_stem_length + 1) // 2
    suffix_length = available_stem_length - prefix_length
    suffix = stem[-suffix_length:] if suffix_length else ""
    return f"{stem[:prefix_length]}...{suffix}{extension}"


def format_as_single_line_prompts(text):
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = normalized_text.split("\n\n")
    cleaned_blocks = [
        " ".join(block.split())
        for block in blocks
        if block.strip()
    ]
    return "\n".join(cleaned_blocks)


def format_history_timestamp(timestamp):
    if not isinstance(timestamp, str) or not timestamp:
        return "Unknown date"
    try:
        return datetime.fromisoformat(timestamp).strftime("%m.%d. %H:%M")
    except ValueError:
        return timestamp[:16]


def history_idea_snippet(rough_idea, max_length=58):
    snippet = re.sub(r"\s+", " ", rough_idea or "").strip()
    snippet = re.sub(
        r"^Generate\s+\d+\s+prompts?\.\s*", "", snippet, flags=re.IGNORECASE
    )
    if re.match(r"^Each prompt\b", snippet, flags=re.IGNORECASE):
        topic_match = re.search(r"\bTopic\s*:\s*", snippet, flags=re.IGNORECASE)
        if topic_match:
            snippet = snippet[topic_match.end() :]
        else:
            snippet = re.sub(
                r"^Each prompt\b[^.!?\n]*[.!?]\s*",
                "",
                snippet,
                count=1,
                flags=re.IGNORECASE,
            )
    snippet = re.sub(r"^Topic\s*:\s*", "", snippet, flags=re.IGNORECASE).strip()
    if len(snippet) > max_length:
        return f"{snippet[: max_length - 3].rstrip()}..."
    return snippet


def is_numeric_result(value):
    return bool(
        isinstance(value, str)
        and re.fullmatch(
            r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
            value.strip(),
        )
    )


_THINK_BLOCK_PATTERNS = (
    re.compile(r"<think>.*?</think>", flags=re.IGNORECASE | re.DOTALL),
    re.compile(r"<thinking>.*?</thinking>", flags=re.IGNORECASE | re.DOTALL),
    re.compile(r"<\|think\|>.*?<\|/think\|>", flags=re.IGNORECASE | re.DOTALL),
)

_UNCLOSED_THINK_PATTERNS = (
    re.compile(r"<think>.*\Z", flags=re.IGNORECASE | re.DOTALL),
    re.compile(r"<thinking>.*\Z", flags=re.IGNORECASE | re.DOTALL),
    re.compile(r"<\|think\|>.*\Z", flags=re.IGNORECASE | re.DOTALL),
)


def strip_think_tags(text):
    if not isinstance(text, str):
        return text
    for pattern in _THINK_BLOCK_PATTERNS:
        text = pattern.sub("", text)
    for pattern in _UNCLOSED_THINK_PATTERNS:
        text = pattern.sub("", text)
    return text.strip()

