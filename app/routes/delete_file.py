# app/routes/delete_file.py
from fastapi import APIRouter, HTTPException
from pathlib import Path
import os
from app.config import collection
from app.routes.list_files import list_files

router = APIRouter()

@router.delete("/delete_file/{file_id}")
async def delete_file(file_id: str):
    """
    Delete a file and its embeddings from the Chroma DB and remove the uploaded file.
    """

    normalized_id = file_id.lower().strip()
    uploads_dir = Path("uploads")

    # Check if file exists in collection
    files_info = await list_files()
    all_files = files_info.get("files", [])
    matching_file = next((f for f in all_files if f.get("file_id") == normalized_id), None)

    if not matching_file:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found in database.")

    # Delete from Chroma
    try:
        collection.delete(where={"file_id": normalized_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting from Chroma: {str(e)}")

    # Delete the uploaded PDF file (if it exists)
    try:
        # Search for any of the sources listed for this file
        sources = matching_file.get("sources", [])
        for src in sources:
            file_path = uploads_dir / src
            if file_path.exists():
                os.remove(file_path)
                print(f"[DEBUG] Deleted file from uploads: {file_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting physical file: {str(e)}")

    # Return confirmation
    updated = await list_files()
    return {
        "message": f"File '{file_id}' deleted successfully from database and uploads.",
        "remaining_files": updated.get("count", 0),
        "files": updated.get("files", [])
    }
