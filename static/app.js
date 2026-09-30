// ============================================================
//  Configuration
//  Frontend v4 — utilise les conversations du backend
// ============================================================
const API_URL = "/api/v1";
const DOCS_URL = `${API_URL}/documents`;
const CONVOS_URL = `${API_URL}/conversations`;
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

  close: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <line x1="18" y1="6" x2="6" y2="18"/>
    <line x1="6" y1="6" x2="18" y2="18"/>
  </svg>`,
};

// ============================================================
//  État global (en mémoire)
// ============================================================
let currentConvoId = null;      // id de la conversation active (côté serveur)
let currentConvo = null;        // objet complet { id, title, document_ids, message_count, ... }
let conversationsCache = [];    // liste des conversations du serveur
let documentsCache = [];        // liste des documents du serveur
let selectedDocId = null;       // restriction éventuelle à un document

// ============================================================
//  DOM
// ============================================================
const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const sendBtn = form.querySelector("button[type='submit']");
const btnNewChat = document.getElementById("btn-new-chat");
const conversationsEl = document.getElementById("conversations");

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

const modalDeleteConvo = document.getElementById("modal-delete-convo");
const deleteConvoName = document.getElementById("delete-convo-name");
const btnDeleteConvoCancel = document.getElementById("btn-delete-convo-cancel");
const btnDeleteConvoConfirm = document.getElementById("btn-delete-convo-confirm");

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

async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok && res.status !== 204) {
    const err = new Error(await extractError(res));
    err.status = res.status;
    err.response = res;
    throw err;
  }
  return res;
}

// ============================================================
//  Styles des bulles selon le mode de réponse du backend
//  Modes possibles :
//    extractive, llm        → réponse standard
//    source_quote           → citation exacte (bordure + guillemets)
//    no_evidence            → italique gris
//    chat_fallback, llm_chat → réponse conversationnelle, gris discret
// ============================================================
function applyBubbleStyles(bubble, mode) {
  if (mode === "source_quote") {
    bubble.classList.add("source-quote");
  } else if (mode === "no_evidence") {
    bubble.style.fontStyle = "italic";
    bubble.style.color = "var(--text-muted)";
  } else if (mode === "chat_fallback" || mode === "llm_chat") {
    bubble.style.color = "var(--text-muted)";
  }
}

function isChatTurn(mode) {
  return mode === "chat_fallback" || mode === "llm_chat";
}

// ============================================================
//  État vide des messages
//  IMPORTANT : on ne met RIEN dans .messages pour laisser
//  le CSS afficher automatiquement le greeting centré
//  (.chat:has(.messages:empty) .greeting { display: block; })
// ============================================================
function renderMessagesEmpty() {
  messagesEl.innerHTML = "";
}

// ============================================================
//  Initialisation
// ============================================================
async function init() {
  console.log("=== INIT v4 (conversations serveur) ===");
  try {
    await Promise.all([refreshDocuments(), refreshConversations()]);

    if (conversationsCache.length > 0) {
      await selectConversation(conversationsCache[0].id);
    } else {
      // Aucune conversation : on vide .messages → greeting centré
      renderMessagesEmpty();
      renderConversations();
    }
  } catch (err) {
    console.error("Init error:", err);
  } finally {
    input.focus();
  }
}

// ============================================================
//  Conversations — API
// ============================================================
async function refreshConversations() {
  try {
    const res = await apiFetch(`${CONVOS_URL}?limit=100`, { headers: authHeaders() });
    const data = await res.json();
    conversationsCache = data.items || [];
    renderConversations();
  } catch (err) {
    console.warn("Erreur de chargement des conversations :", err);
    conversationsEl.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "conversations-error";
    empty.textContent = "Erreur de chargement";
    conversationsEl.appendChild(empty);
  }
}

async function createNewConversation() {
  // Réutilise la conversation active si elle est déjà vide
  if (currentConvo && currentConvo.message_count === 0) {
    console.log("Réutilisation de la conversation vide :", currentConvoId);
    return currentConvo;
  }

  // Feedback visuel
  btnNewChat.disabled = true;
  btnNewChat.classList.add("loading");

  try {
    const allDocIds = documentsCache.map((d) => d.id);
    const res = await apiFetch(CONVOS_URL, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        title: "Nouvelle conversation",
        document_ids: allDocIds,
      }),
    });
    const convo = await res.json();
    console.log("Conversation créée :", convo);

    conversationsCache.unshift(convo);
    currentConvo = convo;
    currentConvoId = convo.id;
    renderMessagesEmpty();
    renderConversations();
    input.focus();
    return convo;
  } catch (err) {
    console.error("Création conversation :", err);
    alert("❌ Impossible de créer la conversation : " + err.message);
    return null;
  } finally {
    btnNewChat.disabled = false;
    btnNewChat.classList.remove("loading");
  }
}

async function selectConversation(id) {
  try {
    const resConvo = await apiFetch(`${CONVOS_URL}/${id}`, { headers: authHeaders() });
    currentConvo = await resConvo.json();
    currentConvoId = currentConvo.id;

    const resMsgs = await apiFetch(
      `${CONVOS_URL}/${id}/messages?limit=100`,
      { headers: authHeaders() }
    );
    const dataMsgs = await resMsgs.json();

    renderMessages(dataMsgs.items || []);
    renderConversations();
    input.focus();
  } catch (err) {
    console.error("Sélection conversation :", err);
    alert("❌ Impossible de charger la conversation : " + err.message);
  }
}

async function deleteConversation(id) {
  try {
    await apiFetch(`${CONVOS_URL}/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    conversationsCache = conversationsCache.filter((c) => c.id !== id);
    if (currentConvoId === id) {
      currentConvoId = null;
      currentConvo = null;
      if (conversationsCache.length > 0) {
        await selectConversation(conversationsCache[0].id);
      } else {
        renderMessagesEmpty();
        renderConversations();
      }
    } else {
      renderConversations();
    }
  } catch (err) {
    alert("❌ Erreur suppression conversation : " + err.message);
  }
}

