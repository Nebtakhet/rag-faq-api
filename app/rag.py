from embeddings import embed_query
from vectorestore import VectorStore
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_answer(query, vector_store):
	query_embedding = embed_query(query)
	context = vector_store.search(query_embedding, top_k=5)
	context_text = "\n".join([meta for meta, _ in context])

	prompt = f"""
You are a FAQ assistant. 
Use ONLY the following context to answer the question:
{context_text}

Question: {query}

If you don't know the answer, say "I don't know". Do not use any information outside of the provided context.
"""
	
	response = client.chat.completions.create(
		model="gpt-4o-mini",
		temperature=0.2,
		messages=[{"role": "system", "content": prompt}]
	)
	return response.choices[0].message.content.strip()
