# app/main.py

from fastapi import FastAPI, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from openai import OpenAI
from pathlib import Path

from dotenv import load_dotenv
import os

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

def split_text_into_chunks(text: str):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    return splitter.split_text(text)

# --- Route: upload any supported file and store embeddings ---
@app.post("/upload")
async def upload_file(file: UploadFile):
    text = extract_text(file)
    chunks = split_text_into_chunks(text)
    embeddings = []

    # Generate embeddings via OpenAI
    for chunk in chunks:
        emb = client_openai.embeddings.create(
            model="text-embedding-3-small",
            input=chunk
        ).data[0].embedding
        embeddings.append(emb)

    # Add to Chroma
    ids = [f"{file.filename}-{i}" for i in range(len(chunks))]
    collection.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=[{"source": file.filename}] * len(chunks),
        documents=chunks
    )
    return {"message": f"Uploaded and processed {file.filename}", "chunks": len(chunks)}

# --- Route: ask question ---
@app.post("/ask")
async def ask_question(query: str = Form(...)):
    # Create embedding for user question
    query_embedding = client_openai.embeddings.create(
        model="text-embedding-3-small",
        input=query
    ).data[0].embedding

    # Search in ChromaDB
    results = collection.query(query_embeddings=[query_embedding], n_results=5)
    retrieved_docs = results["documents"][0]
    context = "\n\n".join(retrieved_docs)

    # Ask LLM with context
    completion = client_openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an assistant that answers questions based on given documents."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
        ]
    )

    answer = completion.choices[0].message.content
    return JSONResponse({"answer": answer})
