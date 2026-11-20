"""Bound and screen untrusted prompt data. This is defense in depth, not a proof against injection."""
import re
import unicodedata


INSTRUCTION_ATTACK = re.compile(
    r"\b(ignore|disregard|override|forget)\b.{0,50}\b(previous|prior|above|all|system|safety)?\s*(instructions?|rules?|polic(?:y|ies))\b|"
    r"\b(system prompt|developer message|you are now|reveal|disclose|exfiltrate|print)\b.{0,60}\b(patient|private|health|medical|personal|record|data|prompt|secret)\b|"
    r"\b(execute|run|call)\s+(the\s+)?(tool|command|function)\b",
    re.IGNORECASE | re.DOTALL,
)


def safe_untrusted_text(value: str, *, limit: int) -> str | None:
    control_stripped = "".join(
        char for char in value
        if char in "\n\t" or not unicodedata.category(char).startswith("C")
    )
    if INSTRUCTION_ATTACK.search(control_stripped):
        return None
    return control_stripped[:limit]


def safe_untrusted_value(value, *, budget: int = 24000):
    if isinstance(value, str):
        return safe_untrusted_text(value, limit=budget)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        output = []
        for item in value[:20]:
            clean = safe_untrusted_value(item, budget=max(1, budget // 20))
            if clean is not None:
                output.append(clean)
        return output
    if isinstance(value, dict):
        output = {}
        for key, item in list(value.items())[:30]:
            clean_key = safe_untrusted_text(str(key), limit=100)
            if item is None:
                if clean_key is not None:
                    output[clean_key] = None
                continue
            clean_value = safe_untrusted_value(item, budget=max(1, budget // 30))
            if clean_key is not None and clean_value is not None:
                output[clean_key] = clean_value
        return output
    return safe_untrusted_text(str(value), limit=min(budget, 200))
