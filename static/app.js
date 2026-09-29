// ============================================================
//  Configuration
//  Backend FastAPI : /api/v1/questions et /api/v1/documents
//  APP_API_KEY est vide dans .env → aucun header X-API-Key
// ============================================================
const API_URL = "/api/v1/questions";
const DOCS_URL = "/api/v1/documents";
const API_KEY = "";  // mettre la clé si APP_API_KEY est activée plus tard

// ============================================================
//  Historique des conversations (local au navigateur)
// ============================================================
const CONVOS_KEY = "vodacom_conversations";
const ACTIVE_CONVO_KEY = "vodacom_active_convo";

function loadConversations() {
  try { return JSON.parse(localStorage.getItem(CONVOS_KEY)) || []; }
  catch { return []; }
}
function saveConversations(c) { localStorage.setItem(CONVOS_KEY, JSON.stringify(c)); }
function getActiveConvoId() { return localStorage.getItem(ACTIVE_CONVO_KEY); }
function setActiveConvoId(id) { localStorage.setItem(ACTIVE_CONVO_KEY, id); }

function createConversation() {
  const id = "convo-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now();
  const convo = {
    id,
    title: "Nouvelle conversation",
    messages: [],
    created_at: Date.now(),
    updated_at: Date.now(),
  };
  const convos = loadConversations();
  convos.unshift(convo);
  saveConversations(convos);
  setActiveConvoId(id);
  return convo;
}

function getActiveConversation() {
  return loadConversations().find((c) => c.id === getActiveConvoId()) || null;
}

function appendMessageToConvo(id, message) {
  const convos = loadConversations();
  const idx = convos.findIndex((c) => c.id === id);
  if (idx === -1) return;
  convos[idx].messages.push({ ...message, ts: Date.now() });
  convos[idx].updated_at = Date.now();
  if (message.role === "user" && convos[idx].title === "Nouvelle conversation") {
    convos[idx].title = message.text.slice(0, 40) + (message.text.length > 40 ? "…" : "");
  }
  saveConversations(convos);
}

// ============================================================
//  DOM
// ============================================================
const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const sendBtn = form.querySelector("button[type='submit']");
const conversationsEl = document.getElementById("conversations");
const btnNewChat = document.getElementById("btn-new-chat");
const sidebar = document.getElementById("sidebar");
const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");
const documentsEl = document.getElementById("documents");
const btnUpload = document.getElementById("btn-upload");
const fileInput = document.getElementById("file-input");

const modalReplace = document.getElementById("modal-replace");
const modalDelete = document.getElementById("modal-delete");
const replaceDocName = document.getElementById("replace-doc-name");
const deleteDocName = document.getElementById("delete-doc-name");
const btnReplacePick = document.getElementById("btn-replace-pick");
const btnReplaceCancel = document.getElementById("btn-replace-cancel");
const btnDeleteCancel = document.getElementById("btn-delete-cancel");
const btnDeleteConfirm = document.getElementById("btn-delete-confirm");
const replaceFileInput = document.getElementById("replace-file-input");

let activeConvo = getActiveConversation();
if (!activeConvo) activeConvo = createConversation();

// ============================================================
//  Helpers HTTP
// ============================================================
function authHeaders(extra = {}) {
  const h = { ...extra };
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}

async function extractError(res) {
  let detail = `HTTP ${res.status}`;
  try {
    const data = await res.json();
    if (typeof data.detail === "string") detail = data.detail;
    else if (data.detail) detail = JSON.stringify(data.detail);
  } catch {}
  return detail;
}

// ============================================================
//  Documents (sidebar)
// ============================================================
let selectedDocId = null;
let documentsCache = [];
const docDetailsCache = new Map();

