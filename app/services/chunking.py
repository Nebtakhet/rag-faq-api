def chunk_text(text, chunk_size=1000, overlap=200):
    # """
    # Splits the input text into chunks of specified size with overlap.

    # Args:
    # text (str): The input text to be chunked.
    # chunk_size (int): The size of each chunk. Default is 1000 characters.
    # overlap (int): The number of overlapping characters between chunks. Default is 200 characters.
    #
    # Returns:
    # List[str]: A list of text chunks.
    # """#
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
