import unicodedata


def normalize_label(value: str) -> str:
    """Compare topic/folder names ignoring case and accents."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.strip())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.casefold()


def labels_match(left: str, right: str) -> bool:
    return normalize_label(left) == normalize_label(right)
