from openai import OpenAI

from app.core.config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = settings.require_openai_api_key()
        _client = OpenAI(api_key=api_key)
    return _client


def embed_text(text):
    client = _get_client()
    response = client.embeddings.create(input=text, model="text-embedding-3-small")
    return [e.embedding for e in response.data]


def embed_query(query):
    client = _get_client()
    response = client.embeddings.create(input=query, model="text-embedding-3-small")
    return response.data[0].embedding
