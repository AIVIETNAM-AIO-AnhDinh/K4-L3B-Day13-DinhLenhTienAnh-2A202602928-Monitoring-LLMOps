import pytest

from app.pii import hash_user_id, scrub_text, summarize_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_email_with_plus_and_digits() -> None:
    out = scrub_text("Send to an.nguyen+lab@gmail.com or 0901234567@example.com")
    assert "@" not in out
    assert "0901234567" not in out
    assert out.count("[REDACTED_EMAIL]") == 2


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
        "+84901234567",
        "84901234567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


@pytest.mark.parametrize("cccd", ["001203004567", "079095012345"])
def test_scrub_cccd(cccd: str) -> None:
    out = scrub_text(f"CCCD cua toi la {cccd}.")
    assert cccd not in out
    assert out == "CCCD cua toi la [REDACTED_CCCD]."


def test_cccd_is_not_mislabelled_as_phone() -> None:
    # A 12-digit CCCD starting with 0 must not be partly eaten by phone_vn.
    assert scrub_text("id=012345678901") == "id=[REDACTED_CCCD]"


@pytest.mark.parametrize(
    "card",
    [
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "4111111111111111",
        "3782 822463 10005",  # Amex, 15 digits
    ],
)
def test_scrub_credit_card(card: str) -> None:
    out = scrub_text(f"Pay with {card} please")
    assert out == "Pay with [REDACTED_CREDIT_CARD] please"


def test_scrub_passport() -> None:
    out = scrub_text("Passport C1234567 expires soon")
    assert out == "Passport [REDACTED_PASSPORT] expires soon"


def test_scrub_multiple_pii_types_in_one_message() -> None:
    out = scrub_text(
        "Email a@b.vn, phone 0987654321, CCCD 001203004567, card 4111 1111 1111 1111"
    )
    for token in ("a@b.vn", "0987654321", "001203004567", "4111 1111 1111 1111"):
        assert token not in out
    for label in ("EMAIL", "PHONE_VN", "CCCD", "CREDIT_CARD"):
        assert f"[REDACTED_{label}]" in out


@pytest.mark.parametrize(
    "safe",
    [
        "req-1a2b3c4d",
        "2026-09-30T02:20:36.852456Z",
        "latency 1874 ms, 144 tokens, cost 0.002268",
        "claude-sonnet-4-5",
        "How do I debug tail latency?",
    ],
)
def test_non_pii_is_left_alone(safe: str) -> None:
    assert scrub_text(safe) == safe


def test_summarize_text_scrubs_and_truncates() -> None:
    out = summarize_text("My phone is 0987654321\n" + "x" * 200, max_len=40)
    assert "0987654321" not in out
    assert "\n" not in out
    assert out.endswith("...")
    assert len(out) == 43


def test_hash_user_id_is_stable() -> None:
    assert hash_user_id("u01") == hash_user_id("u01")
    assert hash_user_id("u01") != hash_user_id("u02")
    assert len(hash_user_id("u01")) == 12
