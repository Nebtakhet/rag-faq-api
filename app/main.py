from pathlib import Path
from typing import Annotated
import os

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile

from app.chunking import chunk_text
from app.embeddings import embed_text
from app.rag import generate_answer
from app.vectorestore import VectorStore

app = FastAPI()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INDEX_PATH = DATA_DIR / "faiss.index"
METADATA_PATH = DATA_DIR / "faiss_metadata.json"
ALLOWED_EXTENSIONS = {".txt", ".md"}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "5242880"))
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

vector_store = None


def require_admin(x_admin_key: Annotated[str | None, Header()] = None) -> None:
	if not ADMIN_API_KEY:
		raise HTTPException(status_code=500, detail="ADMIN_API_KEY is not configured")
	if x_admin_key != ADMIN_API_KEY:
		raise HTTPException(status_code=403, detail="Invalid admin key")


def _load_existing_index() -> None:
	global vector_store
	if INDEX_PATH.exists() and METADATA_PATH.exists():
		vector_store = VectorStore.load(INDEX_PATH, METADATA_PATH)


def _read_text_file(file_path: Path) -> str:
	return file_path.read_text(encoding="utf-8", errors="ignore")


def _rebuild_index_from_data() -> dict:
	global vector_store
	DATA_DIR.mkdir(parents=True, exist_ok=True)
	files = sorted(
		[
			path
			for path in DATA_DIR.iterdir()
			if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
		]
	)

	if not files:
		vector_store = None
		if INDEX_PATH.exists():
			INDEX_PATH.unlink()
		if METADATA_PATH.exists():
			METADATA_PATH.unlink()
		return {"files": 0, "chunks": 0}

	total_chunks = 0
	store = None

	for source_file in files:
		text = _read_text_file(source_file)
		if not text.strip():
			continue

		chunks = chunk_text(text)
		if not chunks:
			continue

		embeddings = embed_text(chunks)
		if not embeddings:
			continue

		if store is None:
			store = VectorStore(dimension=len(embeddings[0]))

		for chunk_id, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
			store.add_vector(
				embedding,
				{
					"source": source_file.name,
					"chunk_id": chunk_id,
					"text": chunk,
				},
			)
			total_chunks += 1

	if store is None:
		vector_store = None
		return {"files": len(files), "chunks": 0}

	store.save(INDEX_PATH, METADATA_PATH)
	vector_store = store
	return {"files": len(files), "chunks": total_chunks}


@app.on_event("startup")
def on_startup() -> None:
	DATA_DIR.mkdir(parents=True, exist_ok=True)
	_load_existing_index()


@app.get("/ask")
def ask(question: str):
	if vector_store is None:
		raise HTTPException(status_code=400, detail="No indexed documents. Upload documents first.")
	answer = generate_answer(question, vector_store)
	return {"answer": answer}


@app.post("/admin/documents")
async def upload_documents(
	files: list[UploadFile] = File(...),
	_: None = Depends(require_admin),
):
	DATA_DIR.mkdir(parents=True, exist_ok=True)
	uploaded = []

	for upload in files:
		filename = Path(upload.filename or "").name
		extension = Path(filename).suffix.lower()
		if extension not in ALLOWED_EXTENSIONS:
			raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")

		payload = await upload.read()
		if len(payload) > MAX_UPLOAD_BYTES:
			raise HTTPException(status_code=400, detail=f"File too large: {filename}")

		target = DATA_DIR / filename
		target.write_bytes(payload)
		uploaded.append(filename)

	summary = _rebuild_index_from_data()
	return {
		"uploaded": uploaded,
		"reindexed": summary,
	}


@app.post("/admin/reindex")
def reindex_documents(_: None = Depends(require_admin)):
	summary = _rebuild_index_from_data()
	return {"reindexed": summary}


@app.get("/admin/documents")
def list_documents(_: None = Depends(require_admin)):
	DATA_DIR.mkdir(parents=True, exist_ok=True)
	files = sorted(
		[
			path.name
			for path in DATA_DIR.iterdir()
			if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
		]
	)

	indexed_chunks = 0
	if vector_store is not None:
		indexed_chunks = len(vector_store.metadata)

	return {
		"documents": files,
		"indexed_chunks": indexed_chunks,
	}
