// EDITH Desktop Companion, System Control, Diagrams & Wake Word Controller
let ws = null;
let currentMode = "standard"; // 'standard', 'coworking' o 'auto' (decide el ML)
let lastMlQuery = "";
let voiceEnabled = true;
let activeFilePath = "notas_del_dia.md";
let recognition = null;
let wakeWordActive = true;
let isListeningForCommand = false;
let activeSessionId = null;
let streamingEl = null;   // burbuja donde se escribe la respuesta token a token
let streamingText = "";
let historySearchTimer = null;
const REASONING_MODES = {
  auto: { label: "🧠 Auto", title: "Razonamiento automático: EDITH decide si pensar a fondo" },
  fast: { label: "⚡ Rápido", title: "Respuesta directa, sin razonamiento (más rápida)" },
  deep: { label: "🔬 Profundo", title: "Pensar a fondo antes de responder (más lento, más fiable)" },
};
let reasoningMode = "auto";
try { reasoningMode = localStorage.getItem("edith.reasoning") || "auto"; } catch (e) {}
if (!REASONING_MODES[reasoningMode]) reasoningMode = "auto";
let lastTurnDeep = null;

document.addEventListener("DOMContentLoaded", () => {
  initMermaid();
  initWebSocket();
  initSpeechRecognition();
  loadStatus();
  loadWorkspaceFiles();
  loadSessions();
  loadLearnings();
  loadSystemStatus();
  setupEventListeners();
  openWorkspaceFile("notas_del_dia.md", true);

  // Intervalo para actualizar estado de batería y CPU cada 15 segundos
  setInterval(loadSystemStatus, 15000);
});

// 1. Mermaid Setup
function initMermaid() {
  if (window.mermaid) {
    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        darkMode: true,
        background: '#0a0a0f',
        primaryColor: '#20202b',
        primaryTextColor: '#ece9f5',
        primaryBorderColor: '#9b5cf6',
        lineColor: '#9b5cf6',
        secondaryColor: '#17171f',
        tertiaryColor: '#2ecc71'
      }
    });
  }
}

// 2. Speech Recognition & Wake Word ("Oye EDITH")
function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.warn("Reconocimiento de voz no soportado en este entorno.");
    const btnWake = document.getElementById("btnWakeWord");
    if (btnWake) btnWake.style.display = "none";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "es-ES";

  recognition.onresult = (event) => {
    let transcript = "";
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      transcript += event.results[i][0].transcript;
    }
    const clean = transcript.toLowerCase().trim();

    const wakeKeywords = ["edith", "oye edith", "hey edith", "hola edith", "edit", "oye edit"];
    const containsWake = wakeKeywords.some(w => clean.includes(w));

    if (containsWake && !isListeningForCommand) {
      triggerWakeAction(clean);
    } else if (isListeningForCommand) {
      const input = document.getElementById("promptInput");
      input.value = transcript;
      if (event.results[event.results.length - 1].isFinal) {
        isListeningForCommand = false;
        document.getElementById("btnWakeWord").classList.remove("listening");
        document.getElementById("chatForm").dispatchEvent(new Event("submit"));
      }
    }
  };

  recognition.onerror = (e) => {
    if (e.error !== "no-speech") {
      console.warn("Error en reconocimiento de voz:", e.error);
    }
  };

  recognition.onend = () => {
    if (wakeWordActive) {
      try { recognition.start(); } catch (err) {}
    }
  };

  try {
    recognition.start();
  } catch (err) {
    console.log("Inicio de reconocimiento diferido:", err);
  }
}

function triggerWakeAction(spokenText) {
  isListeningForCommand = true;
  const btn = document.getElementById("btnWakeWord");
  btn.classList.add("listening");

  // Sonido sutil de confirmación
  playActivationPing();

  // Revisar si ya dijo la orden en la misma frase (ej. "Oye EDITH abre la calculadora")
  const wakeKeywords = ["edith", "oye edith", "hey edith", "hola edith", "edit", "oye edit"];
  for (const w of wakeKeywords) {
    if (spokenText.includes(w)) {
      const parts = spokenText.split(w);
      const command = parts[parts.length - 1].trim();
      if (command.length > 2) {
        document.getElementById("promptInput").value = command;
        isListeningForCommand = false;
        btn.classList.remove("listening");
        document.getElementById("chatForm").dispatchEvent(new Event("submit"));
        return;
      }
    }
  }
}

