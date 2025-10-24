const uploadForm = document.getElementById("uploadForm");
const pdfFile = document.getElementById("pdfFile");
const uploadStatus = document.getElementById("uploadStatus");
const uploadButton = uploadForm.querySelector("button");
const askForm = document.getElementById("askForm");
const chatLog = document.getElementById("chatLog");

// --- Handle file upload with spinner ---
uploadForm.onsubmit = async (e) => {
  e.preventDefault();
  const file = pdfFile.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  // Show spinner and processing text
  processingContainer.style.display = "flex";
  uploadStatus.textContent = "";
  uploadButton.disabled = true;

  try {
    const res = await fetch("/upload", { method: "POST", body: formData });
    const data = await res.json();
    uploadStatus.textContent = data.message;
  } catch {
    uploadStatus.textContent = "Upload failed.";
  } finally {
    processingContainer.style.display = "none";
    uploadButton.disabled = false; // re-enable button after processing
  }
};

// --- Chat Interface ---
askForm.onsubmit = async (e) => {
  e.preventDefault();
  const queryInput = document.getElementById("query");
  const query = queryInput.value.trim();
  if (!query) return;

  appendMessage("user", query);
  queryInput.value = "";

  appendMessage("assistant", "Thinking...");

  const formData = new FormData();
  formData.append("query", query);

  try {
    const res = await fetch("/ask", { method: "POST", body: formData });
    const data = await res.json();

    // Remove "Thinking..." and add the real response
    removeLastAssistantMessage();
    appendMessage("assistant", data.answer);
  } catch {
    removeLastAssistantMessage();
    appendMessage("assistant", "Error getting response.");
  }
};

function appendMessage(role, text) {
  const msg = document.createElement("div");
  msg.className = `message ${role}`;
  msg.innerHTML = `<div class="bubble">${text}</div>`;
  chatLog.appendChild(msg);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function removeLastAssistantMessage() {
  const messages = chatLog.getElementsByClassName("message");
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].classList.contains("assistant")) {
      messages[i].remove();
      break;
    }
  }
}