function renderDocuments() {
  documentsEl.innerHTML = "";

  if (documentsCache.length === 0) {
    const empty = document.createElement("div");
    empty.className = "documents-empty";
    empty.textContent = "Aucun document indexé";
    documentsEl.appendChild(empty);
    return;
  }

  documentsCache.forEach((doc) => {
    const item = document.createElement("div");
    item.className = "document-item" + (doc.id === selectedDocId ? " selected" : "");
    item.title = `${doc.filename} — ${doc.page_count} page(s)`;

    item.addEventListener("mouseenter", async () => {
      const detail = await fetchDocumentDetail(doc.id);
      if (detail) {
        const uploaded = detail.uploaded_at?.replace("T", " ").slice(0, 16) ?? "?";
        item.title =
          `${detail.filename}\n` +
          `${detail.page_count} page(s) · ${detail.chunk_count} chunk(s)\n` +
          `Version ${detail.version} · uploadé le ${uploaded}\n` +
          `SHA-256 : ${detail.sha256.slice(0, 16)}…`;
      }
    });

    const icon = document.createElement("span");
    icon.className = "doc-icon";
    icon.textContent = "📄";

    const name = document.createElement("span");
    name.className = "doc-name";
    name.textContent = doc.filename;

    const pages = document.createElement("span");
    pages.className = "doc-pages";
    pages.textContent = `${doc.page_count}p`;

    const actions = document.createElement("div");
    actions.className = "doc-actions";

    const btnReplace = document.createElement("button");
    btnReplace.className = "doc-action-btn";
    btnReplace.title = "Remplacer ce PDF";
    btnReplace.textContent = "↻";
    btnReplace.addEventListener("click", (e) => {
      e.stopPropagation();
      openReplaceModal(doc);
    });

    const btnDelete = document.createElement("button");
    btnDelete.className = "doc-action-btn danger";
    btnDelete.title = "Supprimer ce PDF";
    btnDelete.textContent = "✕";
    btnDelete.addEventListener("click", (e) => {
      e.stopPropagation();
      openDeleteModal(doc);
    });

    actions.appendChild(btnReplace);
    actions.appendChild(btnDelete);

    item.appendChild(icon);
    item.appendChild(name);
    item.appendChild(pages);
    item.appendChild(actions);

    item.addEventListener("click", () => {
      selectedDocId = selectedDocId === doc.id ? null : doc.id;
      renderDocuments();
      renderScopeBar();
    });

    documentsEl.appendChild(item);
  });
}

function renderScopeBar() {
  let bar = document.getElementById("scope-bar");
  if (!selectedDocId) {
    if (bar) bar.remove();
    return;
  }
  const doc = documentsCache.find((d) => d.id === selectedDocId);
  const label = doc ? doc.filename : selectedDocId.slice(0, 8);

  if (!bar) {
    bar = document.createElement("div");
    bar.id = "scope-bar";
    bar.className = "scope-bar";
    messagesEl.parentElement.insertBefore(bar, messagesEl);
  }
  bar.innerHTML = "";
  const chip = document.createElement("span");
  chip.className = "scope-chip";
  chip.textContent = `📄 ${label}`;
  const clear = document.createElement("button");
  clear.className = "scope-clear";
  clear.textContent = "Tout interroger";
  clear.addEventListener("click", () => {
    selectedDocId = null;
    renderDocuments();
    renderScopeBar();
  });
  bar.appendChild(chip);
  bar.appendChild(clear);
}

async function refreshDocuments() {
  try {
    const res = await fetch(`${DOCS_URL}?limit=50`, { headers: authHeaders() });
    if (!res.ok) throw new Error(await extractError(res));
    const data = await res.json();
    documentsCache = data.items || [];
    if (selectedDocId && !documentsCache.some((d) => d.id === selectedDocId)) {
      selectedDocId = null;
    }
    renderDocuments();
    renderScopeBar();
  } catch (err) {
    console.warn("Impossible de charger les documents :", err);
    documentsEl.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "documents-empty";
    empty.textContent = "Erreur de chargement";
    documentsEl.appendChild(empty);
  }
}

// ---------- GET /api/v1/documents/{id} ----------
async function fetchDocumentDetail(docId) {
  if (docDetailsCache.has(docId)) return docDetailsCache.get(docId);
  try {
    const res = await fetch(`${DOCS_URL}/${docId}`, { headers: authHeaders() });
    if (!res.ok) return null;
    const data = await res.json();
    docDetailsCache.set(docId, data);
    return data;
  } catch {
    return null;
  }
}

// ---------- POST /api/v1/documents (upload) ----------
btnUpload.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;

  if (!file.name.toLowerCase().endsWith(".pdf")) {
    alert("Seuls les fichiers .pdf sont acceptés.");
    fileInput.value = "";
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    alert("Fichier trop volumineux (10 Mo maximum).");
    fileInput.value = "";
    return;
  }

  btnUpload.disabled = true;
  const original = btnUpload.innerHTML;
  btnUpload.innerHTML = "…";

  try {
    const formData = new FormData();
    formData.append("file", file, file.name);

    const res = await fetch(DOCS_URL, {
      method: "POST",
      headers: authHeaders(),
      body: formData,
    });

    if (!res.ok) throw new Error(await extractError(res));

    const doc = await res.json();
    console.log("Document ajouté :", doc);

    await refreshDocuments();
    selectedDocId = doc.id;
    renderDocuments();
    renderScopeBar();
  } catch (err) {
    alert("❌ Erreur upload : " + err.message);
  } finally {
    btnUpload.disabled = false;
    btnUpload.innerHTML = original;
    fileInput.value = "";
  }
});