function playActivationPing() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
    gain.gain.setValueAtTime(0.08, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
    osc.start();
    osc.stop(ctx.currentTime + 0.15);
  } catch (e) {}
}

// 3. WebSocket Setup
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/chat`;
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log("[WebSocket] Conectado a EDITH Desktop");
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWsMessage(data);
    } catch (e) {
      console.error("Error parseando mensaje WS:", e);
    }
  };

  ws.onclose = () => {
    setTimeout(initWebSocket, 3000);
  };
}

// 4. WebSocket Dispatcher
function handleWsMessage(data) {
  const thoughtContent = document.getElementById("thoughtContent");
  const thoughtIndicator = document.getElementById("thoughtIndicator");

  switch (data.type) {
    case "iteration_start":
      // Cada paso del razonamiento empieza limpio (un paso con herramientas no es la respuesta final)
      resetStreamingBubble();
      document.getElementById("thoughtLine").style.display = "flex";
      thoughtIndicator.innerText = `Razonando paso ${data.iteration}`;
      thoughtIndicator.classList.add("active");
      break;

    case "thought_chunk":
      thoughtContent.innerText += data.chunk;
      thoughtContent.scrollTop = thoughtContent.scrollHeight;
      break;

    case "reasoning":
      lastTurnDeep = data.deep;
      thoughtIndicator.innerText = data.deep ? "Pensando a fondo..." : "Respondiendo rápido...";
      break;

    case "content_chunk":
      appendStreamingChunk(data.chunk);
      break;

    case "tool_call":
      resetStreamingBubble();
      appendToolCallBanner(data.tool, data.args);
      break;

    case "team_event":
      handleTeamEvent(data);
      break;

    case "ml_route":
      showMlRoute(data);
      break;

    case "final_answer":
      thoughtIndicator.innerText = "Concluido";
      thoughtIndicator.classList.remove("active");
      resetStreamingBubble();
      appendAssistantMessage(data.content, data.sources, data.deep);
      if (data.audio_url && voiceEnabled) {
        playVoiceAudio(data.audio_url);
      }
      if (data.session_id) activeSessionId = data.session_id;
      loadWorkspaceFiles();
      loadSessions();
      checkAndRenderDiagramsInText(data.content);
      break;

    case "audio_ready":
      if (voiceEnabled) playVoiceAudio(data.audio_url);
      break;

    case "error":
      resetStreamingBubble();
      thoughtIndicator.innerText = "Error";
      thoughtIndicator.classList.remove("active");
      appendAssistantMessage(`⚠️ **Error:** ${data.message}`);
      break;
  }
}

// Respuesta en vivo: se muestra mientras el modelo escribe, en vez de esperar al final
function appendStreamingChunk(chunk) {
  const container = document.getElementById("chatMessages");
  if (!streamingEl) {
    streamingEl = document.createElement("div");
    streamingEl.className = "message assistant-msg streaming-msg";
    streamingEl.innerHTML = `
      <div class="msg-header"><img class="avatar" src="logo.png" alt="EDITH"><span class="name">EDITH</span><span class="time">escribiendo...</span></div>
      <div class="msg-body"></div>
    `;
    container.appendChild(streamingEl);
    streamingText = "";
  }
  streamingText += chunk;
  streamingEl.querySelector(".msg-body").textContent = streamingText;
  container.scrollTop = container.scrollHeight;
}

function resetStreamingBubble() {
  if (streamingEl) streamingEl.remove();
  streamingEl = null;
  streamingText = "";
}

function playVoiceAudio(url) {
  const audio = document.getElementById("edithAudio");
  audio.src = url;
  audio.play().catch((e) => console.log("Reproducción de audio evitada:", e));
}

// 5. Chat UI Helpers
function appendUserMessage(text) {
  const container = document.getElementById("chatMessages");
  const msgEl = document.createElement("div");
  msgEl.className = "message user-msg";
  msgEl.innerHTML = `
    <div class="msg-header"><span class="name">Tú</span></div>
    <div class="msg-body"><p>${escapeHtml(text)}</p></div>
  `;
  container.appendChild(msgEl);
  container.scrollTop = container.scrollHeight;
}

function appendAssistantMessage(markdownContent, sources = [], deep = undefined) {
  const container = document.getElementById("chatMessages");
  const msgEl = document.createElement("div");
  msgEl.className = "message assistant-msg";

  let sourcesHtml = "";
  if (sources && sources.length > 0) {
    sourcesHtml = `
      <div class="sources-box">
        <strong>Fuentes consultadas:</strong>
        ${sources.map(s => `<a href="${s.url}" target="_blank" rel="noopener">🌐 ${s.title || s.url}</a>`).join("")}
      </div>
    `;
  }

  const parsedBody = marked.parse(markdownContent || "");
  msgEl.innerHTML = `
    <div class="msg-header">
      <img class="avatar" src="logo.png" alt="EDITH">
      <span class="name">EDITH</span>
      <span class="time">Ahora</span>
      ${deep === undefined ? "" : `<span class="reasoning-tag">${deep ? "🔬 razonado" : "⚡ rápido"}</span>`}
    </div>
    <div class="msg-body">
      ${parsedBody}
      ${sourcesHtml}
    </div>
  `;
  container.appendChild(msgEl);
  container.scrollTop = container.scrollHeight;

  // Renderizar bloques Mermaid en el mensaje si existen
  renderMermaidBlocksInElement(msgEl);
}

function appendToolCallBanner(tool, args) {
  const container = document.getElementById("chatMessages");
  const banner = document.createElement("div");
  banner.className = "tool-banner";
  let label = `⚙️ ${tool}`;
  if (tool === "open_application") {
    label = `🚀 Abriendo en laptop: "${args.app_name || ''}"`;
  } else if (tool === "get_system_status") {
    label = `📊 Verificando hardware de la laptop...`;
  } else if (tool === "control_system_volume") {
    label = `🔊 Ajustando volumen: ${args.action || ''}`;
  } else if (tool === "save_diagram") {
    label = `📊 Guardando diagrama visual: "${args.title || ''}"`;
  } else if (tool === "web_search") {
    label = `🔍 Rastreando en la web: "${args.query || ''}"`;
  } else if (tool === "read_web_page") {
    label = `📄 Leyendo artículo: ${args.url || ''}`;
  } else if (tool === "save_to_workspace") {
    label = `💾 Guardando archivo: "${args.filename || ''}"`;
  }
  banner.innerText = label;
  container.appendChild(banner);
  container.scrollTop = container.scrollHeight;
}

function handleTeamEvent(data) {
  const cardEdith = document.getElementById("cardEdith");
  const cardScout = document.getElementById("cardScout");
  const cardAuditor = document.getElementById("cardAuditor");

  [cardEdith, cardScout, cardAuditor].forEach(c => c.classList.remove("speaking"));
  if (data.member === "EDITH") cardEdith.classList.add("speaking");
  if (data.member === "Scout") cardScout.classList.add("speaking");
  if (data.member === "Auditor") cardAuditor.classList.add("speaking");

  const container = document.getElementById("chatMessages");
  const item = document.createElement("div");
  item.className = "message assistant-msg";
  item.style.borderLeft = "3px solid #a855f7";
  
  let avatarHtml = `<img class="avatar" src="logo.png" alt="EDITH">`;
  if (data.member === "Scout") avatarHtml = `<span class="avatar">🕵️</span>`;
  if (data.member === "Auditor") avatarHtml = `<span class="avatar">🧐</span>`;

  item.innerHTML = `
    <div class="msg-header">
      ${avatarHtml}
      <span class="name">${data.member} (${data.role})</span>
    </div>
    <div class="msg-body">
      ${marked.parse(data.content || '')}
    </div>
  `;
  container.appendChild(item);
  container.scrollTop = container.scrollHeight;
}

// 6. Diagram Rendering in Chat & Center View
function renderMermaidBlocksInElement(el) {
  if (!window.mermaid) return;
  const codeBlocks = el.querySelectorAll("pre code.language-mermaid, pre code");
  codeBlocks.forEach(async (block) => {
    const text = block.innerText.trim();
    if (text.startsWith("graph") || text.startsWith("flowchart") || text.startsWith("mindmap") || text.startsWith("sequenceDiagram")) {
      const container = document.createElement("div");
      container.className = "mermaid";
      const id = "mermaid_" + Math.random().toString(36).substr(2, 9);
      try {
        const { svg } = await mermaid.render(id, text);
        container.innerHTML = svg;
        block.parentElement.replaceWith(container);
      } catch (err) {
        console.warn("Error renderizando Mermaid:", err);
      }
    }
  });
}

function checkAndRenderDiagramsInText(text) {
  if (!text) return;
  const match = text.match(/```mermaid([\s\S]*?)```/);
  if (match && match[1]) {
    const diagramCode = match[1].trim();
    displayDiagramInCenterView("Mapa Conceptual / Diagrama Reciente", diagramCode);
  }
}

async function displayDiagramInCenterView(title, code) {
  document.getElementById("diagramTitle").innerText = title;
  const container = document.getElementById("diagramRenderArea");
  container.innerHTML = `<div class="mermaid">${code}</div>`;
  if (window.mermaid) {
    try {
      await mermaid.run({ nodes: container.querySelectorAll(".mermaid") });
    } catch (e) {
      console.warn("Mermaid render error:", e);
    }
  }
}

// 7. System Tools API Calls
async function launchApp(appName) {
  try {
    const res = await fetch("/api/system/app", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_name: appName })
    });
    const data = await res.json();
    appendToolCallBanner("open_application", { app_name: appName });
  } catch (e) {
    alert("Error lanzando aplicación: " + e);
  }
}

async function adjustVolume(action) {
  try {
    await fetch("/api/system/volume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
  } catch (e) {}
}

async function loadSystemStatus() {
  try {
    const res = await fetch("/api/system/status");
    const data = await res.json();

    const bat = data.bateria ? `${data.bateria.percent} ${data.bateria.plugged ? '⚡' : ''}` : 'N/A';
    document.getElementById("batteryStat").innerText = `🔋 Bat: ${bat}`;
    document.getElementById("cpuStat").innerText = `⚡ CPU: ${data.cpu_uso}`;
    document.getElementById("ramStat").innerText = `💾 RAM: ${data.memoria_ram ? data.memoria_ram.percent : '--'}`;

    const hwDetails = document.getElementById("hardwareDetails");
    if (hwDetails) {
      hwDetails.innerText = JSON.stringify(data, null, 2);
    }
  } catch (e) {}
}

// 8. General Data: Status, Workspace, Sessions
async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.voice_key) {
      document.getElementById("voiceSelect").value = data.voice_key;
    }
  } catch (e) {}
}

async function loadWorkspaceFiles() {
  try {
    const res = await fetch("/api/workspace");
    const files = await res.json();
    const listEl = document.getElementById("fileList");
    listEl.innerHTML = "";

    if (!files || files.length === 0) {
      listEl.innerHTML = `<li class="file-loading">Workspace listo para tus archivos.</li>`;
      return;
    }

    files.forEach(f => {
      const li = document.createElement("li");
      li.innerHTML = `<span>${f.is_dir ? "📁" : (f.path.endsWith('.mmd') ? '📊' : '📄')}</span> <span>${f.path}</span>`;
      if (!f.is_dir) {
        li.addEventListener("click", () => openWorkspaceFile(f.path));
      }
      listEl.appendChild(li);
    });
  } catch (e) {}
}

async function openWorkspaceFile(path, createIfNotExists = false) {
  try {
    const res = await fetch(`/api/workspace/file?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    if (data.content.startsWith("El archivo") && data.content.includes("no existe") && createIfNotExists) {
      const initialNotes = "# 📝 Notas & Planes del Día\n\n- Escribe aquí tus ideas, tareas o reflexiones con EDITH.\n";
      await fetch("/api/workspace/file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: path, content: initialNotes })
      });
      data.content = initialNotes;
    }

    activeFilePath = path;
    document.getElementById("currentFileName").innerText = path;
    const editor = document.getElementById("codeEditor");
    editor.value = data.content;
    document.getElementById("editorStatus").innerText = `Abierto: ${path}`;

    if (path.endsWith(".mmd")) {
      document.getElementById("tabDiagramView").classList.add("active");
      document.getElementById("tabDailyView").classList.remove("active");
      document.getElementById("tabCodeView").classList.remove("active");
      document.getElementById("editorBodyView").style.display = "none";
      document.getElementById("diagramBodyView").style.display = "flex";
      displayDiagramInCenterView(path, data.content);
    } else if (path.endsWith(".md") || path.includes("nota")) {
      document.getElementById("tabDailyView").classList.add("active");
      document.getElementById("tabCodeView").classList.remove("active");
      document.getElementById("tabDiagramView").classList.remove("active");
      document.getElementById("editorBodyView").style.display = "block";
      document.getElementById("diagramBodyView").style.display = "none";
    } else {
      document.getElementById("tabCodeView").classList.add("active");
      document.getElementById("tabDailyView").classList.remove("active");
      document.getElementById("tabDiagramView").classList.remove("active");
      document.getElementById("editorBodyView").style.display = "block";
      document.getElementById("diagramBodyView").style.display = "none";
    }
  } catch (e) {}
}

