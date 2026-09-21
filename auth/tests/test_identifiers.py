import pytest

from app.identifiers import classify_identifier, is_valid_username, normalize_phone


@pytest.mark.parametrize("raw,expected", [
    ("70123456", "+22670123456"),
    ("70 12 34 56", "+22670123456"),
    ("22670123456", "+22670123456"),
    ("+226 70 12 34 56", "+22670123456"),
    ("0022670123456", "+22670123456"),
    ("+33612345678", "+33612345678"),
    ("1234567", None),
    ("abcdefgh", None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_username_needs_a_letter():
    assert is_valid_username("agent_kaya")
    assert not is_valid_username("12345678")
    assert not is_valid_username("ab")


def test_classify_identifier():
    assert classify_identifier("Test@Anam.BF") == ("email", "test@anam.bf")
    assert classify_identifier("70123456") == ("phone", "+22670123456")
    assert classify_identifier("Agent_Kaya") == ("username", "agent_kaya")
    assert classify_identifier("!!") is None