// ============================================================
//  PUT /api/v1/documents/{id} — Remplacer un PDF
// ============================================================
let docToReplace = null;

function openReplaceModal(doc) {
  docToReplace = doc;
  replaceDocName.textContent = doc.filename;
  modalReplace.hidden = false;
}

btnReplaceCancel.addEventListener("click", () => {
  modalReplace.hidden = true;
  docToReplace = null;
});

btnReplacePick.addEventListener("click", () => replaceFileInput.click());

replaceFileInput.addEventListener("change", async () => {
  const file = replaceFileInput.files[0];
  if (!file || !docToReplace) return;

  if (!file.name.toLowerCase().endsWith(".pdf")) {
    alert("Seuls les fichiers .pdf sont acceptés.");
    replaceFileInput.value = "";
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    alert("Fichier trop volumineux (10 Mo maximum).");
    replaceFileInput.value = "";
    return;
  }

  btnReplacePick.disabled = true;
  const original = btnReplacePick.textContent;
  btnReplacePick.textContent = "Remplacement…";

  const targetId = docToReplace.id;

  try {
    const formData = new FormData();
    formData.append("file", file, file.name);

    const res = await fetch(`${DOCS_URL}/${targetId}`, {
      method: "PUT",
      headers: authHeaders(),
      body: formData,
    });

    if (!res.ok) throw new Error(await extractError(res));

    const updated = await res.json();
    console.log("Document remplacé :", updated);

    modalReplace.hidden = true;
    docToReplace = null;

    docDetailsCache.delete(targetId);

    await refreshDocuments();
    selectedDocId = targetId;
    renderDocuments();
    renderScopeBar();

    if (activeConvo) {
      const bubble = addMessage(
        "assistant",
        `📄 Le document « ${updated.filename} » a été remplacé (version ${updated.version}).`,
        true
      );
      bubble.style.fontStyle = "italic";
      bubble.style.color = "var(--text-muted)";
    }
  } catch (err) {
    alert("❌ Erreur remplacement : " + err.message);
  } finally {
    btnReplacePick.disabled = false;
    btnReplacePick.textContent = original;
    replaceFileInput.value = "";
  }
});

// ============================================================
//  DELETE /api/v1/documents/{id} — Supprimer un PDF
// ============================================================
let docToDelete = null;

function openDeleteModal(doc) {
  docToDelete = doc;
  deleteDocName.textContent = doc.filename;
  modalDelete.hidden = false;
}

btnDeleteCancel.addEventListener("click", () => {
  modalDelete.hidden = true;
  docToDelete = null;
});