async function saveCurrentFile() {
  if (!activeFilePath) return;
  const content = document.getElementById("codeEditor").value;
  try {
    await fetch("/api/workspace/file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: activeFilePath, content })
    });
    document.getElementById("editorStatus").innerText = `Guardado exitoso (${new Date().toLocaleTimeString()})`;
    loadWorkspaceFiles();
  } catch (e) {
    alert("Error al guardar archivo: " + e);
  }
}

// 8b. Historial de conversaciones
async function loadSessions() {
  const list = document.getElementById("historyList");
  const q = document.getElementById("historySearch")?.value.trim() || "";
  try {
    const res = await fetch(`/api/sessions${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    const sessions = await res.json();
    const active = sessions.find(s => s.active);
    const firstLoad = !activeSessionId;
    if (active && firstLoad) activeSessionId = active.id;
    renderHistory(sessions, q);
    // Al abrir EDITH, mostrar la conversación en curso en lugar de un chat vacío
    if (firstLoad && active && active.messages_count > 0 && !q) openSession(active.id);
  } catch (e) {
    list.innerHTML = `<div class="history-empty">No se pudo cargar el historial.</div>`;
  }
}

function historyGroupLabel(iso) {
  if (!iso) return "Anteriores";
  const d = new Date(iso);
  const today = new Date();
  const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOfDay(today) - startOfDay(d)) / 86400000);
  if (days <= 0) return "Hoy";
  if (days === 1) return "Ayer";
  if (days < 7) return "Últimos 7 días";
  if (days < 30) return "Últimos 30 días";
  return d.toLocaleDateString("es", { month: "long", year: "numeric" });
}

function renderHistory(sessions, query) {
  const list = document.getElementById("historyList");
  list.innerHTML = "";
  if (!sessions.length) {
    list.innerHTML = `<div class="history-empty">${query ? "Sin resultados." : "Aún no hay conversaciones."}</div>`;
    return;
  }
  let lastGroup = null;
  sessions.forEach(s => {
    const group = historyGroupLabel(s.updated_at);
    if (group !== lastGroup) {
      const g = document.createElement("div");
      g.className = "history-group";
      g.textContent = group;
      list.appendChild(g);
      lastGroup = group;
    }
    const item = document.createElement("div");
    item.className = "history-item" + (s.id === activeSessionId ? " active" : "");
    item.setAttribute("role", "listitem");
    const time = s.updated_at ? new Date(s.updated_at).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" }) : "";
    const meta = s.match ? `“${s.match}”` : `${s.messages_count} mensajes${time ? " · " + time : ""}`;
    item.innerHTML = `
      <button class="history-main" title="${escapeHtml(s.title)}">
        <span class="history-title">${escapeHtml(s.title)}</span>
        <span class="history-meta">${escapeHtml(meta)}</span>
      </button>
      <div class="history-actions">
        <button data-act="obsidian" title="Guardar en Obsidian">💎</button>
        <button data-act="rename" title="Renombrar">✎</button>
        <button data-act="delete" class="danger" title="Eliminar">🗑</button>
      </div>
    `;
    item.querySelector(".history-main").addEventListener("click", () => openSession(s.id));
    item.querySelector('[data-act="rename"]').addEventListener("click", () => renameSession(s.id, s.title));
    item.querySelector('[data-act="delete"]').addEventListener("click", () => deleteSession(s.id, s.title));
    item.querySelector('[data-act="obsidian"]').addEventListener("click", () => exportSessionToObsidian(s.id));
    list.appendChild(item);
  });
}

async function openSession(id) {
  try {
    const loadRes = await fetch(`/api/sessions/${encodeURIComponent(id)}/load`, { method: "POST" });
    if (!loadRes.ok) throw new Error("No encontrada");
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`);
    const data = await res.json();
    activeSessionId = id;
    resetStreamingBubble();
    const container = document.getElementById("chatMessages");
    container.innerHTML = "";
    data.messages.forEach(m => {
      if (m.role === "user") appendUserMessage(m.content);
      else if (m.role === "assistant") appendAssistantMessage(m.content);
      else if (m.role === "tool") appendToolCallBanner(m.tool, m.args || {});
    });
    if (!data.messages.length) showWelcomeMessage();
    document.getElementById("thoughtLine").style.display = "none";
    loadSessions();
    closeMobileSidebar();
  } catch (e) {
    alert("No se pudo abrir la conversación.");
  }
}

