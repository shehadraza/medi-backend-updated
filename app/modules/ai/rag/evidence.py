"""Conservative surface-level evidence disagreement flags.

These flags identify text that appears to express opposite polarity about
overlapping terms. They are review cues, not clinical conflict determinations.
"""
import re


_WORD = re.compile(r"[^\W_]+", flags=re.UNICODE)
_STOP = {
    "the", "and", "or", "is", "are", "was", "were", "to", "of", "for", "in",
    "on", "a", "an", "with", "may", "can", "be", "by", "this", "that",
}
_POLARITY = (
    (re.compile(r"\bnot recommended\b|\bnot advised\b|\bshould not use\b|\bcontraindicated\b"), "negative"),
    (re.compile(r"\brecommended\b|\badvised\b|\bshould use\b"), "positive"),
    (re.compile(r"\bineffective\b|\bdoes not reduce\b|\bdoes not prevent\b"), "negative"),
    (re.compile(r"\beffective\b|\breduces\b|\bprevents\b"), "positive"),
    (re.compile(r"\bdoes not increase\b|\bno increased risk\b"), "negative"),
    (re.compile(r"\bincreases risk\b|\bincreased risk\b"), "positive"),
)


def potential_disagreement_pairs(texts: list[str]) -> set[tuple[int, int]]:
    """Return passage-index pairs with overlapping terms and opposite wording."""
    annotations = []
    for text in texts:
        normalized = text.casefold()
        polarity = None
        for pattern, label in _POLARITY:
            if pattern.search(normalized):
                polarity = label
                break
        terms = {term for term in _WORD.findall(normalized) if term not in _STOP}
        annotations.append((polarity, terms))
    result: set[tuple[int, int]] = set()
    for left in range(len(annotations)):
        left_polarity, left_terms = annotations[left]
        if left_polarity is None:
            continue
        for right in range(left + 1, len(annotations)):
            right_polarity, right_terms = annotations[right]
            overlap = left_terms & right_terms
            union = left_terms | right_terms
            if right_polarity and right_polarity != left_polarity and union and len(overlap) / len(union) >= 0.35:
                result.add((left, right))
    return result
