# app/main.py

from fastapi import FastAPI, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from openai import OpenAI
from pathlib import Path
import re
import markdown
import json

from dotenv import load_dotenv
import os

# Initialize global variable for files position in database
#global db_place
#db_place = 0

# Optional: for RTF support
try:
    import striprtf
except ImportError:
    striprtf = None

load_dotenv() # Load variables from .env
api_key = os.getenv("OPENAI_API_KEY") #gets the API key from the .env file

print("Loaded API key:", api_key) # Verify API key is loaded DO NOT KEEP THIS IS PRODUCTION CODE

# Initialize app
app = FastAPI()

# --- Paths (make sure they point to app/static and app/templates) ---
#__file__ refers to the current file 
#.resolve ensures full path with no /../ 
#.parent removes the file name from the path, returning a path variable to the folder which contains the file.
BASE_DIR = Path(__file__).resolve().parent

# mounting allows the app to use files found on the disk at the specified location. This allows the HTML to load.
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static"
)

# templates is an object that allows jinja to know wherer to read templates from
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# this loads the web page when accessed through the browser
@app.get("/", response_class=HTMLResponse) #FastAPI expects JSON by default so we must specify HTML
def serve_index(request: Request): #The request object is created and passed to this function in the background by FastAPI, populated by the HTTP metadata
    return templates.TemplateResponse("index.html", {"request": request})

# --- OpenAI + Chroma setup ---
openai_api_key = api_key
client_openai = OpenAI(api_key=openai_api_key)

chroma_client = chromadb.PersistentClient(path="chroma/")
collection = chroma_client.get_or_create_collection("pdf_docs")

# --- Helper: extract + split text from text file. Return pages and text ---
def extract_text(file: UploadFile):
    filename = file.filename.lower()

    # PDF
    if filename.endswith(".pdf"):
        reader = PdfReader(file.file)
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):  # start=1 for human-readable pages
            text = page.extract_text() or ""
            pages.append((page_number, text))
        return pages  # list of (page_number, text) tuples

    # Plain text / UTF-8
    elif filename.endswith((".txt", ".utf-8")):
        content = file.file.read()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="ignore")
        return [(1, text)]  # single pseudo-page

    # RTF
    elif filename.endswith(".rtf"):
        if not striprtf:
            raise RuntimeError("striprtf package not installed. Run `pip install striprtf`.")
        raw_data = file.file.read().decode("utf-8", errors="ignore")
        text = striprtf.striprtf.rtf_to_text(raw_data)
        return [(1, text)]  # single pseudo-page

    else:
        # Fallback
        content = file.file.read()
        try:
            text = content.decode("utf-8")
        except Exception:
            text = ""
        return [(1, text)]

"""
# --- Helper: extract + split text from PDF ---
def extract_text(file: UploadFile) -> str:
    filename = file.filename.lower()

    # PDF
    if filename.endswith(".pdf"):
        reader = PdfReader(file.file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text

    # Plain text / UTF-8
    elif filename.endswith((".txt", ".utf-8")):
        content = file.file.read()
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("latin-1", errors="ignore")

    # RTF
    elif filename.endswith(".rtf"):
        if not striprtf:
            raise RuntimeError("striprtf package not installed. Run `pip install striprtf`.")
        raw_data = file.file.read().decode("utf-8", errors="ignore")
        return striprtf.striprtf.rtf_to_text(raw_data)

    # Fallback: try generic UTF-8 read
    else:
        content = file.file.read()
        try:
            return content.decode("utf-8")
        except Exception:
            return ""
"""

def split_text_into_chunks(text: str):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    return splitter.split_text(text)


# --- Route: upload any supported file and store embeddings ---
@app.post("/upload")
async def upload_file(file: UploadFile):

    # Check to see if there is a collection. If there is, increment 'db_place', else set to 0
    if collection:
        results = collection.get()
        all_metadata = results.get("metadatas", [])
        # Extract unique file IDs and filenames
        unique_files = {}
        for meta in all_metadata:
            source = meta.get("source", "unknown")
            file_id = meta.get("file_id", "unknown")
            unique_files[file_id] = source
        db_place = len(unique_files) + 1
    else:
        db_place = 0

    pages = extract_text(file)  # for PDFs returns [(page_number, text), ...]; for TXT/RTF returns [(1, text)]
    max_pages = len(pages)

    ids = []
    metadatas = []
    documents = []
    embeddings = []

    for page_number, page_text in pages:
        # Treat each page as a single chunk
        chunk_text = page_text.strip()
        if not chunk_text:
            continue  # skip empty pages

        # Metadata includes file name, file_id, page number
        meta = {
            "source": file.filename,
            "file_id": Path(file.filename).stem,
            "place": db_place,
            "page": page_number,
            "pages": max_pages
        }
        print(f"\n\n {meta} \n\n")
        # Generate embedding for this page
        emb = client_openai.embeddings.create(
            model="text-embedding-3-large",
            input=chunk_text
        ).data[0].embedding

        # Append to lists
        unique_prefix = f"{file.filename}-{os.urandom(4).hex()}"
        ids.append(f"{unique_prefix}-page-{page_number}")
        metadatas.append(meta)
        documents.append(chunk_text)
        embeddings.append(emb)

    # Add all pages to Chroma
    collection.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents
    )

    return {"message": f"Uploaded and processed {file.filename}", "pages": len(documents)}


