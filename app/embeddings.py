from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def embed_text(text):
    response = client.embeddings.create(input=text, model="text-embedding-3-small")
    return [e.embedding for e in response.data]


def embed_query(query):
    response = client.embeddings.create(input=query, model="text-embedding-3-small")
    return response.data[0].embedding
