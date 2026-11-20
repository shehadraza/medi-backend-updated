import re


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("Document text must be a string.")
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[\t\f\v ]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def chunk_text(text: str, *, chunk_size: int = 1200, overlap: int = 180) -> list[str]:
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0.")
    normalized = normalize_text(text)
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        part = normalized[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return chunks
