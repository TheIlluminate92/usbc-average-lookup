"""Keep useful response data without retaining credentials, including nested data."""

import re

_SECRET = re.compile(r"authorization|cookie|token|password|passwd|secret|credential|api.?key", re.I)
_BEARER = re.compile(r"\bBearer\s+[^\s\"'<>]+", re.I)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def sanitize(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): sanitize(child)
            for key, child in value.items()
            if not _SECRET.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(child) for child in value]
    if isinstance(value, str):
        return _JWT.sub("[redacted]", _BEARER.sub("Bearer [redacted]", value))
    return value
