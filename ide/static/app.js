// EDITH Desktop Companion, System Control, Diagrams & Wake Word Controller
let ws = null;
let currentMode = "standard"; // 'standard', 'coworking' o 'auto' (decide el ML)
let lastMlQuery = "";
let voiceEnabled = true;
let activeFilePath = "notas_del_dia.md";
let recognition = null;
let wakeWordActive = true;
let isListeningForCommand = false;

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
      document.getElementById("thoughtLine").style.display = "flex";
      thoughtIndicator.innerText = `Razonando paso ${data.iteration}`;
      thoughtIndicator.classList.add("active");
      break;

    case "thought_chunk":
      thoughtContent.innerText += data.chunk;
      thoughtContent.scrollTop = thoughtContent.scrollHeight;
      break;

    case "tool_call":
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
      appendAssistantMessage(data.content, data.sources);
      if (data.audio_url && voiceEnabled) {
        playVoiceAudio(data.audio_url);
      }
      loadWorkspaceFiles();
      checkAndRenderDiagramsInText(data.content);
      break;

    case "error":
      thoughtIndicator.innerText = "Error";
      thoughtIndicator.classList.remove("active");
      appendAssistantMessage(`⚠️ **Error:** ${data.message}`);
      break;
  }
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

function appendAssistantMessage(markdownContent, sources = []) {
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
      <span class="avatar">👓</span>
      <span class="name">EDITH</span>
      <span class="time">Ahora</span>
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
  
  let icon = "👓";
  if (data.member === "Scout") icon = "🕵️";
  if (data.member === "Auditor") icon = "🧐";

  item.innerHTML = `
    <div class="msg-header">
      <span class="avatar">${icon}</span>
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

async function loadSessions() {
  try {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();
    const select = document.getElementById("sessionSelect");
    select.innerHTML = "";
    sessions.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.innerText = `${s.title} (${s.messages_count} msgs)`;
      select.appendChild(opt);
    });
  } catch (e) {}
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

  // "Nueva conversación": limpia el hilo visible (no borra el historial guardado)
  document.getElementById("btnNewSession").addEventListener("click", () => {
    const container = document.getElementById("chatMessages");
    container.innerHTML = `
      <div class="message assistant-msg">
        <div class="msg-header"><span class="avatar">👓</span><span class="name">EDITH</span></div>
        <div class="msg-body"><p>Lista para un nuevo tema. ¿En qué te ayudo?</p></div>
      </div>
    `;
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
