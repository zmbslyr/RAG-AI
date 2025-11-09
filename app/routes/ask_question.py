# app/routes/ask_question.py
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
import re
import json
import markdown
from difflib import get_close_matches
from app.config import client_openai, collection
from app.memory import session_memory, get_session_context, update_session_memory, get_last_active_file, set_last_active_file
import uuid
from pathlib import Path


from fastapi.testclient import TestClient
from app.main import app

# --- Helper to normalize filename to file_id ---
def to_file_id(filename: str) -> str:
    return Path(filename).stem.lower() if filename else ""

# --- Internal helper: call /list_files route from inside the app ---
client_local = TestClient(app)

async def call_list_files_route():
    """Call the existing /list_files route and return its JSON."""
    response = client_local.get("/list_files")
    return response.json()

# --- Internal helper: call /debug_metadata route from inside the app ---
async def call_debug_route():
    """Call the /debug route and return its JSON."""
    response = client_local.get("/debug_metadata")
    return response.json()


# --- Helper: fuzzy-match a partial query to DB filenames ---
async def find_best_file_match_func(query: str):
    """
    Given a partial or paraphrased title, returns the best matching filenames
    from the available filenames in the database (via list_files).
    """
    files_info = await call_list_files_route()
    filenames = [f.get("filename") for f in files_info.get("files", []) if f.get("filename")]
    if not filenames:
        return []

    # Match against lowercase variants but return original-cased filenames
    lc_map = {fn.lower(): fn for fn in filenames}
    matches_lc = get_close_matches(query.lower(), list(lc_map.keys()), n=3, cutoff=0.4)
    mapped_matches = [lc_map[k] for k in matches_lc]
    return mapped_matches

router = APIRouter()

