import faiss
import numpy as np
import json
from pathlib import Path


class VectorStore:
    def __init__(self, dimension):
        self.dimension = dimension
        self.index = faiss.IndexFlatL2(dimension)
        self.metadata = []

    def add_vector(self, vector, meta):
        if len(vector) != self.dimension:
            raise ValueError(f"Vector must be of dimension {self.dimension}")

        self.index.add(np.array([vector], dtype=np.float32))
        self.metadata.append(meta)

    def search(self, query_vector, top_k=5):
        if len(query_vector) != self.dimension:
            raise ValueError(f"Query vector must be of dimension {self.dimension}")

        distances, indices = self.index.search(np.array([query_vector], dtype=np.float32), top_k)
        results = []
        for i, idx in enumerate(indices[0]):
            if idx >= 0 and idx < len(self.metadata):
                results.append((self.metadata[idx], float(distances[0][i])))
        return results

    def save(self, index_path, metadata_path):
        index_file = Path(index_path)
        metadata_file = Path(metadata_path)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        metadata_file.parent.mkdir(parents=True, exist_ok=True)

        faiss.write_index(self.index, str(index_file))
        with metadata_file.open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "dimension": self.dimension,
                    "metadata": self.metadata,
                },
                file,
                ensure_ascii=False,
            )

    @classmethod
    def load(cls, index_path, metadata_path):
        index_file = Path(index_path)
        metadata_file = Path(metadata_path)

        index = faiss.read_index(str(index_file))
        with metadata_file.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        store = cls(dimension=int(payload.get("dimension", index.d)))
        store.index = index
        store.metadata = payload.get("metadata", [])
        return store
