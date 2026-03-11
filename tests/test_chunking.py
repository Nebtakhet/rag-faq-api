import pytest

from app.chunking import chunk_text


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
