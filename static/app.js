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
//  État global
// ============================================================
let currentConvoId = null;
let currentConvo = null;
let conversationsCache = [];
let documentsCache = [];

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
//  Sidebar responsive — ouverture/fermeture sur mobile
// ============================================================
const sidebarEl = document.getElementById("sidebar");
const sidebarOverlay = document.getElementById("sidebar-overlay");
const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");

function openSidebar() {
  if (!sidebarEl) return;
  sidebarEl.classList.add("open");
  if (sidebarOverlay) sidebarOverlay.hidden = false;
}

function closeSidebar() {
  if (!sidebarEl) return;
  sidebarEl.classList.remove("open");
  if (sidebarOverlay) sidebarOverlay.hidden = true;
}

function toggleSidebar() {
  if (!sidebarEl) return;
  if (sidebarEl.classList.contains("open")) closeSidebar();
  else openSidebar();
}

if (btnToggleSidebar) {
  btnToggleSidebar.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleSidebar();
  });
}

if (sidebarOverlay) {
  sidebarOverlay.addEventListener("click", closeSidebar);
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && sidebarEl && sidebarEl.classList.contains("open")) {
    closeSidebar();
  }
});

function closeSidebarOnMobile() {
  if (window.matchMedia("(max-width: 768px)").matches) {
    closeSidebar();
  }
}

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
//  Détecte une salutation côté frontend.
//  Le backend accepte ces messages même sans document attaché,
//  donc on ne bloque pas l'envoi dans ce cas.
// ============================================================
function looksLikeGreeting(text) {
  const normalized = text
    .toLowerCase()
    .replace(/[^a-zà-ÿ0-9'’ ]+/gi, " ")
    .replace(/\s+/g, " ")
    .trim();

  const patterns = [
    /^(bonjour|bonsoir|salut|hello|hi|hey|coucou)( (ça va|ca va|comment vas tu|comment allez vous|how are you))?$/,
    /^(merci|merci beaucoup|je te remercie|je vous remercie|thanks|thank you|thanks a lot|thank you very much)$/,
    /^(au revoir|à bientôt|a bientot|bonne journée|bonne journee|bonne soirée|bonne soiree|goodbye|bye|see you|see you later)$/,
    /^(ça va|ca va|comment vas tu|comment allez vous|how are you)$/,
    /^(привет|здравствуйте|добрый день|добрый вечер)( как дела)?$/,
    /^(спасибо|большое спасибо)$/,
    /^(до свидания|пока|до встречи)$/,
    /^как дела$/,
  ];
  return patterns.some((p) => p.test(normalized));
}

// ============================================================
//  Titre auto : tronque proprement au dernier mot complet
// ============================================================
function makeTitle(text) {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= 40) return clean;
  const cut = clean.slice(0, 40);
  const lastSpace = cut.lastIndexOf(" ");
  return (lastSpace > 20 ? cut.slice(0, lastSpace) : cut) + "…";
}

// ============================================================
//  Documents attachés à la conversation active
// ============================================================
function getConversationDocuments() {
  if (!currentConvo || !Array.isArray(currentConvo.document_ids)) {
    return [];
  }
  const ids = new Set(currentConvo.document_ids);
  return documentsCache.filter((d) => ids.has(d.id));
}

// ============================================================
//  Lier une liste de documents à la conversation active
// ============================================================
async function setConversationDocuments(documentIds) {
  if (!currentConvoId) return null;
  try {
    const res = await apiFetch(`${CONVOS_URL}/${currentConvoId}/documents`, {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ document_ids: documentIds }),
    });
    const updated = await res.json();
    currentConvo = updated;
    const idx = conversationsCache.findIndex((c) => c.id === currentConvoId);
    if (idx !== -1) conversationsCache[idx] = updated;
    return updated;
  } catch (err) {
    console.error("Échec mise à jour documents de la conversation :", err);
    alert("❌ Impossible de lier les documents à la conversation : " + err.message);
    return null;
  }
}

// ============================================================
//  État vide des messages
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

    if (currentConvoId) {
      const updated = conversationsCache.find((c) => c.id === currentConvoId);
      if (updated) currentConvo = updated;
    }

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
  if (currentConvo && currentConvo.message_count === 0) {
    console.log("Réutilisation de la conversation vide :", currentConvoId);
    return currentConvo;
  }

  btnNewChat.disabled = true;
  btnNewChat.classList.add("loading");

  try {
    // Chaque conversation voit tous les documents disponibles (pas d'isolation).
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
    updateDocsCount();
    renderDocsModalList();
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
    updateDocsCount();
    renderDocsModalList();
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
        updateDocsCount();
        renderDocsModalList();
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
    console.log("[rename] Titre mis à jour :", updated.title);
  } catch (err) {
    console.error("[rename] Échec renommage :", err.message, "status=" + err.status);
    try {
      const text = await err.response?.text();
      console.error("[rename] Réponse serveur :", text);
    } catch {}
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
    empty.textContent = "Aucune conversation";
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
      closeSidebarOnMobile();
    });

    conversationsEl.appendChild(item);
  });
}

