# app/routes/ask_question.py
from fastapi import APIRouter, Form, Depends
from fastapi.responses import JSONResponse
import re
import json
import markdown
from difflib import get_close_matches
from pathlib import Path
from sqlalchemy.orm import Session

# Local Imports
from app.services.llm_service import llm_client
from app.services.chroma_service import query_collection
from app.memory import get_session_context, update_session_memory, get_last_active_file, set_last_active_file
from app.services.files_service import render_page_to_base64
from app.routes.list_files import list_files
from app.routes.debug_metadata import debug_metadata
from app.routes.delete_file import delete_file as delete_file_func
from app.routes.auth import get_current_user
from app.core.deps import get_db
from app.core import db as db_core

# --- Helper to normalize filename to file_id ---
def to_file_id(filename: str) -> str:
    return Path(filename).stem.lower() if filename else ""

# --- Helper: fuzzy-match a partial query to DB filenames ---
async def find_best_file_match_func(query: str):
    """
    Given a partial or paraphrased title, returns the best matching filenames
    from the available filenames in the database (via list_files).
    """
    files_info = await list_files()
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
async def ask_question(
    query: str = Form(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    # --- Conversation memory setup ---
    # Generate or retrieve a session ID (in production, send from frontend)
    username = user.get("username", "unknown_user")
    session_id = f"{username}-{db_core.ACTIVE_DB_NAME}"
    prior_context = get_session_context(db, session_id)

    # --- DEBUG PRINT ---
    print(f"[ROUTE DEBUG] Prior Context Length: {len(prior_context)}")
    # -------------------

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

    # Detect debug command
    if query.strip().lower().startswith("debug"):
        debug_info = await debug_metadata()
        # Optionally pretty-format JSON for readability in chat
        debug_json = json.dumps(debug_info, indent=2)
        debug_html = f"<pre>{debug_json}</pre>"
        return JSONResponse({"answer": debug_html, "used_files": []})

    # Detect page number(s) (e.g. "page 3", "pages 3, 4, 5")
    page_section_matches = re.findall(r"pages?\s+([\d\s,and&]+)", query, re.IGNORECASE)
    target_pages = []
    for section in page_section_matches:
        # Extract individual digits from the captured phrase
        nums = re.findall(r"\d+", section)
        target_pages.extend([int(n) for n in nums])
    
    # Deduplicate and sort
    target_pages = sorted(list(set(target_pages)))
    
    # Keep 'page_num' as the first page found (for Vision/Image fallback support)
    page_num = target_pages[0] if target_pages else None

    # --- Ask the LLM to infer which file(s) to target (supports compare mode) ---
    files_info = await list_files()
    available_files = [f["filename"] for f in files_info.get("files", [])]
    available_file_ids = [f["file_id"] for f in files_info.get("files", [])]
    active_file = get_last_active_file(session_id)

    file_inference_prompt = f"""
        You are a routing assistant. Determine what the user wants to do.

        Conversation so far:
        {prior_context}

        User just asked: "{query}"

        Available files: {available_files}
        Currently active file: {active_file or 'None'}

        Rules:
        1. **PRIORITIZE THE NEW QUESTION.** If the user mentions a different file than the Active File, you MUST return the new filename, unless the user is asking for a comparison. Ignore the previous context.
        2. **LIST COMMAND**: If the user is asking to list, show, or display all available files (e.g. 'list files', 'what do you have', 'show inventory', 'how many files'), respond with exactly "COMMAND_LIST".
        3. **DELETE COMMAND**: If the user explicitly asks to delete, remove, or erase a file, identify the closest filename from the list and respond with "COMMAND_DELETE: <exact_filename>".
        4. **SPECIFIC FILE**: If the user mentions a file by name, partial name, or keyword, identify the best match and return that ONE exact filename.
        5. **COMPARE FILES**: If the user explicitly asks to compare **multiple different documents** (e.g. "compare file A and file B", "difference between X and Y"), return the exact filenames comma-separated.
        6. **COMPARE PAGES/ACTIVE**: If the user asks to compare **pages, graphs, or sections** WITHOUT naming a specific file (e.g. "compare page 8 and 9", "compare the charts"), return ONLY the "Currently active file". Do NOT return multiple files.
        7. **ALL FILES**: If user asks a question about "all files" (e.g. "summarize all files"), return "ALL_FILES".
        8. **UNCERTAIN**: Return "None" only if no file in the list matches the user's request.

        Respond ONLY with the filename(s), "COMMAND_LIST", "COMMAND_DELETE: <exact_filename>", "ALL_FILES", or "None".
        """

    inference = await llm_client.chat(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": file_inference_prompt}],
    )
    llm_raw = (inference.choices[0].message.content or "").strip()
    print(f"[LLM FILE INFERENCE RAW] {llm_raw}")

    # Only run this if the LLM failed (returned None)
    if "None" in llm_raw and "ALL_FILES" not in llm_raw:
        normalized_query = query.lower()
        
        # 1. Define "Risky" words to ignore (Common adjectives/nouns in titles)
        #    "great" prevents "Is it great?" -> Gatsby
        #    "case" prevents "In this case..." -> Dr. Jekyll
        risky_words = {
            "the", "a", "an", "of", "in", "and", "or", "to", "for", "file", "pdf", 
            "book", "story", "about", "what", "happens", "is", "does", "great", 
            "strange", "case", "study", "legend", "island", "doctor", "guide"
        }

        detected_by_python = []
        for fname in available_files:
            # Clean filename: "The-Great-Gatsby.pdf" -> ["great", "gatsby"]
            clean_name = Path(fname).stem.lower().replace("-", " ").replace("_", " ")
            parts = clean_name.split()
            
            # Only match against "Strong" unique words
            strong_keywords = [w for w in parts if w not in risky_words and len(w) > 3]
            
            for kw in strong_keywords:
                # If the user typed a "Strong" word (e.g. "Gatsby", "Moreau", "Hollow")
                if kw in normalized_query:
                    detected_by_python.append(fname)
                    break
        
        # If we found a specific strong match, override the LLM's "None"
        if detected_by_python:
            print(f"[RESCUE] LLM said None, but found strong keywords: {detected_by_python}")
            llm_raw = ",".join(detected_by_python)

    # === INTERCEPTOR: LIST FILES ===
    if "COMMAND_LIST" in llm_raw:
        # Execute list_files() directly here
        files = files_info.get("files", [])
        count = files_info.get("count", 0)

        if count == 0:
             return JSONResponse({"answer": "The database is empty.", "used_files": []})
        
        files.sort(key=lambda x: int(x.get("place", 0) or 0))

        # Build clean HTML list
        html_lines = [f"<h4>Found {count} file(s) in the database:</h4><ul>"]
        for f in files:
            fname = f.get("filename", "Unknown")
            pages = f.get("total_pages", "?")
            place = f.get("place", "?")
            html_lines.append(f"<li><strong>{fname}</strong> (Place: {place}, Pages: {pages})</li>")
        html_lines.append("</ul>")
        
        final_html = "".join(html_lines)
        return JSONResponse({"answer": final_html, "used_files": []})
    # === END INTERCEPTOR ===

    # === INTERCEPTOR: DELETE FILE ===
    if "COMMAND_DELETE:" in llm_raw:
        if user.get("role") != "admin":
            return JSONResponse({
                "answer": "I'm sorry, I cannot delete that file. You do not have administrator privileges.",
                "used_files": []
            })
        target_filename = llm_raw.replace("COMMAND_DELETE:", "").strip()
        
        # Verify the file actually exists in our current list
        files = files_info.get("files", [])
        matched_file_id = next((f["file_id"] for f in files if f["filename"] == target_filename), None)

        if not matched_file_id:
            return JSONResponse({"answer": f"I understood you want to delete '{target_filename}', but I couldn't find that exact file ID in the database."})

        try:
            result = await delete_file_func(matched_file_id)
            result_text = f"Deleted '{target_filename}'\n(File ID: {matched_file_id})\n\nRemaining files: {result.get('remaining_files', 0)}"
            return JSONResponse({"answer": f"<pre>{result_text}</pre>", "used_files": []})
        except Exception as e:
            return JSONResponse({"answer": f"Error deleting '{target_filename}': {str(e)}"})
    # === END INTERCEPTOR ===

    # Proceed with file targeting logic
    tokens = [t.strip() for t in llm_raw.split(",") if t.strip()]
    
    # --- ROBUST VALIDATION START ---
    valid = []
    # Create a map for case-insensitive lookup (Optimization)
    filename_map = {f.lower(): f for f in available_files}
    
    for t in tokens:
        # Exact match (Fastest)
        if t in available_files:
            valid.append(t)
        # Case-insensitive match (Handles "gatsby" vs "Gatsby")
        elif t.lower() in filename_map:
            valid.append(filename_map[t.lower()])
        # Fuzzy match (Handles "Sleepy Hollow" vs "The-Legend-of-...")
        else:
            # Use the in-memory list 'available_files', not a DB call
            closest = get_close_matches(t, available_files, n=1, cutoff=0.6)
            if closest:
                valid.append(closest[0])
    # --- ROBUST VALIDATION END ---

    # Handle "ALL_FILES" or fallbacks
    # Check if this is a "Compare Files" request vs a "Compare Pages" request
    is_global_compare = re.search(r"\b(all files|all documents)\b", query, re.IGNORECASE)
    
    # Only trigger 'compare' keyword if we didn't find specific page numbers
    # (If user says 'compare page 1 and 2', we should stick to the inferred file, not search all)
    if not page_num and not target_pages:
         if re.search(r"\b(compare|vs|versus|both)\b", query, re.IGNORECASE):
             is_global_compare = True

    if "ALL_FILES" in llm_raw or is_global_compare:
        if not valid:
            valid = available_files[:]

    # Heuristics if model returns None/empty
    if not valid:
        # Check for specific "All Files" request
        if re.search(r"\b(all files|all documents)\b", query, re.IGNORECASE):
            valid = available_files[:]
            
        # Check for "Compare" keyword
        elif re.search(r"\b(compare|vs|versus|both)\b", query, re.IGNORECASE):
            # CRITICAL FIX: If we have specific target pages, we are comparing PAGES, not FILES.
            # So we should use the ACTIVE file, not ALL files.
            if target_pages and active_file:
                valid = [active_file]
            else:
                # No pages specified? Then they probably mean "Compare File A vs File B" -> Search all
                valid = available_files[:]
                
        # Fallback: Just use the active file
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
    # Add optional page filter (supports multiple pages)
    if target_pages:
        # Build a massive OR condition for ALL targeted pages
        # Matches: (page=1 OR page="1" OR page=2 OR page="2"...)
        page_conditions = []
        for p in target_pages:
            page_conditions.append({"page": p})
            page_conditions.append({"page": str(p)})
            
        page_filter = {"$or": page_conditions}
        
        # Combine with existing file filters via AND
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
    query_embedding = await llm_client.get_embedding("page lookup" if page_num else query)

    # =========================================================================
    # MOVED UP: RUN RETRIEVAL FIRST
    # We query Chroma BEFORE rendering images so we know what to render
    # =========================================================================
    results = query_collection(
        query_embeddings=[query_embedding],
        where=filters if filters else None,
        n_results=10,
        include=["documents", "metadatas"]
    )
    
    # Extract results immediately so we can use them for Vision logic
    retrieved_metas = results.get("metadatas", [[]])[0]
    retrieved_docs = results.get("documents", [[]])[0]

    # Optional debug info (Moved here)
    print(f"\n[DEBUG] Filters applied: {filters or 'None'}")
    if matched_file:
        print(f"Matched file: {matched_file}")

    # =========================================================================
    # SMART VISION TRIGGER
    # KEYWORD RE-RANKING (Zero Token Cost)
    # We check the text of the top 5 results. If one mentions a "Figure" or "Drawing",
    # we prioritize it over a generic text page.
    # =========================================================================
    if not target_pages and retrieved_metas and retrieved_docs:
        candidates = []
        
        # Look at the top 5 results
        limit = min(5, len(retrieved_metas))
        
        for i in range(limit):
            meta = retrieved_metas[i]
            text = retrieved_docs[i] if i < len(retrieved_docs) else ""
            
            # 1. Base Score (Reverse Rank: #1 gets 5 points, #5 gets 1 point)
            score = limit - i
            
            # 2. Visual Bonus (The "Secret Sauce")
            # If the text mentions a diagram, it's highly likely the user wants to see it.
            if re.search(r"(figure|fig\.|drawing|diagram|schematic|exploded view)", text, re.IGNORECASE):
                score += 10  # Massive boost
                print(f"[RE-RANK] Boosting Page {meta.get('page')} (Score +10) due to visual keywords.")

            candidates.append({"meta": meta, "score": score})
        
        # Sort by Score (Descending)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        
        # Pick the winner
        top_candidate = candidates[0]["meta"]
        
        # --- Standard Logic Continues ---
        if top_candidate and "page" in top_candidate:
            detected_page = top_candidate["page"]
            detected_source = top_candidate.get("source")
            
            # Lock file context
            if not matched_file:
                matched_file = detected_source
            
            if matched_file == detected_source:
                print(f"[AUTO-VISION] Re-ranker selected Page {detected_page}")
                target_pages.append(int(detected_page))

    # =========================================================================
    # EXISTING LOGIC: RENDER IMAGES 
    # (Now uses the updated target_pages from above!)
    # =========================================================================
    page_images = [] # Store list of base64 images

    if target_pages and matched_file:
        uploads_dir = Path(__file__).resolve().parents[2] / "uploads"
        pdf_path = uploads_dir / matched_file

        if pdf_path.exists():
            for p in target_pages:
                try:
                    # Now returns a list (Top, Bottom)
                    image_slices = render_page_to_base64(str(pdf_path), p)
                    
                    if image_slices:
                        for i, b64_str in enumerate(image_slices):
                            page_images.append({
                                "page": p,
                                "b64": f"data:image/png;base64,{b64_str}",
                                "slice_index": i # Use to label "Top" vs "Bottom"
                            })
                        print(f"[VISION] Rendered {len(image_slices) - 1} slices for page {p}")
                    else:
                        print(f"[VISION] Could not render page {p}")
                except Exception as e:
                    print(f"[VISION ERROR] Page {p}: {e}")

    """
    # Query Chroma with these filters
    results = query_collection(
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
    """

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


    # --- VISION FALLBACK ---
    # If we found no text documents, but we HAVE a specific page image, 
    # it means the page exists in the PDF but was skipped in the DB (Image-Only).
    # We should proceed and let the LLM see the image.
    if not retrieved_docs:
        if page_images and matched_file:
            # Create a fake "retrieved doc" so the pipeline continues
            retrieved_docs = ["(No text found. Analyzing attached page image.)"]
            retrieved_metas = [{
                "source": matched_file,
                "file_id": to_file_id(matched_file),
                "page": page_num,
                "place": "unknown",
                "chunk_index": 0
            }]
            print(f"[VISION FALLBACK] Triggered for {matched_file} page {page_num}")
        else:
            return JSONResponse({"answer": "No relevant documents found."})
    # -----------------------

    # Get full file metadata via list_files route (smarter and consistent)
    files_info = await list_files()
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
    print("\nFile index summary:")
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

    # Strong system prompt instructing the model to pay attention to file headers
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
        "You are allowed to use your knowlege as a librarian and scholar when providing answers on themes, or in comparisons"

        "**STRICT FORMATTING RULES:**\n"
        "1. **Do NOT use numbered lists** for specifications. Use **Markdown Tables** for all data, dimensions, and part lists.\n"
        "2. **Use Bold Headers** for sections (e.g. `### Dimensions`).\n"
        "3. **Use Natural Paragraphs** for explanations. Do not break every sentence into a bullet point.\n"
        "4. **Grouping:** If you find a label (like 'A') and a value (like '38 inches'), keep them on the SAME line or in the SAME table row. Never split them into separate list items.\n"
        "5. **Citations:** When referencing a specific page, use bold text (e.g. **Page 12**).\n\n"
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

    # print(f"\n{user_prompt}\n")

    # Ask the LLM with the grouped context
    messages = [
        {"role": "system", "content": system_message},
    ]

    user_content = [
        {"type": "text", "text": user_prompt}
    ]

    # Add ALL rendered images
    for img_data in page_images:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": img_data["b64"]} 
        })
        
        # Determine label based on slice_index
        # Index 0 is the Full Page Map (added first in files_service)
        # Index 1 is Top Slice, Index 2 is Bottom Slice
        idx = img_data.get("slice_index", 0)
        
        if idx == 0:
            label = "FULL PAGE OVERVIEW (Low Res)"
            instruction = "Use this image to trace wires and understand the overall layout/topology. It preserves the complete paths."
        elif idx == 1:
            label = "TOP HALF DETAIL (High Res)"
            instruction = "Use this image to read small text labels (pin names, component values) in the top section."
        elif idx == 2:
            label = "BOTTOM HALF DETAIL (High Res)"
            instruction = "Use this image to read small text labels in the bottom section."
        elif idx == 3:
            label = "CENTER DETAIL (Best for Schematics)"
            instruction = "This slice captures the middle of the page intact. Use this primarily for diagrams that are centered to avoid cut wires."

        user_content.append({
            "type": "text", 
            "text": (
                f"(Attached Image: Page {img_data['page']} - {label}).\n"
                f"{instruction}\n"
                "**STRICT VISUAL ANALYSIS RULES:**\n"
                "1. **Topology:** Use the 'FULL PAGE OVERVIEW' to trace the wire path so you don't get lost at cut lines.\n"
                "2. **Reading:** You MUST use the 'DETAIL' views to identify specific component labels (like Rs, R1) that are too small to see in the Overview.\n"
                "3. **Connectivity Rules:**\n"
                "   - Wires crossing WITHOUT a dot are NOT connected.\n"
                "   - Wires meeting at a DOT are connected.\n"
                "   - **Do not skip components:** If a wire passes through a component symbol (like a resistor) on its way to the output, you must list that component.\n"
                "4. **Anti-Hallucination:** Do not connect components just because they are nearby (e.g. Rz, Cz). Only connect them if a wire clearly touches them."
            )
        })
    messages.append({"role": "user", "content": user_content})

    completion = await llm_client.chat(
        model="gpt-4o",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    # print(f"Initial Context\n{context}\nAdditional Prompting:\n{system_message}\n")

    # For traceability, also return which file IDs were included in the context
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
                files_info = await list_files()
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
        second_response = await llm_client.chat(
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

    # --- Remove sources for file listing queries ---
    # Detect if the user asked to list or show files
    is_file_listing_query = re.search(r"\b(list|show|what files|available files|which files)\b", query, re.IGNORECASE)

    if is_file_listing_query:
        # Skip source rendering entirely for these queries
        final_html = answer_html
        sources_list = []
    else:
        final_html = answer_html + sources_html

    # Update session memory
    update_session_memory(db, session_id, query, answer_markdown)

    return JSONResponse({
        "answer": final_html,
        "used_files": included_files,
        "sources": sources_list
    })