async function renameConversation(id, newTitle) {
  try {
    const res = await apiFetch(`${CONVOS_URL}/${id}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ title: newTitle }),
    });
    const updated = await res.json();
    const idx = conversationsCache.findIndex((c) => c.id === id);
    if (idx !== -1) conversationsCache[idx] = updated;
    if (currentConvoId === id) currentConvo = updated;
    renderConversations();
  } catch (err) {
    console.warn("Renommage conversation :", err);
  }
}

// ============================================================
//  Sidebar : rendu des conversations
// ============================================================
function renderConversations() {
  conversationsEl.innerHTML = "";

  if (conversationsCache.length === 0) {
    const empty = document.createElement("div");
    empty.className = "conversations-empty";
    empty.textContent = documentsCache.length === 0
      ? "Ajoutez un PDF pour commencer"
      : "Aucune conversation";
    conversationsEl.appendChild(empty);
    return;
  }

  conversationsCache.forEach((c) => {
    const item = document.createElement("div");
    item.className = "convo-item" + (c.id === currentConvoId ? " active" : "");
    item.title = c.title;

    const dot = document.createElement("span");
    dot.className = "convo-dot";

    const label = document.createElement("span");
    label.className = "convo-label";
    label.textContent = c.title;

    const actions = document.createElement("div");
    actions.className = "convo-actions";

    const btnDelete = document.createElement("button");
    btnDelete.className = "convo-btn danger";
    btnDelete.title = "Supprimer cette conversation";
    btnDelete.innerHTML = ICONS.trash;
    btnDelete.addEventListener("click", (e) => {
      e.stopPropagation();
      openDeleteConvoModal(c);
    });
    actions.appendChild(btnDelete);

    item.appendChild(dot);
    item.appendChild(label);
    item.appendChild(actions);

    item.addEventListener("click", () => {
      if (c.id !== currentConvoId) selectConversation(c.id);
    });

    conversationsEl.appendChild(item);
  });
}

// ============================================================
//  Bouton "Nouvelle conversation"
// ============================================================
btnNewChat.addEventListener("click", () => {
  createNewConversation();
});

// ============================================================
//  Modale suppression de conversation
// ============================================================
let convoToDelete = null;

function openDeleteConvoModal(convo) {
  convoToDelete = convo;
  deleteConvoName.textContent = convo.title;
  modalDeleteConvo.hidden = false;
}

btnDeleteConvoCancel.addEventListener("click", () => {
  modalDeleteConvo.hidden = true;
  convoToDelete = null;
});

btnDeleteConvoConfirm.addEventListener("click", async () => {
  if (!convoToDelete) return;
  const target = convoToDelete;
  convoToDelete = null;
  modalDeleteConvo.hidden = true;
  await deleteConversation(target.id);
});

modalDeleteConvo.addEventListener("click", (e) => {
  if (e.target === modalDeleteConvo) {
    modalDeleteConvo.hidden = true;
    convoToDelete = null;
  }
});

// ============================================================
//  Documents — API
// ============================================================
function updateDocsCount() {
  docsCount.textContent = documentsCache.length;
}

async function refreshDocuments() {
  try {
    const res = await apiFetch(`${DOCS_URL}?limit=100`, { headers: authHeaders() });
    const data = await res.json();
    documentsCache = data.items || [];
    if (selectedDocId && !documentsCache.some((d) => d.id === selectedDocId)) {
      selectedDocId = null;
    }
    updateDocsCount();
    renderDocsModalList();
    renderScopeBar();
  } catch (err) {
    console.warn("Erreur de chargement des documents :", err);
    documentsCache = [];
    updateDocsCount();
    docsList.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "docs-empty";
    empty.textContent = "Erreur de chargement";
    docsList.appendChild(empty);
  }
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

btnDocsAdd.addEventListener("click", () => fileInput.click());

// ============================================================
//  Menu popup "+"
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
    if (!modalDeleteConvo.hidden) { modalDeleteConvo.hidden = true; convoToDelete = null; }
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
//  Upload d'un document
// ============================================================
fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;

  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showFormatPopup(file.name);
    fileInput.value = "";
    return;
  }
  if (file.size > 30 * 1024 * 1024) {
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

    if (res.status === 409) {
      const payload = await res.json();
      console.warn("Doublon détecté :", payload);
      await refreshDocuments();
      if (payload.existing_document_id) {
        selectedDocId = payload.existing_document_id;
        renderDocsModalList();
        renderScopeBar();
        alert("Ce PDF existe déjà dans la bibliothèque. Il a été sélectionné.");
      } else {
        alert("Ce PDF existe déjà dans la bibliothèque.");
      }
      return;
    }

    if (!res.ok) throw new Error(await extractError(res));

    const doc = await res.json();
    console.log("Document ajouté :", doc);

    await refreshDocuments();
    selectedDocId = doc.id;
    renderDocsModalList();
    renderScopeBar();

    if (!currentConvoId && conversationsCache.length === 0) {
      await createNewConversation();
    }
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
//  Suppression d'un document
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
    await apiFetch(`${DOCS_URL}/${target.id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });

    modalDelete.hidden = true;
    docToDelete = null;

    if (selectedDocId === target.id) selectedDocId = null;

    await refreshDocuments();
    await refreshConversations();

    if (currentConvo && currentConvo.document_ids) {
      currentConvo.document_ids = currentConvo.document_ids.filter(
        (id) => id !== target.id
      );
    }

    appendSystemMessage(`Le document « ${target.filename} » a été supprimé.`);
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
//  Messages — rendu
// ============================================================
function scrollToBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

function addMessage(role, text = "", options = {}) {
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

  applyBubbleStyles(bubble, options.mode || null);

  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  scrollToBottom();

  if (role === "assistant") {
    attachAssistantActions(bubble, {
      text,
      sources: options.sources || [],
      warning: options.warning || null,
      mode: options.mode || null,
    });
  }

  return bubble;
}

function appendSystemMessage(text) {
  const wrapper = document.createElement("div");
  wrapper.className = "message system";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  scrollToBottom();
}

// Affiche les messages d'une conversation (chargés depuis /messages).
// Si vide, on laisse .messages vide → le CSS affiche le greeting centré.
function renderMessages(messages) {
  messagesEl.innerHTML = "";
  if (!messages || messages.length === 0) {
    return;
  }
  messages.forEach((m) => {
    addMessage(m.role, m.content, {
      mode: m.response_mode || null,
      sources: m.sources || [],
      warning: null,
    });
  });
}

// ============================================================
//  Actions sous les réponses assistant (copier + références)
// ============================================================
function attachAssistantActions(bubble, { text, sources = [], warning = null, mode = null }) {
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
//  Utilise POST /api/v1/conversations/{id}/questions
// ============================================================
form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const text = input.value.trim();
  if (!text) return;

  // Le backend accepte les salutations même sans document attaché.
  if (!currentConvoId) {
    const convo = await createNewConversation();
    if (!convo) return;
  }

  // ✅ CAPTURE AVANT ENVOI : la conversation était-elle vide ?
  const wasEmpty = currentConvo && currentConvo.message_count === 0;

  addMessage("user", text);
  input.value = "";
  setLoading(true);

  const wrapper = document.createElement("div");
  wrapper.className = "message assistant";
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "V";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = "…";
  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  scrollToBottom();

  try {
    const body = {
      question: text,
      top_k: 4,
    };
    if (selectedDocId) {
      body.document_ids = [selectedDocId];
    }

    const res = await fetch(`${CONVOS_URL}/${currentConvoId}/questions`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });

    if (!res.ok) throw new Error(await extractError(res));

    const data = await res.json();
    const answerText = data.answer ?? "(réponse vide)";

    bubble.textContent = answerText;
    applyBubbleStyles(bubble, data.response_mode || null);

    attachAssistantActions(bubble, {
      text: answerText,
      sources: data.sources || [],
      warning: data.warning || null,
      mode: data.response_mode || null,
    });

    // ✅ Titre auto basé sur la valeur capturée AVANT l'envoi
    //    On saute les simples salutations (chat_fallback, llm_chat)
    if (wasEmpty && !isChatTurn(data.response_mode)) {
      const newTitle = text.slice(0, 40) + (text.length > 40 ? "…" : "");
      await renameConversation(currentConvoId, newTitle);
    }

    // Rafraîchit les métadonnées (message_count, updated_at)
    try {
      const resConvo = await apiFetch(`${CONVOS_URL}/${currentConvoId}`, { headers: authHeaders() });
      currentConvo = await resConvo.json();
      const idx = conversationsCache.findIndex((c) => c.id === currentConvoId);
      if (idx !== -1) conversationsCache[idx] = currentConvo;
      renderConversations();
    } catch {}

    console.log("Mode   :", data.response_mode);
    console.log("Sources:", data.sources);
  } catch (err) {
    bubble.textContent = "❌ " + err.message;
    bubble.style.color = "#b91c1c";
  } finally {
    setLoading(false);
    scrollToBottom();
  }
});

// ============================================================
//  Lancement
// ============================================================
init();