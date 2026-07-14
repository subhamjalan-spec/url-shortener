import pytest
from app.base62 import encode, decode


def test_zero_encodes_to_first_char():
    assert encode(0) == "0"
    assert decode("0") == 0


def test_small_numbers_round_trip():
    for n in range(0, 1000):
        assert decode(encode(n)) == n


def test_known_encodings():
    # Manually verified against the base62 definition: 61 is the last
    # single-digit value ('z'), 62 is the first two-digit value ('10').
    assert encode(61) == "z"
    assert encode(62) == "10"
    assert decode("z") == 61
    assert decode("10") == 62


def test_large_id_round_trips():
    big = 999_999_999_999
    assert decode(encode(big)) == big


def test_encoding_is_deterministic_and_unique_per_id():
    # The core correctness property this whole approach relies on:
    # different IDs must never produce the same code.
    seen = set()
    for n in range(0, 5000):
        code = encode(n)
        assert code not in seen, f"collision: id {n} produced a code already seen"
        seen.add(code)


def test_negative_id_rejected():
    with pytest.raises(ValueError):
        encode(-1)


def test_invalid_character_rejected():
    with pytest.raises(ValueError):
        decode("abc!def")
