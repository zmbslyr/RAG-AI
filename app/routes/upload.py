from fastapi import APIRouter, UploadFile
from pathlib import Path
import shutil
import os

from openai import OpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

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
     # --- Save the uploaded file so it can be viewed later ---
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)

    save_path = upload_dir / file.filename
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Reset file pointer so PdfReader can read it again
    file.file.seek(0)
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

    ids, metadatas, documents, embeddings = [], [], [], []

    for page_number, page_text in pages:
        chunk_text = page_text.strip()
        if not chunk_text:
            continue

        meta = {
            "source": file.filename,
            "file_id": Path(file.filename).stem,
            "place": db_place,
            "page": page_number,
            "pages": max_pages,
        }
        print(f"\n\n{meta}\n\n")

        emb = client_openai.embeddings.create(
            model="text-embedding-3-large",
            input=chunk_text
        ).data[0].embedding

        unique_prefix = f"{file.filename}-{os.urandom(4).hex()}"
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

    return {
    "message": f"Uploaded and processed {file.filename}",
    "pages": len(documents),
    "file_url": f"/uploads/{file.filename}"
    }