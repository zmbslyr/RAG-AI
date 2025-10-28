# app/config.py
import os
from dotenv import load_dotenv
import chromadb
from openai import OpenAI

# --- Load environment variables ---
load_dotenv()

# --- Initialize Chroma persistent client and collection ---
chroma_client = chromadb.PersistentClient(path="chroma/")
collection = chroma_client.get_or_create_collection("pdf_docs")

# --- Initialize OpenAI client ---
client_openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
print("API key initialized. Loading Database...")
