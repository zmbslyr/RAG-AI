# app/routes/list_files.py
from fastapi import APIRouter
from collections import defaultdict

# Local imports
from app.core.db import collection

router = APIRouter()

@router.get("/list_files")
async def list_files():
    """List all unique files stored in the Chroma vector database, with full metadata."""

    results = collection.get(include=["metadatas"])
    if not results or not results.get("metadatas"):
        return {"message": "No files found in the vector database.", "count": 0}

    all_metadata = results.get("metadatas", [])
    grouped = defaultdict(lambda: {
        "file_id": None,
        "filename": None,
        "pages": set(),
        "total_pages": 0,
        "place": None,
        "sources": set(),
    })

    for meta in all_metadata:
        file_id = meta.get("file_id", "unknown")
        entry = grouped[file_id]

        entry["file_id"] = file_id
        entry["filename"] = meta.get("source", entry["filename"])
        entry["place"] = meta.get("place", entry["place"])
        entry["sources"].add(meta.get("source", "unknown"))

        # Collect individual pages if present
        page = meta.get("page")
        if page is not None:
            entry["pages"].add(page)

        # Track total pages if metadata includes it
        if meta.get("pages"):
            entry["total_pages"] = max(entry["total_pages"], meta["pages"])

    # Convert sets to lists for JSON
    file_summaries = []
    for file in grouped.values():
        file["pages"] = sorted(list(file["pages"]))
        file["sources"] = sorted(list(file["sources"]))
        file_summaries.append(file)

    return {
        "message": "Detailed metadata for all unique files in the vector database.",
        "count": len(file_summaries),
        "files": file_summaries
    }
