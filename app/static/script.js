// ------- Elements -------
const uploadForm = document.getElementById("uploadForm");
const pdfFile = document.getElementById("pdfFile");
const uploadStatus = document.getElementById("uploadStatus");
const askForm = document.getElementById("askForm");
const chatLog = document.getElementById("chatLog");
const processingContainer = document.getElementById("processingContainer");

// Viewer elements
const fileSelect = document.getElementById("fileSelect");
const pdfViewer = document.getElementById("pdfViewer");
const askPageBtn = document.getElementById("askPageBtn");

// Query box for auto-resize + enter-to-send
const queryBox = document.getElementById("query");

// ------- State -------
let filesIndex = []; // [{ filename, file_id, total_pages, place }]
let currentFile = null;

// ------- Helpers -------
function setViewer(filename) {
  if (!filename) return;
  currentFile = filename;

  // Use the browser's native PDF viewer (simple & fast); page param supported by most
  pdfViewer.src = `/uploads/${encodeURIComponent(filename)}`;
  pageInput.value = page || 1;
  // Keep the select in sync
  for (const opt of fileSelect.options) {
    opt.selected = (opt.value === filename);
  }
}

async function refreshFiles() {
  try {
    const res = await fetch("/list_files");
    const data = await res.json();

    const files = (data.files || [])
      .filter(f => (f.filename || "").toLowerCase().endsWith(".pdf"))
      .map(f => ({
        filename: f.filename,
        file_id: f.file_id,
        total_pages: f.total_pages || null,
        place: f.place || null
      }));

    filesIndex = files;

    // Populate dropdown
    fileSelect.innerHTML = "";
    if (files.length === 0) {
      const opt = document.createElement("option");
      opt.textContent = "No PDFs uploaded yet";
      opt.disabled = true;
      opt.selected = true;
      fileSelect.appendChild(opt);
      pdfViewer.removeAttribute("src");
      return;
    }

    files.forEach((f, i) => {
      const opt = document.createElement("option");
      opt.value = f.filename;
      opt.textContent = f.filename;
      fileSelect.appendChild(opt);
    });

    // If nothing selected yet, show the first file
    if (!currentFile) setViewer(files[0].filename);
  } catch (e) {
    console.error("Failed to load files:", e);
  }
}

function appendMessage(role, text) {
  const msg = document.createElement("div");
  msg.className = `message ${role}`;
  msg.innerHTML = `<div class="bubble">${text}</div>`;
  chatLog.appendChild(msg);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function appendThinkingMessage() {
  const msg = document.createElement("div");
  msg.className = "message assistant";
  msg.innerHTML = `<div class="bubble">Thinking<span class="thinking-dots"></span></div>`;
  chatLog.appendChild(msg);
  chatLog.scrollTop = chatLog.scrollHeight;

  let dotCount = 0;
  const interval = setInterval(() => {
    dotCount = (dotCount + 1) % 4;
    const dots = msg.querySelector(".thinking-dots");
    if (dots) dots.textContent = ".".repeat(dotCount);
  }, 400);

  msg.dotInterval = interval;
  return msg;
}

function removeLastAssistantMessage() {
  const messages = chatLog.getElementsByClassName("message");
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.classList.contains("assistant")) {
      if (msg.dotInterval) clearInterval(msg.dotInterval);
      msg.remove();
      break;
    }
  }
}

// ------- Upload flow -------
uploadForm.onsubmit = async (e) => {
  e.preventDefault();
  const file = pdfFile.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  // Show spinner and processing text
  processingContainer.style.display = "flex";
  uploadStatus.textContent = "";
  uploadForm.querySelector("button").disabled = true;

  try {
    const res = await fetch("/upload", { method: "POST", body: formData });
    const data = await res.json();
    uploadStatus.textContent = data.message || "Uploaded.";
    // Refresh list and display the just-uploaded file (if it's a PDF)
    await refreshFiles();
    if (file.name.toLowerCase().endsWith(".pdf")) {
      setViewer(file.name, 1);
    }
  } catch (err) {
    console.error(err);
    uploadStatus.textContent = "Upload failed.";
  } finally {
    processingContainer.style.display = "none";
    uploadForm.querySelector("button").disabled = false;
    pdfFile.value = "";
  }
};

// ------- Chat flow -------
const askFormEl = document.getElementById("askForm");
askFormEl.onsubmit = async (e) => {
  e.preventDefault();
  const queryInput = document.getElementById("query");
  const query = queryInput.value.trim();
  if (!query) return;

  appendMessage("user", query);
  queryInput.value = "";

  appendThinkingMessage();

  const formData = new FormData();
  formData.append("query", query);

  try {
    const res = await fetch("/ask", { method: "POST", body: formData });
    const data = await res.json();
    removeLastAssistantMessage();
    appendMessage("assistant", data.answer);
  } catch {
    removeLastAssistantMessage();
    appendMessage("assistant", "Error getting response.");
  }
};

// Auto-resize textarea + Enter submit
queryBox.addEventListener("input", () => {
  queryBox.style.height = "auto";
  queryBox.style.height = Math.min(queryBox.scrollHeight, 120) + "px";
});

queryBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    askForm.requestSubmit();
  }
});

// ------- Viewer controls -------
fileSelect.addEventListener("change", () => {
  const filename = fileSelect.value;
  setViewer(filename, 1);
});

// ------- Init -------
window.addEventListener("DOMContentLoaded", async () => {
  await refreshFiles();
  if (fileSelect.options.length > 0) {
    const firstFile = fileSelect.options[0].value;
    setViewer(firstFile);
  }
});
