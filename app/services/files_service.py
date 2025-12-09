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
# app/services/files_service.py

def render_page_to_base64(pdf_path: str, page_number: int, zoom: float = 3.0) -> list[str]:
    """
    Returns a list of base64 images:
    Index 0: The FULL PAGE (The 'Map') - moderate resolution, preserves topology.
    Index 1+: The SLICES (The 'Magnifiers') - max resolution, for reading tiny labels.
    """
    images = []
    try:
        doc = fitz.open(pdf_path)
        page_index = page_number - 1
        
        if page_index < 0 or page_index >= len(doc):
            return []

        page = doc.load_page(page_index)
        rect = page.rect

        # --- 1. Generate the "Map" (Full Page) ---
        # We target ~2000px height to fit OpenAI's vision limit without hidden downscaling
        # Standard PDF is ~842pts high. 2.0 zoom = ~1684px.
        map_zoom = 2.0 
        mat_map = fitz.Matrix(map_zoom, map_zoom)
        pix_map = page.get_pixmap(matrix=mat_map)
        img_bytes_map = pix_map.tobytes("png")
        images.append(base64.b64encode(img_bytes_map).decode("utf-8"))

        # --- 2. Generate the "Slices" (High Res Detail) ---
        # High zoom for reading tiny text labels
        mat_slice = fitz.Matrix(zoom, zoom) # zoom is 3.0 passed in args
        
        mid_y = rect.height / 2
        overlap = 250
        
        clips = [
            # Index 1: Top Half
            fitz.Rect(0, 0, rect.width, mid_y + overlap),
            
            # Index 2: Bottom Half
            fitz.Rect(0, mid_y - overlap, rect.width, rect.height),
            
            # Index 3: MIDDLE SLICE
            # Captures the middle 60% of the page intact (from 20% down to 80%)
            fitz.Rect(0, rect.height * 0.20, rect.width, rect.height * 0.80)
        ]

        for clip in clips:
            pix = page.get_pixmap(matrix=mat_slice, clip=clip)
            img_bytes = pix.tobytes("png")
            images.append(base64.b64encode(img_bytes).decode("utf-8"))
            
        return images
        
    except Exception as e:
        print(f"Error rendering page: {e}")
        return []
    finally:
        if 'doc' in locals():
            doc.close()
