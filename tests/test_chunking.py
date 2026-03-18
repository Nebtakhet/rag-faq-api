import pytest

from app.services.chunking import chunk_text, is_informative_chunk, normalize_text, prepare_chunks
from app.services import chunking as chunking_module


def test_chunk_text_splits_with_overlap() -> None:
    text = "abcdefghijklmnopqrstuvwxyz"

    chunks = chunk_text(text, chunk_size=10, overlap=2)

    assert chunks == ["abcdefghij", "ijklmnopqr", "qrstuvwxyz", "yz"]


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "expected_message"),
    [
        (0, 0, "chunk_size must be greater than 0"),
        (-1, 0, "chunk_size must be greater than 0"),
        (10, -1, "overlap must be non-negative"),
    ],
)
def test_chunk_text_rejects_invalid_arguments(
    chunk_size: int, overlap: int, expected_message: str
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        chunk_text("hello world", chunk_size=chunk_size, overlap=overlap)


def test_normalize_text_cleans_pdf_like_wrapping() -> None:
    raw = "hyphen-\nated  word\r\n\r\n\r\nsecond\tline"

    assert normalize_text(raw) == "hyphenated word\n\nsecond line"


def test_is_informative_chunk_filters_noise() -> None:
    assert is_informative_chunk("This is text.") is True
    assert is_informative_chunk("$$$$$ 12345 -----", min_alpha_ratio=0.2) is False


def test_prepare_chunks_deduplicates_and_filters_non_informative() -> None:
    text = "Alpha beta gamma.\n\n$$$$$ 12345 -----\n\nAlpha beta gamma."

    chunks = prepare_chunks(text, chunk_size=100, overlap=0, min_alpha_ratio=0.2)

    assert chunks == ["Alpha beta gamma.\n\n$$$$$ 12345 -----\n\nAlpha beta gamma."]


def test_prepare_chunks_keeps_fallback_for_tiny_valid_text() -> None:
    chunks = prepare_chunks("tiny", chunk_size=100, overlap=0, min_alpha_ratio=0.8)

    assert chunks == ["tiny"]


def test_prepare_chunks_filters_duplicates_and_noise(monkeypatch) -> None:
    monkeypatch.setattr(
        chunking_module,
        "chunk_text",
        lambda *_args, **_kwargs: ["@@@@", "Alpha chunk", "Alpha chunk", "   "],
    )

    chunks = prepare_chunks("ignored", min_alpha_ratio=0.2)

    assert chunks == ["Alpha chunk"]
