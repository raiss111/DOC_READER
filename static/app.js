// ============================================================
//  Configuration
// ============================================================
const API_URL = "/api/v1/questions";
const DOCS_URL = "/api/v1/documents";
const API_KEY = "";

// ============================================================
//  Icônes SVG
// ============================================================
const ICONS = {
  file: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <polyline points="14 2 14 8 20 8"/>
  </svg>`,

  trash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="3 6 5 6 21 6"/>
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
    <path d="M10 11v6M14 11v6"/>
    <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
  </svg>`,

  copy: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
  </svg>`,

  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </svg>`,

  link: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
  </svg>`,
};

// ============================================================
//  Conversation active (une seule, garde le titre auto)
// ============================================================
const CONVO_KEY = "vodacom_convo";

function loadConversation() {
  try { return JSON.parse(localStorage.getItem(CONVO_KEY)) || null; }
  catch { return null; }
}
function saveConversation(c) { localStorage.setItem(CONVO_KEY, JSON.stringify(c)); }

function createConversation() {
  const convo = {
    id: "convo-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now(),
    title: "Nouvelle conversation",
    messages: [],
    created_at: Date.now(),
    updated_at: Date.now(),
  };
  saveConversation(convo);
  return convo;
}

function appendMessageToConvo(message) {
  const convo = loadConversation();
  if (!convo) return;
  convo.messages.push({ ...message, ts: Date.now() });
  convo.updated_at = Date.now();
  saveConversation(convo);
}

let activeConvo = loadConversation();
if (!activeConvo) activeConvo = createConversation();

// ============================================================
//  DOM
// ============================================================
const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const sendBtn = form.querySelector("button[type='submit']");
const btnNewChat = document.getElementById("btn-new-chat");
const sidebar = document.getElementById("sidebar");
const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");

const btnOpenDocs = document.getElementById("btn-open-docs");
const docsCount = document.getElementById("docs-count");

const modalDocs = document.getElementById("modal-docs");
const docsList = document.getElementById("docs-list");
const btnDocsAdd = document.getElementById("btn-docs-add");
const btnDocsClose = document.getElementById("btn-docs-close");

const btnPlus = document.getElementById("btn-plus");
const actionMenu = document.getElementById("action-menu");
const btnAddFile = document.getElementById("btn-add-file");
const fileInput = document.getElementById("file-input");

const modalFormat = document.getElementById("modal-format");
const modalToolarge = document.getElementById("modal-toolarge");
const formatFileName = document.getElementById("format-file-name");
const toolargeFileName = document.getElementById("toolarge-file-name");
const btnFormatOk = document.getElementById("btn-format-ok");
const btnToolargeOk = document.getElementById("btn-toolarge-ok");

const modalDelete = document.getElementById("modal-delete");
const deleteDocName = document.getElementById("delete-doc-name");
const btnDeleteCancel = document.getElementById("btn-delete-cancel");
const btnDeleteConfirm = document.getElementById("btn-delete-confirm");

// ============================================================
//  Helpers
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
//  Documents
// ============================================================
let selectedDocId = null;
let documentsCache = [];

function updateDocsCount() {
  docsCount.textContent = documentsCache.length;
}

function renderDocsModalList() {
  docsList.innerHTML = "";

  if (documentsCache.length === 0) {
    const empty = document.createElement("div");
    empty.className = "docs-empty";
    empty.textContent = "Aucun document indexé";
    docsList.appendChild(empty);
    return;
  }

  documentsCache.forEach((doc) => {
    const row = document.createElement("div");
    row.className = "doc-row";

    const icon = document.createElement("span");
    icon.className = "doc-row-icon";
    icon.innerHTML = ICONS.file;

    const body = document.createElement("div");
    body.className = "doc-row-body";

    const name = document.createElement("div");
    name.className = "doc-row-name";
    name.textContent = doc.filename;
    name.title = doc.filename;

    const meta = document.createElement("div");
    meta.className = "doc-row-meta";
    meta.textContent = `${doc.page_count} page(s) · ${doc.chunk_count} chunk(s)`;

    body.appendChild(name);
    body.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "doc-row-actions";

    const btnTrash = document.createElement("button");
    btnTrash.className = "doc-row-btn danger";
    btnTrash.title = "Supprimer ce PDF";
    btnTrash.innerHTML = ICONS.trash;
    btnTrash.addEventListener("click", (e) => {
      e.stopPropagation();
      openDeleteModal(doc);
    });
    actions.appendChild(btnTrash);

    row.appendChild(icon);
    row.appendChild(body);
    row.appendChild(actions);

    // Clic sur la ligne = sélectionner / désélectionner
    row.addEventListener("click", () => {
      selectedDocId = selectedDocId === doc.id ? null : doc.id;
      renderDocsModalList();
      renderScopeBar();
    });

    if (doc.id === selectedDocId) {
      row.style.background = "var(--primary-soft)";
    }

    docsList.appendChild(row);
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
  chip.innerHTML = ICONS.file + `<span>${label}</span>`;
  const clear = document.createElement("button");
  clear.className = "scope-clear";
  clear.textContent = "Tout interroger";
  clear.addEventListener("click", () => {
    selectedDocId = null;
    renderDocsModalList();
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
    updateDocsCount();
    renderDocsModalList();
    renderScopeBar();
  } catch (err) {
    console.warn("Impossible de charger les documents :", err);
    documentsCache = [];
    updateDocsCount();
    docsList.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "docs-empty";
    empty.textContent = "Erreur de chargement";
    docsList.appendChild(empty);
  }
}

// ============================================================
//  Modal Documents
// ============================================================
function openDocsModal() {
  renderDocsModalList();
  modalDocs.hidden = false;
}
function closeDocsModal() {
  modalDocs.hidden = true;
}

btnOpenDocs.addEventListener("click", openDocsModal);
btnDocsClose.addEventListener("click", closeDocsModal);
modalDocs.addEventListener("click", (e) => {
  if (e.target === modalDocs) closeDocsModal();
});

// Le "+" du modal déclenche le même input que le menu "+"
btnDocsAdd.addEventListener("click", () => fileInput.click());

// ============================================================
//  Menu popup "+" dans la barre d'input
// ============================================================
function openActionMenu() {
  actionMenu.hidden = false;
  btnPlus.classList.add("active");
}
function closeActionMenu() {
  actionMenu.hidden = true;
  btnPlus.classList.remove("active");
}

btnPlus.addEventListener("click", (e) => {
  e.stopPropagation();
  if (actionMenu.hidden) openActionMenu();
  else closeActionMenu();
});

document.addEventListener("click", (e) => {
  if (!actionMenu.hidden && !actionMenu.contains(e.target) && e.target !== btnPlus) {
    closeActionMenu();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!actionMenu.hidden) closeActionMenu();
    if (!modalDocs.hidden) closeDocsModal();
    if (!modalDelete.hidden) { modalDelete.hidden = true; docToDelete = null; }
  }
});

btnAddFile.addEventListener("click", () => {
  closeActionMenu();
  fileInput.click();
});

// ============================================================
//  Popups format / taille
// ============================================================
function showFormatPopup(filename) {
  formatFileName.textContent = filename;
  modalFormat.hidden = false;
}
btnFormatOk.addEventListener("click", () => { modalFormat.hidden = true; });
modalFormat.addEventListener("click", (e) => {
  if (e.target === modalFormat) modalFormat.hidden = true;
});

function showTooLargePopup(filename) {
  toolargeFileName.textContent = filename;
  modalToolarge.hidden = false;
}
btnToolargeOk.addEventListener("click", () => { modalToolarge.hidden = true; });
modalToolarge.addEventListener("click", (e) => {
  if (e.target === modalToolarge) modalToolarge.hidden = true;
});

// ============================================================
//  Upload
// ============================================================
fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;

  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showFormatPopup(file.name);
    fileInput.value = "";
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    showTooLargePopup(file.name);
    fileInput.value = "";
    return;
  }

  btnPlus.disabled = true;
  btnDocsAdd.disabled = true;
  const originalPlus = btnPlus.innerHTML;
  const originalAdd = btnDocsAdd.innerHTML;
  btnPlus.textContent = "…";
  btnDocsAdd.textContent = "…";

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
    renderDocsModalList();
    renderScopeBar();
  } catch (err) {
    alert("❌ Erreur upload : " + err.message);
  } finally {
    btnPlus.disabled = false;
    btnDocsAdd.disabled = false;
    btnPlus.innerHTML = originalPlus;
    btnDocsAdd.innerHTML = originalAdd;
    fileInput.value = "";
  }
});

// ============================================================
//  DELETE — Supprimer un document
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

    await refreshDocuments();

    if (activeConvo) {
      const bubble = addMessage(
        "assistant",
        `Le document « ${target.filename} » a été supprimé.`,
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

modalDelete.addEventListener("click", (e) => {
  if (e.target === modalDelete) { modalDelete.hidden = true; docToDelete = null; }
});

// ============================================================
//  Nouvelle conversation
// ============================================================
btnNewChat.addEventListener("click", () => {
  activeConvo = createConversation();
  renderMessages();
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
    appendMessageToConvo({ role, text });
  }

  return bubble;
}

function renderMessages() {
  messagesEl.innerHTML = "";
  if (!activeConvo) return;
  activeConvo.messages.forEach((m) => {
    const bubble = addMessage(m.role, m.text, false);
    if (m.role === "assistant" && (m.sources?.length || m.warning || m.mode)) {
      attachAssistantActions(bubble, m);
    }
  });
}

// ============================================================
//  Actions sous les réponses assistant
// ============================================================
function attachAssistantActions(bubble, { text, sources = [], warning = null, mode = null }) {
  if (mode === "no_evidence") {
    bubble.style.fontStyle = "italic";
    bubble.style.color = "var(--text-muted)";
  }

  let sourcesBlock = null;
  if (Array.isArray(sources) && sources.length > 0) {
    sourcesBlock = document.createElement("div");
    sourcesBlock.className = "msg-sources";
    sourcesBlock.hidden = true;

    sources.forEach((s) => {
      const line = document.createElement("div");
      line.className = "msg-source-line";

      const ref = document.createElement("span");
      ref.className = "msg-source-ref";
      ref.textContent = `[${s.reference}]`;

      const meta = document.createElement("div");
      meta.className = "msg-source-meta";

      const file = document.createElement("div");
      file.className = "msg-source-file";
      file.textContent = s.filename;

      const page = document.createElement("div");
      page.className = "msg-source-page";
      page.textContent = s.page_end && s.page_end !== s.page
        ? `pages ${s.page}–${s.page_end} · score ${s.score}`
        : `page ${s.page} · score ${s.score}`;

      meta.appendChild(file);
      meta.appendChild(page);

      if (s.excerpt) {
        const excerpt = document.createElement("div");
        excerpt.className = "msg-source-excerpt";
        excerpt.textContent = s.excerpt;
        meta.appendChild(excerpt);
      }

      line.appendChild(ref);
      line.appendChild(meta);
      sourcesBlock.appendChild(line);
    });

    bubble.appendChild(sourcesBlock);
  }

  if (warning) {
    const warn = document.createElement("div");
    warn.style.marginTop = "8px";
    warn.style.fontSize = "12px";
    warn.style.color = "#b45309";
    warn.textContent = "⚠ " + warning;
    bubble.appendChild(warn);
  }

  if (!text) return;

  const actions = document.createElement("div");
  actions.className = "message-actions";

  const btnCopy = document.createElement("button");
  btnCopy.type = "button";
  btnCopy.className = "msg-action-btn";
  btnCopy.innerHTML = `${ICONS.copy}<span>Copier</span>`;

  btnCopy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      btnCopy.classList.add("copied");
      btnCopy.innerHTML = `${ICONS.check}<span>Copié</span>`;
      setTimeout(() => {
        btnCopy.classList.remove("copied");
        btnCopy.innerHTML = `${ICONS.copy}<span>Copier</span>`;
      }, 1600);
    } catch (err) {
      alert("Impossible de copier : " + err.message);
    }
  });

  actions.appendChild(btnCopy);

  if (sourcesBlock) {
    const btnRefs = document.createElement("button");
    btnRefs.type = "button";
    btnRefs.className = "msg-action-btn";
    const count = sources.length;
    const label = count === 1 ? "référence" : "références";
    btnRefs.innerHTML = `${ICONS.link}<span>${count} ${label}</span>`;

    btnRefs.addEventListener("click", () => {
      sourcesBlock.hidden = !sourcesBlock.hidden;
      btnRefs.classList.toggle("active", !sourcesBlock.hidden);
    });

    actions.appendChild(btnRefs);
  }

  bubble.appendChild(actions);
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
    const answerText = data.answer ?? "(réponse vide)";
    bubble.textContent = answerText;

    attachAssistantActions(bubble, {
      text: answerText,
      sources: data.sources ?? [],
      warning: data.warning ?? null,
      mode: data.response_mode,
    });

    appendMessageToConvo({
      role: "assistant",
      text: answerText,
      sources: data.sources ?? [],
      warning: data.warning ?? null,
      mode: data.response_mode,
    });

    console.log("Mode   :", data.response_mode);
    console.log("Sources:", data.sources);
  } catch (err) {
    bubble.textContent = "❌ " + err.message;
    bubble.style.color = "#b91c1c";
    appendMessageToConvo({
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
renderMessages();
refreshDocuments();
input.focus();