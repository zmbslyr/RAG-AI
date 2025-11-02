from fastapi import APIRouter, UploadFile
from pathlib import Path
import os

from openai import OpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from datetime import datetime

from app.config import collection

# Optional RTF import
try:
    import striprtf
except ImportError:
    striprtf = None

router = APIRouter()
client_openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# --- Helpers (copied from main.py or moved to shared utils) ---
def extract_text(file: UploadFile):
    filename = file.filename.lower()

    if filename.endswith(".pdf"):
        reader = PdfReader(file.file)
        pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
        return pages

    elif filename.endswith((".txt", ".utf-8")):
        content = file.file.read()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="ignore")
        return [(1, text)]

    elif filename.endswith(".rtf"):
        if not striprtf:
            raise RuntimeError("striprtf package not installed. Run `pip install striprtf`.")
        raw_data = file.file.read().decode("utf-8", errors="ignore")
        text = striprtf.striprtf.rtf_to_text(raw_data)
        return [(1, text)]

    else:
        content = file.file.read()
        try:
            text = content.decode("utf-8")
        except Exception:
            text = ""
        return [(1, text)]


def split_text_into_chunks(text: str):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    return splitter.split_text(text)


# --- Route: upload any supported file and store embeddings ---
@router.post("/upload")
async def upload_file(file: UploadFile):
    # Get database place number
    if collection:
        results = collection.get()
        all_metadata = results.get("metadatas", [])
        unique_files = {m.get("file_id", "unknown"): m.get("source", "unknown") for m in all_metadata}
        db_place = len(unique_files) + 1
    else:
        db_place = 0

    pages = extract_text(file)
    max_pages = len(pages)
    normalized_id = Path(file.filename).stem.lower().replace(" ", "-")
    file_id = normalized_id

    existing_files = collection.get(include=["metadatas"])["metadatas"]
    existing_ids = {m.get("file_id") for m in existing_files if m.get("file_id")}
    if file_id in existing_ids:  # <-- compare the normalized id, not the UploadFile object
        print(f"\nDuplicate file detected. File: '{file.filename}' already exists in database\n")
        return {"message": f"Duplicate upload skipped: '{file.filename}' already exists in database."}

    uploaded_at = datetime.now().isoformat()
    embedding_model = "text-embedding-3-large"

    ids, metadatas, documents, embeddings = [], [], [], []

    for page_number, page_text in pages:
        chunk_text = page_text.strip()
        if not chunk_text:
            continue

        meta = {
            "source": file.filename,
            "file_id": file_id,
            "place": db_place,
            "page": page_number,
            "pages": max_pages,
            "char_count": len(chunk_text),
            "embedding_model": embedding_model,
            "uploaded_at": uploaded_at
        }
        print(f"\n\n{meta}\n\n")

        emb = client_openai.embeddings.create(
            model="text-embedding-3-large",
            input=chunk_text
        ).data[0].embedding

        unique_prefix = f"{file_id}-{os.urandom(4).hex()}"
        ids.append(f"{unique_prefix}-page-{page_number}")
        metadatas.append(meta)
        documents.append(chunk_text)
        embeddings.append(emb)

    collection.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents
    )

    return {"message": f"Uploaded and processed {file.filename}", "pages": len(documents)}
