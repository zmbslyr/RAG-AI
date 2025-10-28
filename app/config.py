# app/config.py
import chromadb

# Initialize Chroma persistent client and collection
chroma_client = chromadb.PersistentClient(path="chroma/")
collection = chroma_client.get_or_create_collection("pdf_docs")
