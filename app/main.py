from fastapi import FastAPI
from rag import generate_answer
from vectorestore import VectorStore
from chunking import chunk_text
from embeddings import embed_text

app = FastAPI()

# Initialize vector store with dimension of embeddings
with open("faq.txt", "r") as f:
	faq_text = f.read()

chunks = chunk_text(faq_text)
embeddings = embed_text(chunks)

vector_store = VectorStore(dimension=len(embeddings[0]))
vector_store.vectors = embeddings

@app.get("/ask")
def ask(question: str):
	answer = generate_answer(question, vector_store)
	return {"answer": answer}
