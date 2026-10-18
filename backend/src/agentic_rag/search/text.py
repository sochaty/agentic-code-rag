"""Tokenisation that understands code identifiers."""

import re

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def tokenize(text: str) -> list[str]:
    """`full_dispatch_request` -> full_dispatch_request, full, dispatch, request.

    Keeping the whole identifier lets exact names score highest; the parts let
    "dispatch request" match it too.
    """
    tokens: list[str] = []
    for word in _WORD.findall(text):
        lowered = word.lower()
        tokens.append(lowered)
        parts = [p.lower() for piece in word.split("_") for p in _CAMEL.findall(piece)]
        if len(parts) > 1:
            tokens.extend(parts)
    return tokens