"""
# --- Route: upload any supported file and store embeddings ---
@app.post("/upload")
async def upload_file(file: UploadFile):
    text = extract_text(file)
    chunks = split_text_into_chunks(text)

    # Prepend headers to each chunk
    total_chunks = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        chunks[i-1] = f"File: {file.filename}\nChunk: {i}/{total_chunks}\n{chunk}"
    
    embeddings = []

    # Generate embeddings via OpenAI
    for chunk in chunks:
        emb = client_openai.embeddings.create(
            model="text-embedding-3-large",
            input=chunk
        ).data[0].embedding
        embeddings.append(emb)

    # Add to Chroma
    ids = [f"{file.filename}-{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "source": file.filename,
            "chunk_index": i,
            "file_id": f"{file.filename}"
        }
        for i in range(len(chunks))
    ]

    collection.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=chunks
    )
    return {"message": f"Uploaded and processed {file.filename}", "chunks": len(chunks)}
"""

# --- Internal helper: call /list_files route from inside the app ---
client_local = TestClient(app)

async def call_list_files_route():
    """Call the existing /list_files route and return its JSON."""
    response = client_local.get("/list_files")
    return response.json()


# --- Route: ask question ---
@app.post("/ask")
async def ask_question(query: str = Form(...)):

    # Detect if the user is requesting a specific page
    page_match = re.search(r"page\s+(\d+)", query, re.IGNORECASE)
    if page_match:
        target_page = int(page_match.group(1))

        # Generate a 1536-dim embedding for the dummy query
        query_embedding = client_openai.embeddings.create(
            model="text-embedding-3-large",
            input="page lookup"
        ).data[0].embedding

        # Directly retrieve chunk from metadata instead of embedding query
        results = collection.query(
            query_embeddings=[query_embedding],
            where={"$or": [{"page": target_page}, {"page": str(target_page)}]},
            n_results=1,
            include=["documents", "metadatas"]
        )
    else:
        # Create embedding for user question
        query_embedding = client_openai.embeddings.create(
            model="text-embedding-3-large",
            input=query
        ).data[0].embedding

        # Search in ChromaDB
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=15,  # increase if you want more candidates
            include=["documents", "metadatas"]
        )

    # Chroma returns lists per query; we only have one query, so index 0
    retrieved_docs = results.get("documents", [[]])[0]
    retrieved_metas = results.get("metadatas", [[]])[0]

    # Return if no documents
    if not retrieved_docs:
        return JSONResponse({"answer": "No relevant documents found."})

    # Group the retrieved chunks by file_id (fallback to source if no file_id)
    grouped = {}
    for doc, meta, in zip(retrieved_docs, retrieved_metas):
        file_id = meta.get("file_id") if isinstance(meta, dict) else None
        source = meta.get("source") if isinstance(meta, dict) else None
        chunk_index = meta.get("chunk_index", 0) if isinstance(meta, dict) else 0
        key = file_id or source or "unknown-file"
        if key not in grouped:
            grouped[key] = {
                "file_id": file_id,
                "source": source,
                "chunks": []
            }
        grouped[key]["chunks"].append({"text": doc,"chunk_index": chunk_index,"page": meta.get("page", "unknown")})

    # --- Sort chunks by chunk_index before combining ---
    for info in grouped.values():
        info["chunks"].sort(key=lambda c: (c["chunk_index"], c["chunk_index"]))

    # Build a well-structured context string with clear separators and headers
    context_parts = []
    for idx, (fid, info) in enumerate(grouped.items(), start=1):
        # File header
        header = (
            f"=== {fid} ===\n"
            f"\n"
            f"Filename: {info.get('source')}\n"
            f"File ID: {info.get('file_id')}\n"
            f"Place: {info.get('place')}\n"
            f"Total Pages: {max(c.get('page', c.get('chunk_index', 0)) for c in info['chunks'])}\n"
            f"=== {fid} ===\n"
        )
        # Add each chunk with page info clearly separated
        chunk_texts = []
        for c in info["chunks"]:
            page = c.get("page", "unknown")
            pages = c.get("pages", "unknown")
            place = c.get("place", "unknown")
            chunk_index = c.get("chunk_index", 0)
            chunk_texts.append(f"--- FILE: {info.get('source')} | PAGE: {page} of {pages} | PLACE: {place} ---\n {c['text']}")
    
        # Join chunks with a clear separator
        file_text = "\n\n".join(chunk_texts)
        context_parts.append(header + file_text)

    context = "\n\n\n".join(context_parts)

    # 6) Strong system prompt instructing the model to pay attention to file headers
    system_message = (
        "You are an assistant that answers questions using only the provided document excerpts. "
        "Each page starts with '--- FILE: <filename> | PAGE: <number> of <number> | PLACE: <number> ---'."
        "The number in PLACE represents the files location in the database."
        "Always refer to these PAGE numbers when asked about a specific page. "
        "Do not assume pages exist if not listed, and do not invent content. "
        "When comparing multiple documents, explicitly mention Filename and Page numbers."
        "When asked about content on a specific page, or the number of pages, you must use these Page numbers. "
        "When you reference or compare material, explicitly mention the Filename and Page numbers so sources are clear."
        "You are allowed to use your electrical engineering knowledge to help you, but not your knowledge of specific manufacturer components."
    )

    """
    # Ask LLM with context
    completion = client_openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an assistant that answers questions based on given documents. Each document is seperated by headers. Keep sources distinct and refer to their filenames when comparing or summarizing."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
        ]
    )

    answer = completion.choices[0].message.content
    return JSONResponse({"answer": answer})
    """

    # --- Define tools (functions) the LLM can call ---
    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "Return the list of all files currently stored in the vector database, including their names and count.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    # If context is huge, truncate it unless needed
    if len(context) > 10000 and re.search(r"\b(list|show|many?)\b", query, re.IGNORECASE):
        context = "(context skipped — file listing not content-based)"
        system_message = "( no system message needed )"


    # 7) Ask the LLM with the grouped context
    completion = client_openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
        ],
        tools=tools,
        tool_choice="auto"
    )
    print(f"Initial Context\n{context}\nAdditional Prompting:\n{system_message}\n")

    
    # 8) For traceability, also return which file IDs were included in the context
    included_files = [{"file_id": info.get("file_id"), "filename": info.get("source")} for info in grouped.values()]

    message = completion.choices[0].message

    # --- Handle if the model wants to call a function ---
    if getattr(message, "tool_calls", None):
        tool_call = message.tool_calls[0]
        func_name = tool_call.function.name
        if func_name == "list_files":
            files_info = await call_list_files_route()
            result_text = (
                f"There are {files_info.get('count', 0)} files in the database:\n" +
                "\n".join(f"- {f['filename']}" for f in files_info.get("files", []))
            )

            # Feed the result back for a natural final answer
            second_response = client_openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": query},
                    message,  # the tool call
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_text,
                    },
                ],
            )
            answer_markdown = second_response.choices[0].message.content
        else:
            answer_markdown = message.content or ""
    else:
        answer_markdown = message.content or ""


    # Convert ChatGPT Markdown to HTML
    answer_html = markdown.markdown(
        answer_markdown,
        extensions=["fenced_code", "tables", "codehilite"]
    )

    return JSONResponse({
        "answer": answer_html,
        "used_files": included_files
    })


