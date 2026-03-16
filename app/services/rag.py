from app.core.config import settings
from app.services.embeddings import embed_query
from openai import OpenAI

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = settings.require_openai_api_key()
        _client = OpenAI(api_key=api_key)
    return _client


def generate_answer(query, vector_store):
    client = _get_client()
    query_embedding = embed_query(query)
    context = vector_store.search(query_embedding, top_k=5)
    context_text = "\n".join(
        [item[0].get("text", "") for item in context if isinstance(item[0], dict)]
    )
    if not context_text.strip():
        context_text = "No indexed context available."

    prompt = f"""
You are a FAQ assistant. 
Use ONLY the following context to answer the question:
{context_text}

Question: {query}

If you don't know the answer, say "I don't know". Do not use any information outside of the provided context.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini", temperature=0.2, messages=[{"role": "system", "content": prompt}]
    )
    content = response.choices[0].message.content
    return (content or "").strip()
