# app/routes/list_files.py
from fastapi import APIRouter
from app.config import collection

router = APIRouter()

# --- Endpoint to access list_files functions ---
@router.get("/list_files")
async def list_files():
    """List all unique files stored in the Chroma vector database."""
    results = collection.get()

    if not results or not results.get("metadatas"):
        return {"message": "No files found in the vector database.", "count": 0}

    all_metadata = results.get("metadatas", [])
    unique_files = {}
    for meta in all_metadata:
        file_id = meta.get("file_id", "unknown")
        if file_id not in unique_files:
            unique_files[file_id] = {
                "filename": meta.get("source", "unknown"),
                "pages": meta.get("pages", "unknown"),
                "place": meta.get("place", "unknown")
            }

    return {
        "message": "Unique files currently stored in the vector database.",
        "count": len(unique_files),
        "files": list(unique_files.values())
    }
