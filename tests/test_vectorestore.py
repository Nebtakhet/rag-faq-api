from pathlib import Path

import pytest

from app.vectorestore import VectorStore


def test_vector_store_add_and_search() -> None:
    store = VectorStore(dimension=3)
    store.add_vector([1.0, 0.0, 0.0], {"text": "alpha"})
    store.add_vector([0.0, 1.0, 0.0], {"text": "beta"})

    results = store.search([1.0, 0.0, 0.0], top_k=1)

    assert len(results) == 1
    assert results[0][0]["text"] == "alpha"


def test_vector_store_rejects_wrong_dimension() -> None:
    store = VectorStore(dimension=3)

    with pytest.raises(ValueError, match="Vector must be of dimension 3"):
        store.add_vector([1.0, 0.0], {"text": "bad"})


def test_vector_store_save_and_load(tmp_path: Path) -> None:
    index_path = tmp_path / "faiss.index"
    metadata_path = tmp_path / "faiss_metadata.json"

    store = VectorStore(dimension=2)
    store.add_vector([0.3, 0.7], {"text": "saved"})
    store.save(index_path, metadata_path)

    loaded = VectorStore.load(index_path, metadata_path)
    results = loaded.search([0.3, 0.7], top_k=1)

    assert loaded.dimension == 2
    assert len(loaded.metadata) == 1
    assert results[0][0]["text"] == "saved"