async function renameSession(id, currentTitle) {
  const title = prompt("Nuevo nombre para la conversación:", currentTitle);
  if (!title || !title.trim() || title === currentTitle) return;
  await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title.trim() })
  });
  loadSessions();
}

async function deleteSession(id, title) {
  if (!confirm(`¿Eliminar la conversación "${title}"? No se puede deshacer.`)) return;
  const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) return;
  const data = await res.json();
  if (id === activeSessionId) {
    activeSessionId = data.active_id;
    document.getElementById("chatMessages").innerHTML = "";
    showWelcomeMessage();
  }
  loadSessions();
}

async function exportSessionToObsidian(id) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}/obsidian`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error");
    alert(`Guardada en Obsidian: ${data.note}`);
  } catch (e) {
    alert("No se pudo guardar en Obsidian: " + e.message);
  }
}

async function startNewSession() {
  // Limpiar la vista primero: si se escribe rápido, el mensaje nuevo no debe borrarse después
  resetStreamingBubble();
  showWelcomeMessage();
  try {
    const res = await fetch("/api/sessions/new", { method: "POST" });
    const data = await res.json();
    activeSessionId = data.id;
  } catch (e) {}
  loadSessions();
}

function showWelcomeMessage() {
  const container = document.getElementById("chatMessages");
  container.innerHTML = `
    <div class="message assistant-msg">
      <div class="msg-header"><img class="avatar" src="logo.png" alt="EDITH"><span class="name">EDITH</span></div>
      <div class="msg-body"><p>Lista para un nuevo tema. ¿En qué te ayudo?</p></div>
    </div>
  `;
}

function setupReasoningToggle() {
  const btn = document.getElementById("btnReasoning");
  const order = ["auto", "fast", "deep"];
  const render = () => {
    btn.innerText = REASONING_MODES[reasoningMode].label;
    btn.title = REASONING_MODES[reasoningMode].title;
    btn.classList.toggle("fast", reasoningMode === "fast");
    btn.classList.toggle("deep", reasoningMode === "deep");
  };
  btn.addEventListener("click", () => {
    reasoningMode = order[(order.indexOf(reasoningMode) + 1) % order.length];
    try { localStorage.setItem("edith.reasoning", reasoningMode); } catch (e) {}
    render();
  });
  render();
}

function setupHistory() {
  const search = document.getElementById("historySearch");
  search.addEventListener("input", () => {
    clearTimeout(historySearchTimer);
    historySearchTimer = setTimeout(loadSessions, 250);
  });
}

async function loadLearnings() {
  try {
    const res = await fetch("/api/learnings");
    const learnings = await res.json();
    const list = document.getElementById("learningsList");
    list.innerHTML = "";
    if (!learnings || learnings.length === 0) {
      list.innerHTML = `<p class="empty-state">No hay errores registrados.</p>`;
      return;
    }
    learnings.forEach(l => {
      const card = document.createElement("div");
      card.className = "learning-card";
      card.innerHTML = `
        <div class="task">${escapeHtml(l.task || 'Regla')}</div>
        <div class="lesson">${escapeHtml(l.lesson || '')}</div>
      `;
      list.appendChild(card);
    });
  } catch (e) {}
}

// 8b. Machine Learning
const ML_ROUTE_LABELS = {
  direct: "Directo", web_search: "Búsqueda web", coworking: "Equipo (Co-Working)", workspace: "Archivo / código"
};

async function loadMlStatus() {
  const box = document.getElementById("mlStats");
  if (!box) return;
  try {
    const st = await (await fetch("/api/ml/status")).json();
    if (!st.enabled) { box.innerText = "ML desactivado (instala scikit-learn)."; return; }
    box.innerText = `Recuerdos: ${st.recuerdos} · Correcciones aprendidas: ${st.actualizaciones_router}`;
  } catch (e) { box.innerText = "No se pudo leer el estado del ML."; }
}

function showMlRoute(data) {
  const label = ML_ROUTE_LABELS[data.route] || data.route;
  document.getElementById("mlLast").innerText =
    `Última consulta → ${label} (${Math.round(data.confidence * 100)}%). Modo usado: ${data.mode === "coworking" ? "equipo" : "directo"}.`;
  document.getElementById("mlFix").style.display = "flex";
  document.getElementById("coworkingMonitor").style.display = data.mode === "coworking" ? "grid" : "none";
}

function setupMlListeners() {
  const refresh = document.getElementById("btnRefreshMl");
  if (!refresh) return;
  refresh.addEventListener("click", loadMlStatus);
  document.getElementById("btnMlTrain").addEventListener("click", async () => {
    try {
      const r = await (await fetch("/api/ml/train", { method: "POST" })).json();
      document.getElementById("mlLast").innerText = `${r.indexed} mensajes nuevos indexados.`;
    } catch (e) {}
    loadMlStatus();
  });
  document.querySelectorAll("#mlFix button").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!lastMlQuery) return;
      try {
        await fetch("/api/ml/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: lastMlQuery, route: btn.dataset.route })
        });
        document.getElementById("mlLast").innerText = `Aprendido: esa consulta va a «${ML_ROUTE_LABELS[btn.dataset.route]}».`;
        document.getElementById("mlFix").style.display = "none";
      } catch (e) {}
      loadMlStatus();
    });
  });
  loadMlStatus();
}

// 9. Event Listeners
function setupEventListeners() {
  const form = document.getElementById("chatForm");
  const input = document.getElementById("promptInput");

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || !ws) return;

    appendUserMessage(text);
    lastMlQuery = text;
    input.value = "";
    input.style.height = "auto";

    document.getElementById("thoughtContent").innerText = "";
    document.getElementById("thoughtContent").style.display = "none";
    document.getElementById("btnToggleThought").innerText = "Ver pasos";
    document.getElementById("thoughtIndicator").innerText = "Razonando...";
    document.getElementById("thoughtIndicator").classList.add("active");

    ws.send(JSON.stringify({
      action: "query",
      prompt: text,
      mode: currentMode,
      reasoning: reasoningMode,
      speak: voiceEnabled
    }));
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event("submit"));
    }
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });

  // Botón Micrófono
  const btnMic = document.getElementById("btnMicInput");
  btnMic.addEventListener("click", () => {
    triggerWakeAction("");
  });

  // Wake Word Toggle
  const btnWake = document.getElementById("btnWakeWord");
  btnWake.addEventListener("click", () => {
    wakeWordActive = !wakeWordActive;
    if (wakeWordActive) {
      btnWake.classList.add("active");
      document.getElementById("wakeWordLabel").innerText = `🎙️ "Oye EDITH" Activo`;
      try { recognition.start(); } catch (err) {}
    } else {
      btnWake.classList.remove("active");
      document.getElementById("wakeWordLabel").innerText = `🔇 "Oye EDITH" Pausa`;
      try { recognition.stop(); } catch (err) {}
    }
  });

  // Selector de Voz
  document.getElementById("voiceSelect").addEventListener("change", async (e) => {
    try {
      await fetch("/api/voice/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice_key: e.target.value })
      });
    } catch (err) {}
  });

  // Toggle de Sonido
  const btnVoice = document.getElementById("btnVoiceToggle");
  btnVoice.addEventListener("click", () => {
    voiceEnabled = !voiceEnabled;
    btnVoice.innerText = voiceEnabled ? "🔊" : "🔇";
    if (!voiceEnabled) document.getElementById("edithAudio").pause();
  });

  // Tabs Centro: Notas, Código, Diagramas
  document.getElementById("tabDailyView").addEventListener("click", () => {
    document.getElementById("editorBodyView").style.display = "block";
    document.getElementById("diagramBodyView").style.display = "none";
    openWorkspaceFile("notas_del_dia.md", true);
  });

  document.getElementById("tabCodeView").addEventListener("click", () => {
    document.getElementById("editorBodyView").style.display = "block";
    document.getElementById("diagramBodyView").style.display = "none";
    openWorkspaceFile("codigo.py", true);
  });

  document.getElementById("tabDiagramView").addEventListener("click", () => {
    document.getElementById("tabDiagramView").classList.add("active");
    document.getElementById("tabDailyView").classList.remove("active");
    document.getElementById("tabCodeView").classList.remove("active");
    document.getElementById("editorBodyView").style.display = "none";
    document.getElementById("diagramBodyView").style.display = "flex";
  });

  // Modos: Tú a Tú vs Co-Working
  const btnStandard = document.getElementById("btnModeStandard");
  const btnCoworking = document.getElementById("btnModeCoworking");
  const monitor = document.getElementById("coworkingMonitor");

  const btnAuto = document.getElementById("btnModeAuto");
  const modeButtons = [btnStandard, btnCoworking, btnAuto];
  const setMode = (mode, activeBtn, showMonitor) => {
    currentMode = mode;
    modeButtons.forEach(b => b.classList.remove("active"));
    activeBtn.classList.add("active");
    monitor.style.display = showMonitor ? "grid" : "none";
  };

  btnStandard.addEventListener("click", () => setMode("standard", btnStandard, false));
  btnCoworking.addEventListener("click", () => setMode("coworking", btnCoworking, true));
  btnAuto.addEventListener("click", () => setMode("auto", btnAuto, false));
  setupMlListeners();

  document.getElementById("btnSaveFile").addEventListener("click", saveCurrentFile);
  document.getElementById("btnRefreshSystem").addEventListener("click", loadSystemStatus);
  document.getElementById("btnRefreshLearnings").addEventListener("click", loadLearnings);

  // Descarga de Diagrama SVG
  document.getElementById("btnExportDiagram").addEventListener("click", () => {
    const svgEl = document.querySelector("#diagramRenderArea svg");
    if (!svgEl) return alert("No hay diagrama generado para exportar.");
    const blob = new Blob([svgEl.outerHTML], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "edith_diagrama.svg";
    a.click();
  });

  // Pestañas dentro del panel lateral (Archivos / Editor / Laptop / Evolución)
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");
    });
  });

  setupDrawer();
  setupSidebar();
  setupHistory();
  setupReasoningToggle();
  setupThoughtToggle();
}

// 10. Panel lateral (drawer): Archivos, Editor, Laptop, Evolución
function openDrawerTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
  document.querySelector(`.tab-btn[data-tab="${tabId}"]`)?.classList.add("active");
  document.getElementById(tabId)?.classList.add("active");
  document.getElementById("detailsDrawer").classList.add("open");
  document.getElementById("drawerBackdrop").classList.add("visible");
}

function closeDrawer() {
  document.getElementById("detailsDrawer").classList.remove("open");
  document.getElementById("drawerBackdrop").classList.remove("visible");
}

function setupDrawer() {
  document.querySelectorAll(".tool-btn[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => openDrawerTab(btn.dataset.tab));
  });
  document.getElementById("btnCloseDrawer").addEventListener("click", closeDrawer);
  document.getElementById("drawerBackdrop").addEventListener("click", () => {
    closeDrawer();
    closeMobileSidebar();
  });
}

// 11. Barra lateral: colapsar en escritorio, off-canvas en móvil
function setupSidebar() {
  const sidebar = document.getElementById("sidebar");

  document.getElementById("btnCollapseSidebar").addEventListener("click", () => {
    sidebar.classList.toggle("collapsed");
  });

  const btnOpenMobile = document.getElementById("btnSidebarOpenMobile");
  if (btnOpenMobile) {
    btnOpenMobile.addEventListener("click", () => {
      sidebar.classList.add("mobile-open");
      document.getElementById("drawerBackdrop").classList.add("visible");
    });
  }

  // "Nueva conversación": abre una sesión nueva (la anterior queda en el historial)
  document.getElementById("btnNewSession").addEventListener("click", () => {
    startNewSession();
    closeMobileSidebar();
  });
}

function closeMobileSidebar() {
  document.getElementById("sidebar").classList.remove("mobile-open");
  if (!document.getElementById("detailsDrawer").classList.contains("open")) {
    document.getElementById("drawerBackdrop").classList.remove("visible");
  }
}

// 12. Mostrar/ocultar el detalle del razonamiento paso a paso
function setupThoughtToggle() {
  const btn = document.getElementById("btnToggleThought");
  const content = document.getElementById("thoughtContent");
  btn.addEventListener("click", () => {
    const visible = content.style.display !== "none";
    content.style.display = visible ? "none" : "block";
    btn.innerText = visible ? "Ver pasos" : "Ocultar";
  });
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return text.replace(/[&<>"']/g, (m) => map[m]);
}
window.launchApp = launchApp;
window.adjustVolume = adjustVolume;
