def normalize_phone(phone: str) -> str:
    """Normalize WhatsApp phone numbers, especially BR mobile without the 9 digit."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return phone

    # Brazil: Meta may send 12 digits (55 + DDD + 8 digits) instead of 13 (with mobile 9).
    if digits.startswith("55") and len(digits) == 12:
        return f"{digits[:4]}9{digits[4:]}"

    return digits
