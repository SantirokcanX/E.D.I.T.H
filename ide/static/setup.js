// EDITH · Asistente de primer arranque y panel de Ajustes (Fase 15.2)
//
// Un solo esquema (GET /api/settings) dibuja los dos: el asistente recorre las secciones
// paso a paso y el panel de Ajustes las muestra en pestañas. Todo el texto se inserta con
// textContent (nunca HTML crudo).

const EdithSetup = (() => {
  let schema = [];
  let values = {};
  let desktop = false;
  let hardware = null;
  let pollTimer = null;

  // ------------------------------------------------------------ utilidades
  async function api(url, options = {}) {
    const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
    let data = null;
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) {
      const err = new Error((data && typeof data.detail === "string" && data.detail) || `Error ${res.status}`);
      err.detail = data && data.detail;
      throw err;
    }
    return data;
  }

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }

  const allFields = () => schema.flatMap((s) => s.fields);
  const fieldDef = (key) => allFields().find((f) => f.key === key);

  async function loadSettings() {
    const data = await api("/api/settings");
    schema = data.schema;
    values = data.values;
    const status = await api("/api/setup/status");
    desktop = status.desktop;
    return status;
  }

  function openExternal(url) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_url) window.pywebview.api.open_url(url);
    else window.open(url, "_blank", "noopener");
  }

  // ------------------------------------------------------------ campos
  function renderField(f) {
    const value = values[f.key];
    const id = `es-${f.key}`;
    const error = el("div", { class: "es-error", role: "alert" });
    let input;
    let get;
    let extra = null;

    switch (f.type) {
      case "bool": {
        input = el("input", { type: "checkbox", id, class: "es-switch" });
        input.checked = !!value;
        get = () => input.checked;
        const row = el("label", { class: "es-bool" + (f.danger ? " es-danger" : ""), for: id }, input, el("span", { text: f.label }));
        const wrap = el("div", { class: "es-field" }, row, f.help ? el("div", { class: "es-help", text: f.help }) : null, error);
        if (f.danger) {
          input.addEventListener("change", () => {
            if (input.checked && !confirm(`${f.label}\n\n${f.help || ""}\n\n¿Activarlo de todos modos?`)) input.checked = false;
          });
        }
        return { key: f.key, node: wrap, get, error };
      }
      case "select":
      case "voice": {
        input = el("select", { id });
        for (const [v, label] of f.options) input.appendChild(el("option", { value: v, text: label }));
        input.value = value ?? "";
        get = () => input.value;
        if (f.type === "voice") {
          const play = el("button", { type: "button", class: "es-btn es-btn-ghost", text: "▶ Escuchar" });
          play.addEventListener("click", async () => {
            play.disabled = true;
            play.textContent = "Generando…";
            try {
              const { audio_url, offline } = await api("/api/setup/voice/sample", { method: "POST", body: JSON.stringify({ voice_key: input.value }) });
              // Sin conexión con el servicio de voz neural, todas las muestras suenan con la voz de Windows
              error.textContent = offline ? "Sin conexión con el servicio de voz: esta muestra usa la voz de Windows, no la elegida." : "";
              const audio = new Audio(audio_url);
              await audio.play();
            } catch (e) {
              error.textContent = e.message;
            } finally {
              play.disabled = false;
              play.textContent = "▶ Escuchar";
            }
          });
          extra = play;
        }
        break;
      }
      case "multi": {
        const boxes = f.options.map(([v, label]) => {
          const cb = el("input", { type: "checkbox", value: v });
          cb.checked = (value || []).includes(v);
          return { cb, node: el("label", { class: "es-check" }, cb, el("span", { text: label })) };
        });
        input = el("div", { class: "es-checks" }, boxes.map((b) => b.node));
        get = () => boxes.filter((b) => b.cb.checked).map((b) => b.cb.value);
        break;
      }
      case "phones": {
        input = el("textarea", { id, rows: "2", placeholder: "+5215512345678, +5215587654321" });
        input.value = (value || []).join(", ");
        // Separar solo por comas, punto y coma o saltos de línea: "+52 155 1234 5678" es UN número
        get = () => input.value.split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean);
        break;
      }
      case "timerange": {
        const [a, b] = String(value || "23:00-07:00").split("-");
        const from = el("input", { type: "time", value: a });
        const to = el("input", { type: "time", value: b });
        input = el("div", { class: "es-range" }, from, el("span", { text: "a" }), to);
        get = () => `${from.value}-${to.value}`;
        break;
      }
      case "model": {
        input = el("input", { id, list: "es-model-list", value: value || "", autocomplete: "off", spellcheck: "false" });
        get = () => input.value.trim();
        input.addEventListener("change", () => document.dispatchEvent(new CustomEvent("es-models-changed")));
        break;
      }
      case "folder": {
        input = el("input", { id, value: value || "", spellcheck: "false" });
        get = () => input.value.trim();
        const info = el("div", { class: "es-help" });
        const check = async (create = false) => {
          error.textContent = "";
          info.textContent = "Comprobando…";
          try {
            const r = await api("/api/setup/vault/check", { method: "POST", body: JSON.stringify({ path: input.value, create }) });
            input.value = r.path;
            info.replaceChildren();
            if (!r.exists) {
              info.append("Esa carpeta no existe. ",
                el("button", { type: "button", class: "es-link", text: "Crearla como bóveda nueva", onclick: () => check(true) }));
            } else if (!r.writable) {
              error.textContent = "EDITH no puede escribir en esa carpeta.";
              info.textContent = "";
            } else {
              const kind = r.is_obsidian ? "Bóveda de Obsidian" : "Carpeta";
              info.append(`✓ ${kind} con ${r.notes} nota(s). `);
              if (!r.has_structure) {
                info.append(el("button", { type: "button", class: "es-link", text: "Crear carpetas 00-04 de EDITH", onclick: () => check(true) }));
              } else {
                info.append("Estructura de EDITH lista.");
              }
            }
          } catch (e) {
            error.textContent = e.message;
            info.textContent = "";
          }
        };
        const buttons = [];
        if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder) {
          buttons.push(el("button", {
            type: "button", class: "es-btn es-btn-ghost", text: "Elegir…",
            onclick: async () => {
              const picked = await window.pywebview.api.pick_folder(input.value);
              if (picked) { input.value = picked; check(); }
            },
          }));
        }
        buttons.push(el("button", { type: "button", class: "es-btn es-btn-ghost", text: "Comprobar", onclick: () => check() }));
        extra = el("div", { class: "es-row-buttons" }, buttons);
        const wrap = el("div", { class: "es-field" },
          el("label", { for: id, text: f.label }), f.help ? el("div", { class: "es-help", text: f.help }) : null,
          el("div", { class: "es-inline" }, input, extra), info, error);
        if (input.value) setTimeout(() => check(), 0);
        return { key: f.key, node: wrap, get, error };
      }
      case "number":
        input = el("input", { id, type: "number", min: f.min, max: f.max, value: value ?? "" });
        get = () => input.value;
        break;
      case "time":
        input = el("input", { id, type: "time", value: value || "" });
        get = () => input.value;
        break;
      case "secret":
        input = el("input", { id, type: "password", value: value || "", autocomplete: "off", placeholder: value ? "" : "sin configurar" });
        get = () => input.value;
        break;
      default:
        input = el("input", { id, type: "text", value: value ?? "", spellcheck: "false" });
        get = () => input.value;
    }
    const label = el("label", { for: id, text: f.label, class: f.danger ? "es-danger" : null });
    const wrap = el("div", { class: "es-field" }, label, f.help ? el("div", { class: "es-help", text: f.help }) : null,
      extra ? el("div", { class: "es-inline" }, input, extra) : input, error);
    if (f.restart) wrap.appendChild(el("div", { class: "es-help", text: "Se aplica al reiniciar EDITH." }));
    return { key: f.key, node: wrap, get, error };
  }

  async function saveFields(fields, statusNode) {
    fields.forEach((f) => (f.error.textContent = ""));
    const payload = {};
    fields.forEach((f) => (payload[f.key] = f.get()));
    try {
      const res = await api("/api/settings", { method: "POST", body: JSON.stringify({ values: payload }) });
      Object.assign(values, payload);
      if (statusNode) {
        statusNode.className = "es-status ok";
        statusNode.textContent = res.changed.length
          ? `✓ Guardado${res.restart_required.length ? ". Reinicia EDITH para aplicar: " + res.restart_required.join(", ") : " y aplicado."}`
          : "✓ Sin cambios.";
      }
      return true;
    } catch (e) {
      const errors = e.detail && typeof e.detail === "object" ? e.detail : null;
      if (errors) {
        for (const [key, msg] of Object.entries(errors)) {
          const f = fields.find((x) => x.key === key);
          if (f) f.error.textContent = msg;
        }
      }
      if (statusNode) {
        statusNode.className = "es-status err";
        statusNode.textContent = errors ? "Revisa los campos marcados." : e.message;
      }
      return false;
    }
  }

  // ------------------------------------------------------------ equipo y modelos
  async function renderHardware(container, modelFields) {
    container.replaceChildren(el("div", { class: "es-help", text: "Analizando tu equipo…" }));
    const fast = modelFields.find((f) => f.key === "OLLAMA_MODEL");
    const deep = modelFields.find((f) => f.key === "OLLAMA_DEEP_MODEL");
    try {
      hardware = await api(`/api/setup/hardware?fast=${encodeURIComponent(fast?.get() || "")}&deep=${encodeURIComponent(deep?.get() || "")}`);
    } catch (e) {
      container.replaceChildren(el("div", { class: "es-error", text: `No pude analizar el equipo: ${e.message}` }));
      return;
    }
    const h = hardware;
    const gpu = h.best_gpu;
    const cards = el("div", { class: "es-cards" },
      el("div", { class: "es-card" }, el("strong", { text: "Procesador" }), el("span", { text: `${h.system.cpu}` }), el("small", { text: `${h.system.cores} hilos · ${h.system.ram_gb} GB de RAM` })),
      el("div", { class: "es-card" }, el("strong", { text: "Gráfica" }),
        el("span", { text: gpu ? gpu.name : "No detectada" }),
        el("small", { text: gpu ? `${gpu.vram_gb} GB de VRAM${gpu.dedicated ? "" : " (integrada)"}` : "" })),
      el("div", { class: "es-card" + (h.disk_ok ? "" : " es-card-warn") }, el("strong", { text: "Disco para modelos" }),
        el("span", { text: `${h.models_disk.free_gb} GB libres` }), el("small", { text: h.models_disk.drive })),
      el("div", { class: "es-card" + (h.ollama.running ? "" : " es-card-warn") }, el("strong", { text: "Ollama" }),
        el("span", { text: h.ollama.running ? `Activo (v${h.ollama.version})` : h.ollama.installed ? "Instalado, no responde" : "No instalado" }),
        el("small", { text: `${h.ollama.models.length} modelo(s)` })),
    );

    // lista de modelos para los campos: instalados + recomendados + conocidos
    const installed = new Set(h.ollama.models.map((m) => m.name.replace(/:latest$/, "")));
    let list = document.getElementById("es-model-list");
    if (!list) { list = el("datalist", { id: "es-model-list" }); document.body.appendChild(list); }
    list.replaceChildren(...[...new Set([...installed, ...Object.keys(h.model_sizes_gb)])].map((m) =>
      el("option", { value: m, label: installed.has(m) ? "instalado" : `descargar ~${h.model_sizes_gb[m] ?? "?"} GB` })));

    const rec = h.recommendation;
    const recBox = el("div", { class: "es-reco" },
      el("div", {}, el("strong", { text: "Recomendado para tu equipo: " }), `${rec.fast} (rápido) + ${rec.deep} (profundo)`),
      el("div", { class: "es-help", text: rec.why }));
    if ((fast && fast.get() !== rec.fast) || (deep && deep.get() !== rec.deep)) {
      recBox.appendChild(el("button", {
        type: "button", class: "es-link", text: "Usar la recomendación",
        onclick: () => {
          const fi = fast.node.querySelector("input"); const di = deep.node.querySelector("input");
          fi.value = rec.fast; di.value = rec.deep;
          renderHardware(container, modelFields);
        },
      }));
    }

    const dl = el("div", { class: "es-download" });
    const renderDownload = () => {
      dl.replaceChildren();
      if (!h.ollama.installed) {
        dl.append(el("div", { class: "es-warn", text: "Para pensar, EDITH necesita Ollama (gratis). Instálalo y pulsa «Volver a analizar»." }),
          el("div", { class: "es-row-buttons" },
            el("button", { type: "button", class: "es-btn", text: "Descargar Ollama", onclick: () => openExternal("https://ollama.com/download/windows") }),
            el("button", { type: "button", class: "es-btn es-btn-ghost", text: "Volver a analizar", onclick: () => renderHardware(container, modelFields) })));
        return;
      }
      if (!h.models_needed.length) {
        dl.append(el("div", { class: "es-ok", text: "✓ Los modelos elegidos ya están descargados." }));
        return;
      }
      const gb = h.download_gb;
      dl.append(el("div", { class: h.disk_ok ? "es-help" : "es-warn",
        text: `Falta descargar ${h.models_needed.join(" y ")} (~${gb} GB).` + (h.disk_ok ? "" : ` Solo hay ${h.models_disk.free_gb} GB libres: libera espacio antes.`) }));
      const btn = el("button", { type: "button", class: "es-btn", text: `Descargar (${gb} GB)` });
      btn.disabled = !h.disk_ok;
      btn.addEventListener("click", () => startDownload(h.models_needed, dl, () => renderHardware(container, modelFields)));
      dl.append(btn);
    };
    renderDownload();
    container.replaceChildren(cards, recBox, dl);
    // si ya hay una descarga en marcha (p. ej. se reabrió el asistente), mostrar su progreso
    try {
      const p = await api("/api/setup/models/progress");
      if (p.running) watchDownload(dl, () => renderHardware(container, modelFields));
    } catch (e) {}
  }

  async function startDownload(models, box, onDone) {
    try {
      await api("/api/setup/models/pull", { method: "POST", body: JSON.stringify({ models }) });
    } catch (e) {
      box.append(el("div", { class: "es-error", text: e.message }));
      return;
    }
    watchDownload(box, onDone);
  }

  function fmtGB(bytes) { return (bytes / 1024 ** 3).toFixed(2); }

  function watchDownload(box, onDone) {
    clearInterval(pollTimer);
    const view = el("div", { class: "es-progress-list" });
    const cancel = el("button", { type: "button", class: "es-btn es-btn-ghost", text: "Pausar",
      onclick: () => api("/api/setup/models/cancel", { method: "POST" }) });
    box.replaceChildren(view, cancel);
    const tick = async () => {
      let p;
      try { p = await api("/api/setup/models/progress"); } catch (e) { return; }
      view.replaceChildren(...p.items.map((it) => {
        const pct = it.total ? Math.round((100 * it.completed) / it.total) : (it.status === "listo" ? 100 : 0);
        return el("div", { class: "es-progress" },
          el("div", { class: "es-progress-head" }, el("strong", { text: it.model }),
            el("span", { text: it.total ? `${fmtGB(it.completed)} / ${fmtGB(it.total)} GB · ${pct}%` : it.status })),
          el("div", { class: "es-bar" }, el("div", { class: "es-bar-fill" + (it.status === "error" ? " err" : ""), style: `width:${pct}%` })),
          el("small", { text: it.status === "error" ? it.message : it.message || it.status }));
      }));
      if (p.finished) {
        clearInterval(pollTimer);
        cancel.textContent = p.ok ? "✓ Listo" : "Reintentar";
        cancel.onclick = p.ok ? null : () => onDone();
        if (p.ok) setTimeout(onDone, 1200);
      }
    };
    tick();
    pollTimer = setInterval(tick, 1000);
  }

  // ------------------------------------------------------------ ventana modal
  function modal(className) {
    const panel = el("div", { class: `es-panel ${className}`, role: "dialog", "aria-modal": "true" });
    const backdrop = el("div", { class: "es-backdrop" }, panel);
    document.body.appendChild(backdrop);
    const close = () => { clearInterval(pollTimer); backdrop.remove(); };
    return { panel, close };
  }

  // ------------------------------------------------------------ asistente de primer arranque
  const STEPS = [
    { id: "bienvenida", title: "Hola, soy EDITH 👓", text: "Vamos a dejarme lista en un par de minutos. Todo se puede cambiar después en Ajustes.", keys: ["USER_NAME"] },
    { id: "equipo", title: "Tu equipo y mis modelos", text: "Elijo los modelos de IA según tu tarjeta gráfica para responder rápido.", keys: ["OLLAMA_MODEL", "OLLAMA_DEEP_MODEL"], hardware: true },
    { id: "obsidian", title: "Tu bóveda de Obsidian", text: "Ahí guardaré notas, resúmenes y nuestras conversaciones.", keys: ["OBSIDIAN_VAULT_PATH", "OBSIDIAN_AUTO_SYNC"] },
    { id: "voz", title: "Elige mi voz", text: "Escucha cada una y quédate con la que más te guste.", keys: ["EDITH_VOICE", "VOICE_OFFLINE_FALLBACK"] },
    { id: "canales", title: "WhatsApp y teléfono", text: "Opcional: háblame desde el celular. Solo responderé a los números que pongas aquí.",
      keys: ["AUTHORIZED_PHONE_NUMBERS", "WHATSAPP_ENABLED", "WHATSAPP_VOICE_REPLIES"],
      advanced: ["OWNER_PHONE_NUMBER", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "PUBLIC_BASE_URL", "TWILIO_VOICE_MODE"] },
    { id: "autonomia", title: "Iniciativa propia", text: "Recordatorios, avisos y un resumen cada mañana.",
      keys: ["HEARTBEAT_ENABLED", "MORNING_BRIEFING_TIME", "QUIET_HOURS", "NOTIFY_CHANNELS", "HEARTBEAT_NEWS_TOPICS", "START_WITH_WINDOWS"] },
    { id: "listo", title: "¡Lista!", text: "Ya puedes hablarme. Si quieres cambiar algo, abre ⚙️ Ajustes en la barra lateral o en el icono junto al reloj.", final: true },
  ];

  async function openWizard() {
    await loadSettings();
    const { panel, close } = modal("es-wizard");
    let index = 0;
    const finish = async () => {
      try { await api("/api/setup/complete", { method: "POST" }); } catch (e) {}
      close();
      if (typeof loadStatus === "function") loadStatus();
    };

    const render = () => {
      clearInterval(pollTimer);
      const step = STEPS[index];
      const fields = (step.keys || []).map(fieldDef).filter(Boolean).map(renderField);
      const advanced = (step.advanced || []).map(fieldDef).filter(Boolean).map(renderField);
      const status = el("div", { class: "es-status" });
      const body = el("div", { class: "es-body" }, el("p", { class: "es-lead", text: step.text }));

      if (step.hardware) {
        const hw = el("div", { class: "es-hw" });
        body.append(hw, ...fields.map((f) => f.node));
        renderHardware(hw, fields);
        document.addEventListener("es-models-changed", () => renderHardware(hw, fields), { once: true });
      } else {
        body.append(...fields.map((f) => f.node));
      }
      if (advanced.length) {
        body.append(el("details", { class: "es-advanced" }, el("summary", { text: "Llamadas telefónicas con Twilio (opcional)" }), advanced.map((f) => f.node)));
      }
      if (step.id === "canales") {
        const qr = el("img", { class: "es-qr", alt: "QR para vincular WhatsApp", hidden: true });
        const qrBtn = el("button", { type: "button", class: "es-link", text: "Mostrar QR para vincular WhatsApp",
          onclick: async () => {
            const ok = await saveFields([...fields, ...advanced], status);
            if (!ok) return;
            qrBtn.textContent = "Esperando el QR…";
            for (let i = 0; i < 30; i++) {
              const r = await fetch(`/api/channels/whatsapp/qr?ts=${Date.now()}`);
              if (r.ok) { qr.src = URL.createObjectURL(await r.blob()); qr.hidden = false; qrBtn.textContent = "Escanéalo en WhatsApp → Dispositivos vinculados"; return; }
              await new Promise((res) => setTimeout(res, 1500));
            }
            qrBtn.textContent = "No apareció el QR: falta el componente de WhatsApp (edith-whatsapp.exe o Node). Mira Laptop → Canales.";
          } });
        body.append(qrBtn, qr);
      }
      if (step.final) {
        const summary = el("ul", { class: "es-summary" },
          el("li", { text: `Nombre: ${values.USER_NAME || "sin indicar"}` }),
          el("li", { text: `Modelos: ${values.OLLAMA_MODEL} + ${values.OLLAMA_DEEP_MODEL || "(el mismo)"}` }),
          el("li", { text: `Bóveda: ${values.OBSIDIAN_VAULT_PATH}` }),
          el("li", { text: `Voz: ${values.EDITH_VOICE}` }),
          el("li", { text: `WhatsApp: ${values.WHATSAPP_ENABLED ? "activado" : "desactivado"} · números autorizados: ${(values.AUTHORIZED_PHONE_NUMBERS || []).length}` }),
          el("li", { text: `Resumen matutino: ${values.MORNING_BRIEFING_TIME || "desactivado"}` }));
        body.append(summary);
      }

      const dots = el("div", { class: "es-dots" }, STEPS.map((s, i) => el("span", { class: i === index ? "on" : i < index ? "done" : "" })));
      const back = el("button", { type: "button", class: "es-btn es-btn-ghost", text: "Atrás", disabled: index === 0,
        onclick: () => { index--; render(); } });
      const next = el("button", { type: "button", class: "es-btn", text: step.final ? "Empezar" : "Siguiente" });
      next.addEventListener("click", async () => {
        if (step.final) return finish();
        next.disabled = true;
        const ok = await saveFields([...fields, ...advanced], status);
        next.disabled = false;
        if (ok) { index++; render(); }
      });
      const later = el("button", { type: "button", class: "es-link", text: "Configurar más tarde", onclick: finish });

      panel.replaceChildren(
        el("div", { class: "es-head" }, el("img", { src: "logo.png", alt: "", class: "es-logo" }),
          el("div", {}, el("small", { text: `Paso ${index + 1} de ${STEPS.length}` }), el("h2", { text: step.title })), dots),
        body,
        el("div", { class: "es-foot" }, later, status, el("div", { class: "es-row-buttons" }, back, next)));
    };
    render();
  }

  // ------------------------------------------------------------ panel de Ajustes
  async function openSettings() {
    if (document.querySelector(".es-backdrop")) return;
    await loadSettings();
    const { panel, close } = modal("es-settings");
    const rendered = [];
    const nav = el("nav", { class: "es-tabs", role: "tablist" });
    const pages = el("div", { class: "es-pages" });
    schema.forEach((section, i) => {
      const fields = section.fields.map(renderField);
      rendered.push(...fields);
      const page = el("section", { class: "es-page", hidden: i !== 0 }, el("h3", { text: `${section.icon} ${section.title}` }));
      if (section.id === "modelos") {
        const hw = el("div", { class: "es-hw" });
        page.append(hw);
        page.dataset.hardware = "1";
        page._hw = () => renderHardware(hw, fields);
        document.addEventListener("es-models-changed", () => renderHardware(hw, fields));
      }
      page.append(...fields.map((f) => f.node));
      const tab = el("button", { type: "button", role: "tab", class: i === 0 ? "active" : "", text: `${section.icon} ${section.title}` });
      tab.addEventListener("click", () => {
        nav.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
        tab.classList.add("active");
        pages.querySelectorAll(".es-page").forEach((p) => (p.hidden = p !== page));
        if (page._hw && !page._hwLoaded) { page._hwLoaded = true; page._hw(); }
      });
      nav.appendChild(tab);
      pages.appendChild(page);
    });
    const status = el("div", { class: "es-status" });
    const save = el("button", { type: "button", class: "es-btn", text: "Guardar cambios" });
    save.addEventListener("click", async () => {
      save.disabled = true;
      await saveFields(rendered, status);
      save.disabled = false;
    });
    panel.replaceChildren(
      el("div", { class: "es-head" }, el("h2", { text: "⚙️ Ajustes" }),
        el("button", { type: "button", class: "es-close", "aria-label": "Cerrar", text: "✕", onclick: close })),
      el("div", { class: "es-settings-body" }, nav, pages),
      el("div", { class: "es-foot" },
        el("button", { type: "button", class: "es-link", text: "Repetir el asistente", onclick: () => { close(); openWizard(); } }),
        status, save));
  }

  // ------------------------------------------------------------ arranque
  async function init() {
    const btn = document.getElementById("btnSettings");
    if (btn) btn.addEventListener("click", openSettings);
    try {
      const status = await api("/api/setup/status");
      if (!status.completed) openWizard();
    } catch (e) {}
  }

  document.addEventListener("DOMContentLoaded", init);
  return { openWizard, openSettings };
})();

window.EdithSetup = EdithSetup;
