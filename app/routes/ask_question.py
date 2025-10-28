from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
import re
import markdown
from difflib import get_close_matches
from openai import OpenAI
from app.config import client_openai, collection

from fastapi.testclient import TestClient
from app.main import app

# --- Internal helper: call /list_files route from inside the app ---
client_local = TestClient(app)

async def call_list_files_route():
    """Call the existing /list_files route and return its JSON."""
    response = client_local.get("/list_files")
    return response.json()

router = APIRouter()

# --- Route: ask question ---
@router.post("/ask")
async def ask_question(query: str = Form(...)):

    # 1. Detect a page number (like "page 3")
    page_match = re.search(r"page\s+(\d+)", query, re.IGNORECASE)
    page_num = int(page_match.group(1)) if page_match else None

    # 2. Detect a filename (quoted or capitalized)
    file_match = re.search(r'["“”](.+?)["“”]', query)  # match text in quotes
    if file_match:
        file_query = file_match.group(1).strip()
    else:
        # fallback heuristic for unquoted titles: consecutive capitalized words
        possible_name = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4})', query)
        file_query = possible_name.group(1).strip() if possible_name else None

    # 3. If a file name was detected, try to match it to known sources
    matched_file = None
    if file_query:
        # Get all known sources in Chroma metadata
        all_files = {
            m.get("source") for m in collection.get(include=["metadatas"])["metadatas"]
            if m.get("source")
        }

        # DEBUG: show available files
        all_files = {
            m.get("source") for m in collection.get(include=["metadatas"])["metadatas"]
            if m.get("source")
        }
        print("\n[DEBUG] Available file sources in collection:")
        for f in all_files:
            print(f"  ->", f)

        matches = get_close_matches(file_query, all_files, n=1, cutoff=0.5)
        if matches:
            matched_file = matches[0]

    # 4. Create appropriate query embedding
    query_embedding = client_openai.embeddings.create(
        model="text-embedding-3-large",
        input="page lookup" if page_num else query
    ).data[0].embedding

    # 5. Build metadata filter dynamically
    filters = {}
    if matched_file:
        filters["source"] = matched_file
    if page_num:
        filters["$or"] = [{"page": page_num}, {"page": str(page_num)}]

    # 6. Query Chroma with these filters
    results = collection.query(
        query_embeddings=[query_embedding],
        where=filters if filters else None,
        n_results=10,
        include=["documents", "metadatas"]
    )

    # Optional debug info
    print(f"\n[Stage E+] Filters applied: {filters or 'None'}")
    if matched_file:
        print(f"Matched file: {matched_file}")
    if page_num:
        print(f"Matched page: {page_num}")
    print()


    # Chroma returns lists per query; we only have one query, so index 0
    retrieved_docs = results.get("documents", [[]])[0]
    retrieved_metas = results.get("metadatas", [[]])[0]

    # Return if no documents
    if not retrieved_docs:
        return JSONResponse({"answer": "No relevant documents found."})

    # Get all metadata from the collection so the LLM knows every file and its page count
    all_results = collection.get(include=["metadatas"])
    all_metas = all_results.get("metadatas", [])

    # Build an index of file_id → {source, pages, place}
    file_index = {}
    for m in all_metas:
        fid = m.get("file_id", "unknown")
        if fid not in file_index:
            file_index[fid] = {
                "source": m.get("source", "unknown"),
                "pages": m.get("pages", "unknown"),
                "place": m.get("place", "unknown")
            }

    # Merge known metadata (pages, place) into every meta that lacks it
    for m in retrieved_metas:
        fid = m.get("file_id", "unknown")
        if fid in file_index:
            for key in ("pages", "place", "source"):
                if m.get(key) in (None, "unknown"):
                    m[key] = file_index[fid][key]

    # Optional debug print
    print("\n[Stage E] File index summary:")
    for fid, info in file_index.items():
        print(f"  {fid}: pages={info['pages']}, place={info['place']}, source={info['source']}")
    print()


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
                "chunks": [],
                "place": meta.get("place", "unknown"),
                "pages": meta.get("pages", "unknown")
            }
        grouped[key]["chunks"].append({"text": doc,"chunk_index": chunk_index,"page": meta.get("page", "unknown")})

    # --- Sort chunks by chunk_index before combining ---
    for info in grouped.values():
        info["chunks"].sort(key=lambda c: (c["chunk_index"], c["chunk_index"]))

    # Build a well-structured context string with clear separators and headers
    context_parts = []
    for idx, (fid, info) in enumerate(grouped.items(), start=1):
        representative_page = (
            info["chunks"][0].get("page")
            if info.get("chunks") and isinstance(info["chunks"], list) and len(info["chunks"]) > 0
            else "unknown"
        )

        # File header
        header = (
            f"=== {fid} ===\n"
            f"\n"
            f"Filename: {info.get('source')}\n"
            f"File ID: {info.get('file_id')}\n"
            f"Place: {info.get('place')}\n"
            f"Page: {representative_page}\n"
            f"Total Pages: {info.get('pages')}\n"
            f"=== {fid} ===\n"
        )
        # Add each chunk with page info clearly separated
        chunk_texts = []
        for c in info["chunks"]:
            page = c.get("page", "unknown")
            pages = info.get("pages", "unknown")
            place = info.get("place", "unknown")
            chunk_index = c.get("chunk_index", 0)
            chunk_texts.append(f"\n--- FILE: {info.get('source')} | PAGE: {page} of {pages} | PLACE: {place} ---\n\n {c['text']}")
    
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
