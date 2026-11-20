import re


def bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def jaccard(a: str, b: str) -> float:
    left, right = bigrams(a), bigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
