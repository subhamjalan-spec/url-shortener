"""Base62 encoding for short codes.

Why base62 instead of random-string-plus-collision-check: every link gets
an auto-incrementing integer primary key from Postgres, which is already
guaranteed unique by the database. Encoding that integer into base62
(a-z, A-Z, 0-9 -- 62 characters) is a pure bijection: every ID maps to
exactly one code and back, so collisions are structurally impossible,
not just checked for and retried. This is the deliberate "hard part" of
this project, tested here in complete isolation before any DB or API
code touches it.
"""

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)


def encode(n: int) -> str:
    """Encodes a non-negative integer ID into a base62 short code."""
    if n < 0:
        raise ValueError("cannot encode a negative id")
    if n == 0:
        return ALPHABET[0]
    digits = []
    while n > 0:
        n, remainder = divmod(n, BASE)
        digits.append(ALPHABET[remainder])
    return "".join(reversed(digits))


def decode(code: str) -> int:
    """Decodes a base62 short code back into its integer ID."""
    n = 0
    for char in code:
        idx = ALPHABET.find(char)
        if idx == -1:
            raise ValueError(f"invalid base62 character: {char!r}")
        n = n * BASE + idx
    return n
