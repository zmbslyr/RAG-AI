from fastapi import APIRouter
from datetime import datetime
from collections import defaultdict

# Local imports
from app.core.db import collection
from app.routes.list_files import list_files

router = APIRouter()

@router.get("/debug_metadata")
async def debug_metadata():
    """
    Inspect metadata stored inside Chroma, with per-file summary stats.
    """
    results = collection.get(include=["metadatas"], limit=None)
    metas = results.get("metadatas", [])

    list_info = await list_files()
    list_files_data = list_info.get("files", [])
    list_index = {f["file_id"]: f for f in list_files_data}

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

        file_info = list_index.get(file_id, {})
        pages = file_info.get("pages", [])
        sources = file_info.get("sources", [])
        listed_total = file_info.get("total_pages", total_pages)

        summaries.append({
            "file_id": file_id,
            "filename": filename,
            "embedding_model": embedding_model,
            "uploaded_at": uploaded_at,
            "place": place,
            "total_pages": total_pages,
            "pages_present": len(pages),
            "pages_list": pages,
            "sources": sources,
            "total_chars": total_chars,
            "avg_chars_per_page": round(avg_chars, 2),
        })

    # --- Print and return ---
    print("\n\n=== DEBUG FILE SUMMARY ===")
    for s in summaries:
        print(
            f"\nFile: {s['filename']}"
            f"\n  File ID: {s['file_id']}"
            f"\n  Pages: {s['total_pages']} (Detected: {s['pages_present']})"
            f"\n  Total chars: {s['total_chars']}"
            f"\n  Avg per page: {s['avg_chars_per_page']}"
            f"\n  Model: {s['embedding_model']}"
            f"\n  Uploaded: {s['uploaded_at']}"
            f"\n  Place: {s['place']}"
            f"\n  Sources: {', '.join(s['sources']) if s['sources'] else '—'}"
        )
    print("==========================\n\n")


    return {
        "timestamp": datetime.now().isoformat(),
        "file_count": len(summaries),
        "files": summaries
    }