# --- Route: list all unique files in vector database ---
@app.get("/list_files")
async def list_files():
    # Retrieve all metadata stored in the collection
    results = collection.get()

    if not results or not results.get("metadatas"):
        return {"message": "No files found in the vector database.", "count": 0}

    # Flatten metadata list (Chroma returns list of lists)
    all_metadata = results.get("metadatas", [])
    # Extract unique file IDs and filenames
    unique_files = {}
    for meta in all_metadata:
        source = meta.get("source", "unknown")
        file_id = meta.get("file_id", "unknown")
        pages = meta.get("pages", "unknown")
        place = meta.get("place", "unknown")
        unique_files[file_id] = source

    print("\n\nPAGES: ", pages, "\n\n")

    return {
        "message": "Unique files currently stored in the vector database.",
        "count": len(unique_files),
        "files": [{"file_id": fid, "filename": name} for fid, name in unique_files.items()],
        "pages": pages,
        "place": place
    }

@app.get("/debug_metadata")
async def debug_metadata():
    """Inspect what metadata actually exists inside Chroma."""
    results = collection.get(include=["metadatas", "documents"], limit=5)
    metas = results.get("metadatas", [])
    print("\n\n=== METADATA DEBUG ===")
    for i, m in enumerate(metas[:10]):
        print(f"[{i}] {m}")
    print("======================\n\n")
    return metas
