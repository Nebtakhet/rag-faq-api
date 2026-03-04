# rag-faq-api
Minimal RAG based FAQ API, built with FastAPI, OpenAI embeddings and FAISS

# GenAI FAQ Chat (RAG Prototype)

A clean, minimal Retrieval-Augmented Generation (RAG) system for question answering over custom documents.

This project builds a production-style RAG pipeline from scratch using:

- OpenAI embeddings
- FAISS vector store
- FastAPI backend
- Prompt-controlled LLM generation

No frameworks. No LangChain.

The system:

1. Loads local documents
2. Chunks text with overlap
3. Generates embeddings
4. Stores vectors in FAISS
5. Retrieves relevant chunks via similarity search
6. Injects context into a controled prompt
7. Returns grounded answers

This repository will focus on architecture clarity and cost awareness.