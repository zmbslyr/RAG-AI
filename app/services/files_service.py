from pathlib import Path
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os

try:
    import striprtf
except ImportError:
    striprtf = None

def extract_text(file):
    filename = file.filename.lower()
    if filename.endswith(".pdf"):
        reader = PdfReader(file.file)
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    elif filename.endswith((".txt", ".utf-8")):
        text = file.file.read().decode("utf-8", errors="ignore")
        return [(1, text)]
    elif filename.endswith(".rtf") and striprtf:
        text = striprtf.striprtf.rtf_to_text(file.file.read().decode("utf-8", errors="ignore"))
        return [(1, text)]
    else:
        return [(1, file.file.read().decode("utf-8", errors="ignore"))]

def split_text_into_chunks(text: str):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    return splitter.split_text(text)
