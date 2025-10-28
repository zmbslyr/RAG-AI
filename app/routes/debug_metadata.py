# app/routes/debugmeta_data
from fastapi import APIRouter
from app.config import collection

router = APIRouter()

@router.get("/debug_metadata")
async def debug_metadata():
    """
    Inspect what metadata actually exists inside Chroma.
    Returns a small sample of stored metadata and prints debug info to console.
    """
    results = collection.get(include=["metadatas", "documents"], limit=5)
    metas = results.get("metadatas", [])

    print("\n\n=== METADATA DEBUG ===")
    for i, m in enumerate(metas[:10]):
        print(f"[{i}] {m}")
    print("======================\n\n")

    return metas