// ============================================================
//  Bouton "Nouvelle conversation"
// ============================================================
btnNewChat.addEventListener("click", async () => {
  await createNewConversation();
  closeSidebarOnMobile();
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
  docsCount.textContent = getConversationDocuments().length;
}

async function refreshDocuments() {
  try {
    const res = await apiFetch(`${DOCS_URL}?limit=100`, { headers: authHeaders() });
    const data = await res.json();
    documentsCache = data.items || [];
    updateDocsCount();
    renderDocsModalList();
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

// ============================================================
//  Liste des documents — uniquement ceux de la conversation
// ============================================================
function renderDocsModalList() {
  docsList.innerHTML = "";

  const convoDocs = getConversationDocuments();

  if (convoDocs.length === 0) {
    const empty = document.createElement("div");
    empty.className = "docs-empty";
    empty.textContent = currentConvoId
      ? "Aucun document dans cette conversation"
      : "Aucune conversation active";
    docsList.appendChild(empty);
    return;
  }

  convoDocs.forEach((doc) => {
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

    const btnDetach = document.createElement("button");
    btnDetach.className = "doc-row-btn danger";
    btnDetach.title = "Retirer ce PDF de la conversation";
    btnDetach.innerHTML = ICONS.close;
    btnDetach.addEventListener("click", (e) => {
      e.stopPropagation();
      openDeleteModal(doc);
    });
    actions.appendChild(btnDetach);

    row.appendChild(icon);
    row.appendChild(body);
    row.appendChild(actions);

    docsList.appendChild(row);
  });
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

btnOpenDocs.addEventListener("click", () => {
  openDocsModal();
  closeSidebarOnMobile();
});

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
//  Upload d'un document — l'ajoute ET le lie à la conversation
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

    let docId = null;

    if (res.status === 409) {
      const payload = await res.json();
      console.warn("[upload] Doublon détecté :", payload);
      docId = payload.existing_document_id;
    } else if (!res.ok) {
      throw new Error(await extractError(res));
    } else {
      const doc = await res.json();
      console.log("[upload] Nouveau document :", doc);
      docId = doc.id;
    }

    if (!docId) {
      throw new Error("Impossible d'obtenir l'ID du document.");
    }

    // 1) Recharge la bibliothèque globale
    await refreshDocuments();

    // 2) Crée une conversation si aucune n'existe
    if (!currentConvoId) {
      const convo = await createNewConversation();
      if (!convo) return;
    }

    // 3) Rafraîchit currentConvo depuis le serveur
    try {
      const resConvo = await apiFetch(`${CONVOS_URL}/${currentConvoId}`, { headers: authHeaders() });
      currentConvo = await resConvo.json();
      const idx = conversationsCache.findIndex((c) => c.id === currentConvoId);
      if (idx !== -1) conversationsCache[idx] = currentConvo;
    } catch (err) {
      console.warn("[upload] Impossible de rafraîchir la conversation :", err);
    }

    // 4) Ajoute le nouveau doc à la liste existante (sans écraser)
    const current = new Set(currentConvo.document_ids || []);
    current.add(docId);

    const updated = await setConversationDocuments([...current]);
    if (updated) {
      updateDocsCount();
      renderDocsModalList();
      renderConversations();
    }
  } catch (err) {
    console.error("[upload] Erreur :", err);
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
//  Retirer un document de la conversation
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
  btnDeleteConfirm.textContent = "Retrait…";

  try {
    if (currentConvoId && currentConvo) {
      const remaining = (currentConvo.document_ids || []).filter(
        (id) => id !== target.id
      );
      const updated = await setConversationDocuments(remaining);
      if (updated) {
        modalDelete.hidden = true;
        docToDelete = null;

        updateDocsCount();
        renderDocsModalList();

        appendSystemMessage(
          `Le document « ${target.filename} » a été retiré de cette conversation.`
        );
      }
    }
  } catch (err) {
    alert("❌ Erreur retrait : " + err.message);
  } finally {
    btnDeleteConfirm.disabled = false;
    btnDeleteConfirm.textContent = "Retirer";
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
// ============================================================
form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const text = input.value.trim();
  if (!text) return;

  if (!currentConvoId) {
    const convo = await createNewConversation();
    if (!convo) return;
  }

  // Rafraîchit currentConvo depuis le serveur pour connaître
  // ses documents réels avant de décider d'envoyer ou non.
  try {
    const resConvo = await apiFetch(`${CONVOS_URL}/${currentConvoId}`, { headers: authHeaders() });
    currentConvo = await resConvo.json();
    const idx = conversationsCache.findIndex((c) => c.id === currentConvoId);
    if (idx !== -1) conversationsCache[idx] = currentConvo;
  } catch {}

  // ⚠️ Conversation sans document → on bloque,
  // sauf pour les salutations que le backend accepte sans document.
  const convoDocs = getConversationDocuments();
  if (convoDocs.length === 0 && !looksLikeGreeting(text)) {
    appendSystemMessage(
      "Aucun document n'est associé à cette conversation. " +
      "Ajoutez ou sélectionnez un document pour commencer."
    );
    return;
  }

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

    // Titre auto à la 1ère vraie question
    if (wasEmpty && !isChatTurn(data.response_mode)) {
      const newTitle = makeTitle(text);
      await renameConversation(currentConvoId, newTitle);
    }

    // Rafraîchit les métadonnées
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