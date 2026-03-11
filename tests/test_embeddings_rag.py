from types import SimpleNamespace

import pytest

from app import embeddings, rag


def test_embed_text_returns_embedding_list(monkeypatch) -> None:
    class DummyEmbeddings:
        @staticmethod
        def create(*, input, model):
            assert input == ["a", "b"]
            assert model == "text-embedding-3-small"
            return SimpleNamespace(
                data=[
                    SimpleNamespace(embedding=[0.1, 0.2]),
                    SimpleNamespace(embedding=[0.3, 0.4]),
                ]
            )

    monkeypatch.setattr(
        embeddings,
        "_get_client",
        lambda: SimpleNamespace(embeddings=DummyEmbeddings()),
    )

    assert embeddings.embed_text(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_query_returns_first_embedding(monkeypatch) -> None:
    class DummyEmbeddings:
        @staticmethod
        def create(*, input, model):
            assert input == "question"
            assert model == "text-embedding-3-small"
            return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 2.0, 3.0])])

    monkeypatch.setattr(
        embeddings,
        "_get_client",
        lambda: SimpleNamespace(embeddings=DummyEmbeddings()),
    )

    assert embeddings.embed_query("question") == [1.0, 2.0, 3.0]


def test_generate_answer_uses_context_and_strips_output(monkeypatch) -> None:
    class DummyStore:
        @staticmethod
        def search(_query_embedding, top_k=5):
            assert top_k == 5
            return [({"text": "hello"}, 0.0), ({"text": "world"}, 0.1)]

    class DummyCompletions:
        @staticmethod
        def create(*, model, temperature, messages):
            assert model == "gpt-4o-mini"
            assert temperature == 0.2
            prompt = messages[0]["content"]
            assert "hello\nworld" in prompt
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="  final answer  "))]
            )

    dummy_client = SimpleNamespace(chat=SimpleNamespace(completions=DummyCompletions()))

    monkeypatch.setattr(rag, "embed_query", lambda _q: [0.1, 0.2])
    monkeypatch.setattr(rag, "_get_client", lambda: dummy_client)

    assert rag.generate_answer("What is this?", DummyStore()) == "final answer"


def test_generate_answer_handles_empty_context_and_none_content(monkeypatch) -> None:
    class DummyStore:
        @staticmethod
        def search(_query_embedding, top_k=5):
            return [("not-a-dict", 0.2)]

    class DummyCompletions:
        @staticmethod
        def create(*, model, temperature, messages):
            prompt = messages[0]["content"]
            assert "No indexed context available." in prompt
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])

    dummy_client = SimpleNamespace(chat=SimpleNamespace(completions=DummyCompletions()))

    monkeypatch.setattr(rag, "embed_query", lambda _q: [0.5, 0.5])
    monkeypatch.setattr(rag, "_get_client", lambda: dummy_client)

    assert rag.generate_answer("Anything?", DummyStore()) == ""


def test_embeddings_get_client_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(embeddings, "_client", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        embeddings._get_client()


def test_embeddings_get_client_creates_once(monkeypatch) -> None:
    dummy_client = object()
    monkeypatch.setattr(embeddings, "_client", None)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr(embeddings, "OpenAI", lambda api_key: dummy_client)

    assert embeddings._get_client() is dummy_client
    assert embeddings._get_client() is dummy_client


def test_rag_get_client_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(rag, "_client", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        rag._get_client()
