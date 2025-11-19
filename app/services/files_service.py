from pathlib import Path
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
import os

import pymupdf
import pymupdf4llm

import fitz
import base64

try:
    import striprtf
except ImportError:
    striprtf = None

def extract_text(file):
    filename = file.filename.lower()
    if filename.endswith(".pdf"):
            # Read file bytes into a PyMuPDF Document
            file_bytes = file.file.read()
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
            
            # Extract Markdown with "page_chunks=True" to keep page boundaries
            # This returns a list of dicts: [{'text': '...', 'metadata': {'page': 1, ...}}]
            md_pages = pymupdf4llm.to_markdown(doc, page_chunks=True)
            
            # Convert to your expected format: List of (page_number, text) tuples
            # Note: PyMuPDF pages are 1-indexed in metadata, but let's ensure consistency
            return [(p["metadata"]["page"], p["text"]) for p in md_pages]
    elif filename.endswith((".txt", ".utf-8")):
        text = file.file.read().decode("utf-8", errors="ignore")
        return [(1, text)]
    elif filename.endswith(".rtf") and striprtf:
        text = striprtf.striprtf.rtf_to_text(file.file.read().decode("utf-8", errors="ignore"))
        return [(1, text)]
    else:
        return [(1, file.file.read().decode("utf-8", errors="ignore"))]

def split_text_into_chunks(text: str):
    # "Language.MARKDOWN" tells it to try not to split inside tables or headers
    splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.MARKDOWN,
        chunk_size=1000,
        chunk_overlap=150
    )
    return splitter.split_text(text)

# --- Helper: Returns png string for multimodal model ---
def render_page_to_base64(pdf_path: str, page_number: int, zoom: float = 2.0) -> str:
    """
    Opens a PDF, renders a specific page to an image, and returns a base64 string.
    page_number is 1-indexed (what humans/your DB use), so we convert to 0-indexed.
    """
    try:
        doc = fitz.open(pdf_path)
        # Convert 1-based page number to 0-based index
        page_index = page_number - 1
        
        if page_index < 0 or page_index >= len(doc):
            return None

        page = doc.load_page(page_index)
        
        # Matrix(2, 2) = 2x zoom. This is CRITICAL. 
        # Default resolution is 72 DPI (blurry). 2x gives ~150 DPI (readable schematics).
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        
        # Get image bytes directly (no file save needed)
        img_bytes = pix.tobytes("png")
        
        # Encode to base64
        base64_str = base64.b64encode(img_bytes).decode("utf-8")
        return base64_str
        
    except Exception as e:
        print(f"Error rendering page: {e}")
        return None
    finally:
        if 'doc' in locals():
            doc.close()
