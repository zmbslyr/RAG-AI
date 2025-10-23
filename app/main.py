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

# Initialize app
app = FastAPI()

# --- Paths (make sure they point to app/static and app/templates) ---
BASE_DIR = Path(__file__).resolve().parent

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static"
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")

@app.get("/", response_class=HTMLResponse)
def serve_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# --- OpenAI + Chroma setup ---
openai_api_key = "YOUR_OPENAI_API_KEY"
client_openai = OpenAI(api_key=openai_api_key)

chroma_client = chromadb.PersistentClient(path="chroma/")
collection = chroma_client.get_or_create_collection("pdf_docs")

# --- Helper: extract + split text from PDF ---
def process_pdf(file: UploadFile):
    reader = PdfReader(file.file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = splitter.split_text(text)
    return chunks

# --- Route: upload PDF and store embeddings ---
@app.post("/upload")
async def upload_pdf(file: UploadFile):
    chunks = process_pdf(file)
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
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an assistant that answers questions based on given documents."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
        ]
    )

    answer = completion.choices[0].message.content
    return JSONResponse({"answer": answer})