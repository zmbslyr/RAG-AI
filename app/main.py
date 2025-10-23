# app/main.py
from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import JSONResponse
import openai, chromadb
from pypdf import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter

openai.api_key = "YOUR_OPENAI_API_KEY"

app = FastAPI()
client = chromadb.PersistentClient(path="chroma/")
collection = client.get_or_create_collection("pdf_docs")

# Helper: extract + split text
def process_pdf(file: UploadFile):
    pdf = PdfReader(file.file)
    text = " ".join(page.extract_text() for page in pdf.pages if page.extract_text())
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = splitter.split_text(text)
    return chunks

@app.post("/upload_pdf")
async def upload_pdf(file: UploadFile):
    chunks = process_pdf(file)
    for idx, chunk in enumerate(chunks):
        emb = openai.embeddings.create(input=chunk, model="text-embedding-3-small")["data"][0]["embedding"]
        collection.add(ids=[f"{file.filename}-{idx}"], documents=[chunk], embeddings=[emb], metadatas=[{"source": file.filename}])
    return {"message": f"Stored {len(chunks)} chunks from {file.filename}"}

@app.post("/query")
async def query_rag(query: str = Form(...)):
    query_emb = openai.embeddings.create(input=query, model="text-embedding-3-small")["data"][0]["embedding"]
    results = collection.query(query_embeddings=[query_emb], n_results=5)

    context = "\n".join(results["documents"][0])
    completion = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a research assistant that uses the provided context."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
        ]
    )
    answer = completion.choices[0].message.content
    return JSONResponse({"answer": answer})