btnDeleteConfirm.addEventListener("click", async () => {
  if (!docToDelete) return;
  const target = docToDelete;

  btnDeleteConfirm.disabled = true;
  btnDeleteConfirm.textContent = "Suppression…";

  try {
    const res = await fetch(`${DOCS_URL}/${target.id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });

    if (!res.ok && res.status !== 204) {
      throw new Error(await extractError(res));
    }

    console.log("Document supprimé :", target.id);

    modalDelete.hidden = true;
    docToDelete = null;

    if (selectedDocId === target.id) selectedDocId = null;
    docDetailsCache.delete(target.id);

    await refreshDocuments();

    if (activeConvo) {
      const bubble = addMessage(
        "assistant",
        `🗑️ Le document « ${target.filename} » a été supprimé.`,
        true
      );
      bubble.style.fontStyle = "italic";
      bubble.style.color = "var(--text-muted)";
    }
  } catch (err) {
    alert("❌ Erreur suppression : " + err.message);
  } finally {
    btnDeleteConfirm.disabled = false;
    btnDeleteConfirm.textContent = "Supprimer";
  }
});

// Fermer les modales en cliquant sur le fond
modalReplace.addEventListener("click", (e) => {
  if (e.target === modalReplace) { modalReplace.hidden = true; docToReplace = null; }
});
modalDelete.addEventListener("click", (e) => {
  if (e.target === modalDelete) { modalDelete.hidden = true; docToDelete = null; }
});

// ============================================================
//  Sidebar : historique des conversations
// ============================================================
function renderConversations() {
  const convos = loadConversations();
  conversationsEl.innerHTML = "";

  if (convos.length === 0) {
    const empty = document.createElement("div");
    empty.className = "conversation-item";
    empty.style.color = "var(--text-muted)";
    empty.style.cursor = "default";
    empty.textContent = "Aucune conversation";
    conversationsEl.appendChild(empty);
    return;
  }

  const activeId = getActiveConvoId();
  convos.forEach((c) => {
    const item = document.createElement("div");
    item.className = "conversation-item" + (c.id === activeId ? " active" : "");

    const dot = document.createElement("span");
    dot.className = "dot";

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = c.title;

    item.appendChild(dot);
    item.appendChild(label);
    item.addEventListener("click", () => switchConversation(c.id));
    conversationsEl.appendChild(item);
  });
}

function renderMessages(convo) {
  messagesEl.innerHTML = "";
  if (!convo) return;
  convo.messages.forEach((m) => {
    const bubble = addMessage(m.role, m.text, false);
    if (m.sources?.length) renderSources(bubble, m.sources);
    if (m.warning) renderWarning(bubble, m.warning);
    if (m.mode === "no_evidence") {
      bubble.style.fontStyle = "italic";
      bubble.style.color = "var(--text-muted)";
    }
  });
}

function switchConversation(id) {
  setActiveConvoId(id);
  activeConvo = getActiveConversation();
  renderMessages(activeConvo);
  renderConversations();
}

btnNewChat.addEventListener("click", () => {
  activeConvo = createConversation();
  renderMessages(activeConvo);
  renderConversations();
  input.focus();
});

btnToggleSidebar.addEventListener("click", () => {
  sidebar.classList.toggle("collapsed");
});

// ============================================================
//  Messages
// ============================================================
function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

function addMessage(role, text = "", persist = true) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "V";
    wrapper.appendChild(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  scrollToBottom();

  if (persist && activeConvo) {
    appendMessageToConvo(activeConvo.id, { role, text });
    renderConversations();
  }

  return bubble;
}

function renderSources(bubble, sources) {
  const list = document.createElement("div");
  list.className = "sources";
  list.style.marginTop = "12px";
  list.style.paddingTop = "10px";
  list.style.borderTop = "1px solid var(--border)";
  list.style.fontSize = "12px";
  list.style.color = "var(--text-muted)";

  sources.forEach((s) => {
    const line = document.createElement("div");
    line.style.marginBottom = "6px";
    const pages = s.page_end && s.page_end !== s.page
      ? `pages ${s.page}-${s.page_end}`
      : `page ${s.page}`;
    line.innerHTML = `<strong>[${s.reference}]</strong> ${s.filename} — ${pages}`;
    list.appendChild(line);
  });

  bubble.appendChild(list);
}

function renderWarning(bubble, warning) {
  const warn = document.createElement("div");
  warn.style.marginTop = "8px";
  warn.style.fontSize = "12px";
  warn.style.color = "#b45309";
  warn.textContent = "⚠️ " + warning;
  bubble.appendChild(warn);
}

function setLoading(loading) {
  input.disabled = loading;
  sendBtn.disabled = loading;
  if (!loading) input.focus();
}

// ============================================================
//  Envoi d'une question
// ============================================================
form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const text = input.value.trim();
  if (!text) return;

  addMessage("user", text);
  input.value = "";
  setLoading(true);

  const bubble = addMessage("assistant", "…", false);

  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        question: text,
        document_ids: selectedDocId ? [selectedDocId] : null,
        top_k: 4,
      }),
    });

    if (!res.ok) throw new Error(await extractError(res));

    const data = await res.json();

    bubble.textContent = data.answer ?? "(réponse vide)";

    if (Array.isArray(data.sources) && data.sources.length > 0) {
      renderSources(bubble, data.sources);
    }
    if (data.warning) {
      renderWarning(bubble, data.warning);
    }
    if (data.response_mode === "no_evidence") {
      bubble.style.fontStyle = "italic";
      bubble.style.color = "var(--text-muted)";
    }

    appendMessageToConvo(activeConvo.id, {
      role: "assistant",
      text: data.answer ?? "",
      sources: data.sources ?? [],
      warning: data.warning ?? null,
      mode: data.response_mode,
    });

    console.log("Mode   :", data.response_mode);
    console.log("Sources:", data.sources);
  } catch (err) {
    bubble.textContent = "❌ " + err.message;
    bubble.style.color = "#b91c1c";
    appendMessageToConvo(activeConvo.id, {
      role: "assistant",
      text: "❌ " + err.message,
    });
  } finally {
    setLoading(false);
    scrollToBottom();
  }
});

// ============================================================
//  Init
// ============================================================
renderConversations();
renderMessages(activeConvo);
refreshDocuments();
input.focus();