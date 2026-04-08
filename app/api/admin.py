from fastapi import APIRouter

from app import main

router = APIRouter()

router.add_api_route("/admin/documents", main.upload_documents, methods=["POST"])
router.add_api_route("/admin/reindex", main.reindex_documents, methods=["POST"])
router.add_api_route("/admin/documents", main.list_documents, methods=["GET"])