# --- Route: ask question ---
@router.post("/ask")
async def ask_question(query: str = Form(...)):

    # --- Conversation memory setup ---
    # Generate or retrieve a session ID (in production, send from frontend)
    session_id = "default"  # Replace later with client-provided ID if desired
    prior_context = get_session_context(session_id)

    # Track which file should be "active" this round
    active_file = get_last_active_file(session_id)
    matched_file = None

    # Optional: only keep memory turns about the same file
    if active_file or matched_file:
        file_ref = (matched_file or active_file)
        # crude text filter to remove prior turns mentioning other filenames
        prior_context = "\n".join([
            line for line in prior_context.splitlines()
            if not re.search(r"\.pdf", line, re.IGNORECASE) or file_ref.lower() in line.lower()
        ])

    # Detect delete command
    if query.strip().lower().startswith("delete "):
        filename_query = query.split(" ", 1)[1].strip().lower()

        # Get all files
        files_info = await call_list_files_route()
        files = files_info.get("files", [])
        filenames = [f.get("filename") for f in files if f.get("filename")]

        if not filenames:
            return JSONResponse({"answer": "No files in database to delete"})
        
        # Fuzzy match the input to the existing filenames
        match = get_close_matches(filename_query.lower(), [fn.lower() for fn in filenames], n=1, cutoff=0.4)
        if not match:
            return JSONResponse({"answer": f"No close match found for '{filename_query}'.", "used_files": []})
        
        matched_filename = match[0]
        matched_file_id = next((f["file_id"] for f in files if f["filename"].lower() == matched_filename), None)

        if not matched_file_id:
            return JSONResponse({"answer": f"Could not find file_id for '{matched_filename}'.", "used_files": []})
        
        # Call delete_file route internally
        client_local = TestClient(app)
        response = client_local.delete(f"/delete_file/{matched_file_id}")

        if response.status_code != 200:
            return JSONResponse({
                "answer": f"Error deleting '{matched_filename}': {response.json().get('detail', 'Unknown error')}",
                "used_files": []
            })
        
        result = response.json()
        result_text = f"Deleted '{matched_filename}' (file_id: {matched_file_id})\n\nRemaining files: {result.get('remaining_files', 0)}"
        return JSONResponse({"answer": f"<pre>{result_text}</pre>", "used_files": []})

    # Detect debug command
    if query.strip().lower().startswith("debug"):
        debug_info = await call_debug_route()
        # Optionally pretty-format JSON for readability in chat
        debug_json = json.dumps(debug_info, indent=2)
        debug_html = f"<pre>{debug_json}</pre>"
        return JSONResponse({"answer": debug_html, "used_files": []})

    # Detect a page number (like "page 3")
    page_match = re.search(r"page\s+(\d+)", query, re.IGNORECASE)
    page_num = int(page_match.group(1)) if page_match else None

    # --- Ask the LLM to infer which file(s) to target (supports compare mode) ---
    files_info = await call_list_files_route()
    available_files = [f["filename"] for f in files_info.get("files", [])]
    available_file_ids = [f["file_id"] for f in files_info.get("files", [])]
    active_file = get_last_active_file(session_id)

    file_inference_prompt = f"""
    You determine which document(s) the user means.

    Conversation so far:
    {prior_context}

    User just asked: "{query}"

    Available files (exact filenames): {available_files}
    Currently active file: {active_file or 'None'}

    Rules:
    - If user clearly names one doc or implies the last active doc, return that ONE exact filename.
    - If user is comparing/asking about multiple docs (e.g., "compare", "vs", "both", or names multiple),
    return the exact filenames separated by commas, in any order.
    - If user says "all files" or similar, return the exact filenames for ALL available files, comma-separated.
    - If uncertain, return "None".

    Respond with ONLY the filename(s) from the list, comma-separated. No extra text.
    """

    inference = client_openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": file_inference_prompt}],
    )
    llm_raw = (inference.choices[0].message.content or "").strip()
    print(f"[LLM FILE INFERENCE RAW] {llm_raw}")

    # Parse the LLM output
    tokens = [t.strip() for t in llm_raw.split(",") if t.strip()]
    # Validate strictly against the available list
    valid = [t for t in tokens if t in available_files]

    # Heuristics if model returns None/empty
    if not valid:
        # If query looks like a compare request but LLM didn't list, fall back to all
        if re.search(r"\b(compare|vs|versus|both|all files|all documents)\b", query, re.IGNORECASE):
            valid = available_files[:]
        # Otherwise reuse active_file if available
        elif active_file:
            valid = [active_file]

    # Set modes and memory
    matched_files = valid[:]                           # list of filenames
    multi_file_mode = len(matched_files) > 1           # comparison mode?
    matched_file = matched_files[0] if matched_files else None  # primary for continuity

    if matched_file:
        set_last_active_file(session_id, matched_file)

    print(f"[MATCH] Query: {query}")
    print(f"[MATCH] Inferred files: {matched_files or 'None'}")
    print(f"[MATCH] Multi-file mode: {multi_file_mode}")
    print(f"[MATCH] Active file (memory): {active_file}")



    # --- Build metadata filter (single-file or multi-file) ---
    filters = {}

    def one_file_filter(fname: str):
        fid = to_file_id(fname)
        # Prefer matching by file_id; also allow exact source filename for safety
        return {"$or": [{"file_id": fid}, {"source": fname}]}

    if matched_files and multi_file_mode:
        # Only include the selected files (good for compare between specific docs)
        ors = [one_file_filter(f) for f in matched_files]
        filters = {"$or": ors} if ors else {}
    elif matched_file:
        filters = one_file_filter(matched_file)
    else:
        filters = {}  # nothing inferred → allow wide search

    # Add optional page filter (applies to both single and multi-file cases)
    if page_num is not None:
        page_filter = {"$or": [{"page": page_num}, {"page": str(page_num)}]}
        filters = {"$and": [filters, page_filter]} if filters else page_filter

    # Natural-language fallbacks that should open the filter up
    if re.search(r"\b(all files|compare|vs|versus|both)\b", query, re.IGNORECASE):
        # If user explicitly asks to compare EVERYTHING, drop to empty filters.
        if re.search(r"\ball files\b", query, re.IGNORECASE):
            filters = {}
        # If they didn’t name which files, we already constrained to matched_files above.
        # If matched_files is empty, filters stays {} (wide compare).

    print("\n===============================")
    print(f"[FILTER] Final filter object: {json.dumps(filters, indent=2)}")
    print("=================================\n")

    # Create appropriate query embedding
    query_embedding = client_openai.embeddings.create(
        model="text-embedding-3-large",
        input="page lookup" if page_num else query
    ).data[0].embedding

    if re.search(r"\b(compare|both|all files)\b", query, re.IGNORECASE):
        filters = {}  # disable filtering for cross-file questions

    # 6. Query Chroma with these filters
    results = collection.query(
        query_embeddings=[query_embedding],
        where=filters if filters else None,
        n_results=10,
        include=["documents", "metadatas"]
    )

    # Optional debug info
    print(f"\n[DEBUG] Filters applied: {filters or 'None'}")
    if matched_file:
        print(f"Matched file: {matched_file}")
    if page_num:
        print(f"Matched page: {page_num}")
    print()

    # Chroma returns lists per query; we only have one query, so index 0
    retrieved_docs = results.get("documents", [[]])[0]
    retrieved_metas = results.get("metadatas", [[]])[0]

    # Build list of sources with page links
    sources_list = []
    seen = set()  # to prevent duplicates

    for meta in retrieved_metas:
        if not meta or not isinstance(meta, dict):
            continue

        filename = meta.get("source", "unknown")
        page = meta.get("page", "unknown")

        if filename == "unknown" or page == "unknown":
            continue

        # Build direct link to the page in the uploaded PDF
        url = f"/uploads/{filename}#page={page}"
        key = (filename, page)
        if key not in seen:
            seen.add(key)
            sources_list.append({
                "filename": filename,
                "page": page,
                "url": url
            })


    # Return if no documents
    if not retrieved_docs:
        return JSONResponse({"answer": "No relevant documents found."})

    # Get full file metadata via list_files route (smarter and consistent)
    files_info = await call_list_files_route()
    file_index = {
        f.get("file_id", "unknown"): {
            "source": f.get("filename", "unknown"),
            "pages": f.get("total_pages", "unknown"),
            "place": f.get("place", "unknown")
        }
        for f in files_info.get("files", [])
    }
    print("\n[DEBUG] File metadata index from list_files:")
    for fid, info in file_index.items():
        print(f"  {fid}: {info}")
    print("\n")

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
    for doc, meta in zip(retrieved_docs, retrieved_metas):
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
        grouped[key]["chunks"].append({
            "text": doc,
            "chunk_index": chunk_index,
            "page": meta.get("page", "unknown")
        })

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
            chunk_texts.append(
                f"\n--- FILE: {info.get('source')} | PAGE: {page} of {pages} | PLACE: {place} ---\n\n{c['text']}"
            )

        # Join chunks with a clear separator
        file_text = "\n\n".join(chunk_texts)
        context_parts.append(header + file_text)

    context = "\n\n\n".join(context_parts)

    # 6) Strong system prompt instructing the model to pay attention to file headers
    system_message = (
        "You must limit your reasoning to the provided excerpts for the active file "
        "(unless the question clearly asks to compare multiple documents). "
        "You are an assistant that answers questions using only the provided document excerpts. "
        "Each page starts with '--- FILE: <filename> | PAGE: <number> of <number> | PLACE: <number> ---'. "
        "The number in PLACE represents the files location in the database. "
        "Always refer to these PAGE numbers when asked about a specific page. "
        "Do not assume pages exist if not listed, and do not invent content. "
        "When comparing multiple documents, explicitly mention Filename and Page numbers. "
        "When asked about content on a specific page, or the number of pages, you must use these Page numbers. "
        "When you reference or compare material, explicitly mention the Filename and Page numbers so sources are clear."
        "During comparisons across multiple documents, always attribute each point with 'Filename, Page N' based on the headers in the provided context."
    )

    # --- Define tools (functions) the LLM can call ---
    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "Return detailed metadata for all files (filename, total_pages, place, file_id).",
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_best_file_match",
                "description": "Given a partial title, return best matching filenames from the DB.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "partial or vague title"}
                    },
                    "required": ["query"]
                }
            }
        }
    ]

    # If context is huge, truncate it unless needed
    if len(context) > 10000 and re.search(r"\b(list|show|many?)\b", query, re.IGNORECASE):
        context = "(context skipped — file listing not content-based)"
        system_message = "( no system message needed )"

    # Integrate short-term memory into the prompt
    user_prompt = f"""
    --- Prior Conversation ---
    {prior_context}

    --- Retrieved Context ---
    {context}

    --- New Question ---
    {query}
    """

    print(f"\n{user_prompt}\n")

    # Ask the LLM with the grouped context
    completion = client_openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_prompt}
        ],
        tools=tools,
        tool_choice="auto"
    )
    print(f"Initial Context\n{context}\nAdditional Prompting:\n{system_message}\n")

    # 8) For traceability, also return which file IDs were included in the context
    included_files = [{"file_id": info.get("file_id"), "filename": info.get("source")} for info in grouped.values()]

    message = completion.choices[0].message

    # --- Handle if the model wants to call one or more functions (tool_calls) ---
    if getattr(message, "tool_calls", None):
        tool_messages = []

        # loop all tool calls and prepare a tool response for each
        for tool_call in message.tool_calls:
            func_name = tool_call.function.name

            if func_name == "list_files":
                # return rich metadata lines
                files_info = await call_list_files_route()
                result_lines = []
                for f in files_info.get("files", []):
                    filename = f.get("filename", "unknown")
                    total_pages = f.get("total_pages", "unknown")
                    place = f.get("place", "unknown")
                    result_lines.append(f"- {filename} — Total Pages: {total_pages} — Place: {place}")
                result_text = (
                    f"There are {files_info.get('count', 0)} files in the database.\n\n"
                    f"Here are their details:\n" + "\n".join(result_lines)
                )
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_text,
                })

            elif func_name == "find_best_file_match":
                # tool_call.function.arguments is a JSON string; parse safely
                args_raw = getattr(tool_call.function, "arguments", "{}")
                try:
                    args = json.loads(args_raw)
                except Exception:
                    args = {}
                query_str = args.get("query", "")
                matches = await find_best_file_match_func(query_str)
                result_text = f"Best matches for '{query_str}': {matches}"
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_text,
                })

            else:
                # unrecognized tool - respond with a safe default
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"No handler implemented for tool '{func_name}'."
                })

        # Now feed all tool responses back to the model at once
        second_response = client_openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": query},
                message,   # assistant message containing tool_calls
                *tool_messages,
            ],
        )
        answer_markdown = second_response.choices[0].message.content

    else:
        answer_markdown = message.content or ""

    # Convert ChatGPT Markdown to HTML
    answer_html = markdown.markdown(
        answer_markdown,
        extensions=["fenced_code", "tables", "codehilite"]
    )

    # --- Build grouped clickable source links for in-app viewer ---
    from collections import defaultdict

    grouped_sources = defaultdict(list)
    for s in sources_list:
        grouped_sources[s["filename"]].append(int(s["page"]))

    # Sort and deduplicate
    for fname in grouped_sources:
        grouped_sources[fname] = sorted(set(grouped_sources[fname]))

    sources_html = ""
    if grouped_sources:
        html_lines = ["<h4>Sources:</h4>"]
        for fname, pages in grouped_sources.items():
            # Each page number becomes a link with data attributes
            page_links = ", ".join(
                f'<a href="#" class="open-in-viewer" data-file="{fname}" data-page="{p}">{p}</a>'
                for p in pages
            )

            plural = "Pages" if len(pages) > 1 else "Page"
            html_lines.append(f"<p><strong>{fname}</strong> — {plural} {page_links}</p>")
        sources_html = "\n".join(html_lines)

    final_html = answer_html + sources_html
    
    # Update session memory
    update_session_memory(session_id, query, answer_markdown)

    return JSONResponse({
        "answer": final_html,
        "used_files": included_files,
        "sources": sources_list
    })
