"""The project's style rule, enforced on model output: no en or em dashes in anything a reader sees."""

import re

DASH_RANGE = re.compile(r"(\d)\s*[–—]\s*(\d)")


def no_dashes(text: str) -> str:
    text = DASH_RANGE.sub(r"\1 to \2", text or "")
    return re.sub(r"\s*[–—]\s*", ", ", text)
