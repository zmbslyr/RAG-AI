// app/static/script.js

// === GLOBAL STATE ===
let authToken = localStorage.getItem("authToken") || null;
let filesIndex = [];
let currentFile = null;

// === DOM LOADED ===
document.addEventListener("DOMContentLoaded", async () => {
  // 1. Setup UI references
  const loginModal   = document.getElementById("loginModal");
  const loginForm    = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");
  const registerLink = document.getElementById("registerLink");
  const backToLogin  = document.getElementById("backToLogin");
  
  const uploadForm   = document.getElementById("uploadForm");
  const askFormEl    = document.getElementById("askForm");
  const fileSelect   = document.getElementById("fileSelect");
  const dbSelect     = document.getElementById("dbSelect");
  const queryBox     = document.getElementById("query");
  const pdfViewer    = document.getElementById("pdfViewer");
  const uploadStatus = document.getElementById("uploadStatus");
  const processingContainer = document.getElementById("processingContainer");
  const chatLog      = document.getElementById("chatLog");

  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) {
      logoutBtn.addEventListener("click", () => {
          localStorage.removeItem("authToken");
          window.location.reload();
      });
  }

  // 2. Define Auth & Fetch Helpers
  window.authFetch = async function(url, options = {}) {
    const opts = { ...options, headers: { ...(options.headers || {}) } };
    if (authToken) opts.headers["Authorization"] = `Bearer ${authToken}`;
    
    const res = await fetch(url, opts);
    if (res.status === 401) {
      authToken = null;
      localStorage.removeItem("authToken");
      showLogin();
      throw new Error("Unauthorized");
    }
    return res;
  };

  function showLogin() { if (loginModal) loginModal.style.display = "flex"; }
  function hideLogin() { if (loginModal) loginModal.style.display = "none"; }

  function getUserRole() {
      if (!authToken) return null;
      try {
          const payload = JSON.parse(atob(authToken.split(".")[1]));
          return payload.role || "user";
      } catch {
          return "user";
      }
  }

  function applyRoleUI() {
    const role = getUserRole();
    const uploadSection = document.getElementById("upload-section");
    if (uploadSection) {
        uploadSection.style.display = (role === "admin") ? "grid" : "none"; // Note: grid for layout
    }
    const dbSection = document.getElementById("dbControlsSection");
    if (dbSection) {
      dbSection.style.display = (role === "admin") ? "flex" : "none";
    }
  }

  // 3. Database UI Logic
  async function loadDatabasesUI() {
    if (!dbSelect) return;
    try {
      const listRes = await window.authFetch("/databases");
      if (!listRes.ok) throw new Error("Failed to list databases");
      const listData = await listRes.json();
      
      const activeRes = await window.authFetch("/active_database");
      if (!activeRes.ok) throw new Error("Failed to get active database");
      const activeData = await activeRes.json();

      dbSelect.innerHTML = "";
      const dbs = listData.databases || [];
      
      if (dbs.length === 0) {
        const opt = document.createElement("option");
        opt.text = "Default";
        opt.value = "default";
        dbSelect.add(opt);
      } else {
        dbs.forEach(db => {
          const opt = document.createElement("option");
          opt.value = db;
          opt.textContent = db;
          dbSelect.appendChild(opt);
        });
      }

      dbSelect.value = activeData.active;

      dbSelect.onchange = async () => {
        const newDb = dbSelect.value;
        if (confirm(`Switch database to "${newDb}"? The page will reload.`)) {
           try {
             await window.authFetch(`/set_database?name=${newDb}`, { method: "POST" });
             window.location.reload();
           } catch (e) {
             alert("Error switching database: " + e.message);
           }
        } else {
           dbSelect.value = activeData.active;
        }
      };
    } catch (err) {
      console.error("Error loading databases:", err);
    }
  }

  // 4. Files & Viewer Logic
  async function refreshFiles() {
    try {
      const res = await window.authFetch("/list_files");
      const data = await res.json();

      const files = (data.files || []).filter(f => (f.filename || "").toLowerCase().endsWith(".pdf"));

      filesIndex = files;
      fileSelect.innerHTML = "";

      if (files.length === 0) {
        const opt = document.createElement("option");
        opt.textContent = "No PDFs uploaded";
        opt.disabled = true;
        opt.selected = true;
        fileSelect.appendChild(opt);
        pdfViewer.removeAttribute("src");
        currentFile = null;
      } else {
        files.forEach(f => {
          const opt = document.createElement("option");
          opt.value = f.filename;
          opt.textContent = f.filename;
          fileSelect.appendChild(opt);
        });
        if (!currentFile && files.length > 0) setViewer(files[0].filename);
      }
    } catch (e) {
      console.error("Failed to load files:", e);
    }
  }

  function setViewer(filename, page = 1) {
    if (!filename) return;
    currentFile = filename;
    const encoded = encodeURIComponent(filename);
    const timestamp = new Date().getTime();
    pdfViewer.src = `/uploads/${encoded}?t=${timestamp}#page=${page}`;
    
    if (fileSelect) {
        for (const opt of fileSelect.options) {
            if (opt.value === filename) opt.selected = true;
        }
    }
  }
  
  window.openInViewer = function(filename, page) { setViewer(filename, page); };

  // 5. Event Listeners
  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const u = document.getElementById("loginUsername").value;
      const p = document.getElementById("loginPassword").value;
      const body = new URLSearchParams();
      body.append("username", u); body.append("password", p);

      const res = await fetch("/auth/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
      const data = await res.json();
      
      if (res.ok && data.access_token) {
        authToken = data.access_token;
        localStorage.setItem("authToken", authToken);
        hideLogin();
        applyRoleUI();
        loadDatabasesUI();
        refreshFiles();
      } else {
        alert(data.detail || "Login failed");
      }
    });
  }

  if (registerForm) {
    registerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const u = document.getElementById("registerUsername").value;
      const p = document.getElementById("registerPassword").value;
      const res = await fetch("/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
      if (res.ok) {
        alert("Registered! Please login.");
        registerForm.style.display = "none";
        loginForm.style.display = "block";
      } else {
        alert("Registration failed");
      }
    });
  }
  
  if (registerLink) registerLink.onclick = (e) => { e.preventDefault(); loginForm.style.display="none"; registerForm.style.display="block"; };
  if (backToLogin) backToLogin.onclick = (e) => { e.preventDefault(); registerForm.style.display="none"; loginForm.style.display="block"; };

  if (uploadForm) {
    uploadForm.onsubmit = async (e) => {
      e.preventDefault();
      const fileInput = document.getElementById("pdfFile");
      const file = fileInput.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append("file", file);
      
      processingContainer.style.display = "flex";
      uploadStatus.textContent = "";
      uploadForm.querySelector("button").disabled = true;

      try {
        const res = await window.authFetch("/upload", { method: "POST", body: formData });
        const data = await res.json();
        uploadStatus.textContent = data.message || "Uploaded.";
        await refreshFiles();
        if (file.name.toLowerCase().endsWith(".pdf")) setViewer(file.name);
      } catch (err) {
        uploadStatus.textContent = "Upload failed.";
      } finally {
        processingContainer.style.display = "none";
        uploadForm.querySelector("button").disabled = false;
        fileInput.value = "";
      }
    };
  }

  if (askFormEl) {
    askFormEl.onsubmit = async (e) => {
      e.preventDefault();
      const q = queryBox.value.trim();
      if (!q) return;
      
      // Add User Message
      appendMessage("user", q);
      queryBox.value = "";
      queryBox.style.height = "auto"; // reset height

      // Add Thinking Placeholder
      appendThinkingMessage();

      const formData = new FormData();
      formData.append("query", q);

      try {
        const res = await window.authFetch("/ask", { method: "POST", body: formData });
        const data = await res.json();
        removeLastAssistantMessage();
        appendMessage("assistant", data.answer);
      } catch {
        removeLastAssistantMessage();
        appendMessage("assistant", "Error getting response.");
      }
    };
  }
  
  fileSelect.onchange = () => setViewer(fileSelect.value);

  // === CHAT UI FUNCTIONS ===
  
  function appendMessage(role, html) {
    const isUser = role === "user";
    const avatarLabel = isUser ? "You" : "AI";
    const avatarClass = isUser ? "user-avatar" : "ai-avatar";

    // Build the "Row" structure
    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    row.innerHTML = `
      <div class="message-inner">
        <div class="avatar ${avatarClass}">${isUser ? "U" : "AI"}</div>
        <div class="message-content">${html}</div>
      </div>
    `;

    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function appendThinkingMessage() {
    const row = document.createElement("div");
    row.className = "message-row assistant thinking-row";
    row.innerHTML = `
      <div class="message-inner">
        <div class="avatar ai-avatar">AI</div>
        <div class="message-content">Thinking<span class="thinking-dots"></span></div>
      </div>
    `;
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function removeLastAssistantMessage() {
    // Find the last row that is an assistant row
    const rows = chatLog.getElementsByClassName("message-row");
    for (let i = rows.length - 1; i >= 0; i--) {
      if (rows[i].classList.contains("assistant")) {
        rows[i].remove();
        break;
      }
    }
  }

  // Click delegation for chat links
  if (chatLog) {
      chatLog.addEventListener("click", (e) => {
        const a = e.target.closest("a.open-in-viewer");
        if (a) {
            e.preventDefault();
            window.openInViewer(a.dataset.file, a.dataset.page);
        }
      });
  }
  
  // Auto-resize query box
  queryBox.oninput = () => {
      queryBox.style.height = "auto";
      queryBox.style.height = Math.min(queryBox.scrollHeight, 200) + "px";
  };
  queryBox.onkeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          askFormEl.requestSubmit();
      }
  };

  // Init
  if (!authToken) {
    showLogin();
  } else {
    applyRoleUI();
    loadDatabasesUI();
    refreshFiles();
  }
});
