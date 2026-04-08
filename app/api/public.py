from fastapi import APIRouter

from app import main

router = APIRouter()

router.add_api_route("/ask", main.ask, methods=["GET"])
