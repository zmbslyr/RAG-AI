from fastapi import APIRouter, UploadFile, Depends
from pathlib import Path
import shutil
import os
from datetime import datetime

# Local imports
from app.core.settings import settings
from app.services.llm_service import llm_client
from app.services.files_service import extract_text
from app.core import db
from app.routes.auth import require_admin

# Optional RTF import
try:
    import striprtf
except ImportError:
    striprtf = None

router = APIRouter()

# --- Helpers ---
def get_next_available_place():
    """Find the lowest available 'place' number among existing files."""
    results = db.collection.get(include=["metadatas"])
    all_metadata = results.get("metadatas", []) if results else []

    existing_places = set()
    for m in all_metadata:
        place = m.get("place")
        if isinstance(place, int):
            existing_places.add(place)
        else:
            try:
                existing_places.add(int(place))
            except Exception:
                continue

    if not existing_places:
        return 1

    # Find smallest missing positive integer
    n = 1
    while n in existing_places:
        n += 1
    return n



# --- Route: upload any supported file and store embeddings ---
@router.post("/upload")
async def upload_file(file: UploadFile, user=Depends(require_admin)):
     # --- Save the uploaded file so it can be viewed later ---
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)

    save_path = upload_dir / file.filename
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Reset file pointer so PdfReader can read it again
    file.file.seek(0)
    # Get database place number
    if db.collection:
        db_place = get_next_available_place()
    else:
        db_place = 1

    pages = extract_text(file)
    max_pages = len(pages)
    normalized_id = Path(file.filename).stem.lower().replace(" ", "-")
    file_id = normalized_id

    existing_files = db.collection.get(include=["metadatas"])["metadatas"]
    existing_ids = {m.get("file_id") for m in existing_files if m.get("file_id")}
    if file_id in existing_ids:  # <-- compare the normalized id, not the UploadFile object
        print(f"\nDuplicate file detected. File: '{file.filename}' already exists in database\n")
        return {"message": f"Duplicate upload skipped: '{file.filename}' already exists in database."}

    uploaded_at = datetime.now().isoformat()
    embedding_model = settings.EMBEDDING_MODEL

    ids, metadatas, documents, embeddings = [], [], [], []
    overlap_size = 200
    previous_text_tail = ""

    for page_number, page_text in pages:
        raw_text = page_text.strip()
        combined_text = (previous_text_tail + "\n\n" + raw_text).strip()
        # Grab the last 200 chars of the CURRENT page
        if len(raw_text) > overlap_size:
            previous_text_tail = raw_text[-overlap_size:]
        else:
            previous_text_tail = raw_text
        # Handle empty pages (scans)
        if not combined_text:
            combined_text = "[IMAGE_ONLY_PAGE]"

        meta = {
            "source": file.filename,
            "file_id": file_id,
            "place": db_place,
            "page": page_number,
            "pages": max_pages,
            "char_count": len(combined_text),
            "embedding_model": embedding_model,
            "uploaded_at": uploaded_at
        }
        print(f"\n\n{meta}\n\n")

        emb = await llm_client.get_embedding(combined_text)

        unique_prefix = f"{file_id}-{os.urandom(4).hex()}"
        ids.append(f"{unique_prefix}-page-{page_number}")
        metadatas.append(meta)
        documents.append(combined_text)
        embeddings.append(emb)

    db.collection.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents
    )

    return {
    "message": f"Uploaded and processed {file.filename}",
    "pages": len(documents),
    "file_url": f"/uploads/{file.filename}"
    }
