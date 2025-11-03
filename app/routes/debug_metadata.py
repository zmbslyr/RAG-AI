from fastapi import APIRouter
from app.config import collection
from datetime import datetime
from collections import defaultdict

router = APIRouter()

@router.get("/debug_metadata")
async def debug_metadata():
    """
    Inspect metadata stored inside Chroma, with per-file summary stats.
    """
    results = collection.get(include=["metadatas"], limit=None)
    metas = results.get("metadatas", [])

    if not metas:
        return {"status": "empty", "message": "No metadata found in collection"}

    # --- Group by file_id ---
    grouped = defaultdict(list)
    for m in metas:
        grouped[m.get("file_id", "unknown")].append(m)

    # --- Build summaries ---
    summaries = []
    for file_id, records in grouped.items():
        first = records[0]
        filename = first.get("source", "unknown")
        embedding_model = first.get("embedding_model", "unknown")
        uploaded_at = first.get("uploaded_at", "N/A")
        total_pages = len(records)
        total_chars = sum(int(r.get("char_count", 0)) for r in records)
        avg_chars = total_chars / total_pages if total_pages else 0
        place = first.get("place", "unknown")


        summaries.append({
            "file_id": file_id,
            "filename": filename,
            "embedding_model": embedding_model,
            "uploaded_at": uploaded_at,
            "total_pages": total_pages,
            "total_chars": total_chars,
            "avg_chars_per_page": round(avg_chars, 2),
            "place": place
        })

    # --- Print and return ---
    print("\n\n=== METADATA DEBUG SUMMARY ===")
    for s in summaries:
        print(
            f"\nFile: {s['filename']}\n"
            f"  Pages: {s['total_pages']}\n"
            f"  Total chars: {s['total_chars']}\n"
            f"  Avg per page: {s['avg_chars_per_page']}\n"
            f"  Model: {s['embedding_model']}\n"
            f"  Uploaded: {s['uploaded_at']}\n"
            f"  Place: {s['place']}\n"
        )
    print("===============================\n\n")

    return {
        "timestamp": datetime.now().isoformat(),
        "file_count": len(summaries),
        "files": summaries
    }
