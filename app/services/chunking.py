import re


def chunk_text(text, chunk_size=1000, overlap=200):
    # Validate parameters
    # Splits the input text into chunks of specified size with overlap.

    # Args:
    # text (str): The input text to be chunked.
    # chunk_size (int): The size of each chunk. Default is 1000 characters.
    # overlap (int): The number of overlapping characters between chunks. Default is 200 characters.
    #
    # Returns:
    # List[str]: A list of text chunks.
    #
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start += chunk_size - overlap

    return chunks


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00ad", "")

    # Merge words split by line-wrap hyphenation from PDFs.
    normalized = re.sub(r"(?<=\w)-\n(?=\w)", "", normalized)

    lines = [line.strip() for line in normalized.split("\n")]
    normalized = "\n".join(lines)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def is_informative_chunk(text: str, min_alpha_ratio: float = 0.15) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    alpha_count = sum(char.isalpha() for char in stripped)
    return (alpha_count / max(1, len(stripped))) >= min_alpha_ratio


def prepare_chunks(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
    min_alpha_ratio: float = 0.15,
) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    raw_chunks = chunk_text(normalized, chunk_size=chunk_size, overlap=overlap)
    unique_chunks: list[str] = []
    seen = set()

    for raw in raw_chunks:
        cleaned = raw.strip()
        if not cleaned:
            continue
        if not is_informative_chunk(cleaned, min_alpha_ratio=min_alpha_ratio):
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        unique_chunks.append(cleaned)

    if unique_chunks:
        return unique_chunks

    # Keep at least one chunk for tiny-but-valid docs.
    fallback = normalized[:chunk_size].strip()
    return [fallback] if fallback else []
