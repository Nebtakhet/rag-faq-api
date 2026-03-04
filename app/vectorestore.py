import faiss
import numpy as np

class VectorStore:
	def __init__(self, dimension):
		self.dimension = dimension
		self.index = faiss.IndexFlatL2(dimension)
		self.vectors = []
		self.metadata = []

	def add_vector(self, vector, meta):
		if len(vector) != self.dimension:
			raise ValueError(f"Vector must be of dimension {self.dimension}")
		
		self.index.add(np.array([vector], dtype=np.float32))
		self.vectors.append(vector)
		self.metadata.append(meta)

	def search(self, query_vector, top_k=5):
		if len(query_vector) != self.dimension:
			raise ValueError(f"Query vector must be of dimension {self.dimension}")
		
		distances, indices = self.index.search(np.array([query_vector], dtype=np.float32), top_k)
		results = []
		for idx in indices[0]:
			if idx < len(self.metadata):
				results.append((self.metadata[idx], self.vectors[idx]))
		return results
