// EDITH Rich Renderer (Fase 7): Markdown + fórmulas LaTeX (KaTeX) + bloques de código profesionales.
//
// Las fórmulas se extraen ANTES de pasar el texto por marked: si no, marked interpreta
// `_`, `*` y `\` dentro de la fórmula como Markdown y la rompe (p. ej. `\frac` → `frac`).
//
// Fase 14: todo el HTML resultante pasa por DOMPurify antes de insertarse. El texto lo escribe
// el modelo y puede venir influido por una web o un archivo: nada de <script>, atributos onclick/
// onerror, enlaces javascript:, <style> que tape la interfaz ni imágenes externas que filtren datos.

const EdithRender = (() => {
  const PURIFY_CONFIG = {
    FORBID_TAGS: ["style", "link", "meta", "base", "form", "input", "button", "textarea", "select", "option",
                  "iframe", "frame", "object", "embed", "audio", "video", "source", "track", "picture", "image", "use"],
    // id/name: el contenido no puede hacerse pasar por elementos de la interfaz (p. ej. el modal "¿Autorizas?")
    FORBID_ATTR: ["id", "name", "background", "srcset", "poster", "ping", "formaction"],
  };
  // CSS en línea que KaTeX no usa y que serviría para tapar la interfaz o cargar recursos externos
  const UNSAFE_STYLE = /url\s*\(|expression\s*\(|@import|position\s*:\s*(fixed|sticky)/i;
  let purifyReady = false;

  function setupPurify() {
    if (purifyReady || !window.DOMPurify) return !!window.DOMPurify;
    DOMPurify.addHook("afterSanitizeAttributes", (node) => {
      if (node.hasAttribute && node.hasAttribute("style") && UNSAFE_STYLE.test(node.getAttribute("style"))) {
        node.removeAttribute("style");
      }
      if (node.tagName === "A" && node.hasAttribute("href")) {
        node.setAttribute("target", "_blank"); // un enlace nunca saca a EDITH de su pestaña
        node.setAttribute("rel", "noopener noreferrer");
      }
    });
    purifyReady = true;
    return true;
  }

  function sanitize(html) {
    const clean = DOMPurify.sanitize(html, PURIFY_CONFIG);
    // Imágenes de otros servidores: se cambian por un enlace (cargarlas solas podría enviar datos
    // en la URL). Dentro de <template> nada se descarga mientras se revisa.
    const tpl = document.createElement("template");
    tpl.innerHTML = clean;
    tpl.content.querySelectorAll("img").forEach((img) => {
      const src = img.getAttribute("src") || "";
      let external = true;
      try {
        const u = new URL(src, window.location.href);
        external = u.origin !== window.location.origin && u.protocol !== "data:";
      } catch (e) {}
      if (!external) return;
      const a = document.createElement("a");
      a.textContent = `🖼️ ${img.getAttribute("alt") || "imagen externa"} (no se cargó: ábrela si confías en ella)`;
      if (/^https?:/i.test(src)) {
        a.href = src;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
      }
      img.replaceWith(a);
    });
    return tpl.innerHTML;
  }

  /** Sin las librerías (p. ej. sin internet) se muestra texto plano: nunca HTML sin sanear. */
  function plainHtml(text) {
    return `<p>${escapeAttr(text || "").replace(/\n/g, "<br>")}</p>`;
  }
  // Segmentos de código (no se busca LaTeX dentro de ellos)
  const CODE_RE = /(```[\s\S]*?(?:```|$)|`[^`\n]+`)/g;
  // Orden importa: primero los delimitadores de bloque
  const MATH_RES = [
    { re: /\$\$([\s\S]+?)\$\$/g, display: true },
    { re: /\\\[([\s\S]+?)\\\]/g, display: true },
    // Entornos de LaTeX sueltos (equation, align, gather...): después de $$ y \[ para no partirlos
    { re: /(\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}[\s\S]+?\\end\{\2\})/g, display: true },
    { re: /\\\(([\s\S]+?)\\\)/g, display: false },
    // $...$ en línea: sin espacio tras la apertura ni antes del cierre, y sin dígito pegado
    // después del cierre (así "cuesta $5 y $10" no se toma como fórmula).
    { re: /(^|[^\\$\w])\$(?!\s)([^\n$]+?)(?<!\s)\$(?!\d)/g, display: false, lead: true },
  ];

  function renderMath(tex, display) {
    if (!window.katex) return null;
    try {
      const html = katex.renderToString(tex, { displayMode: display, throwOnError: false, output: "html", strict: "ignore" });
      const src = escapeAttr((display ? "$$" : "$") + tex + (display ? "$$" : "$"));
      const cls = display ? "math-block" : "math-inline";
      return `<span class="${cls}" data-latex="${src}" title="Doble clic para copiar en LaTeX">${html}</span>`;
    } catch (e) {
      return null;
    }
  }

  function escapeAttr(s) {
    return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function protectMath(text, store) {
    return text.split(CODE_RE).map((part, i) => {
      if (i % 2 === 1) return part; // código: intacto
      for (const { re, display, lead } of MATH_RES) {
        part = part.replace(re, (m, a, b) => {
          const prefix = lead ? a : "";
          const tex = (lead ? b : a).trim();
          const html = renderMath(tex, display);
          if (html === null) return m;
          store.push(html);
          // Token alfanumérico: marked no lo altera
          return `${prefix}EDITHMATH${store.length - 1}X`;
        });
      }
      return part;
    }).join("");
  }

  function restoreMath(html, store) {
    return html.replace(/EDITHMATH(\d+)X/g, (m, i) => store[+i] ?? m);
  }

  // Ecuaciones numeradas (Fase 7), como en LaTeX: una ecuación en bloque con \label{…} o un entorno
  // equation/align/gather sin asterisco recibe un número (\tag{n}); \eqref{…} y \ref{…} lo citan.
  const DISPLAY_RE = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}[\s\S]+?\\end\{\2\})/g;
  const NUMBERED_ENV = /\\begin\{(equation|align|gather|multline)\}/;

  function numberEquations(text) {
    const parts = text.split(CODE_RE);
    const labels = {};
    let n = 0;
    for (let i = 0; i < parts.length; i += 2) {
      parts[i] = parts[i].replace(DISPLAY_RE, (block) => {
        const label = block.match(/\\label\{([^}]+)\}/);
        if (!label && !NUMBERED_ENV.test(block)) return block;
        let out = block.replace(/\\label\{[^}]+\}/g, "");
        if (/\\tag\{/.test(out)) return out;  // número puesto a mano
        n += 1;
        if (label) labels[label[1].trim()] = n;
        if (out.startsWith("$$")) return out.slice(0, -2) + ` \\tag{${n}}$$`;
        if (out.startsWith("\\[")) return out.slice(0, -2) + ` \\tag{${n}}\\]`;
        return out.replace(/\\end\{([a-z]+)\}$/, ` \\tag{${n}}\\end{$1}`);
      });
    }
    for (let i = 0; i < parts.length; i += 2) {
      parts[i] = parts[i].replace(/\\(eq)?ref\{([^}]+)\}/g, (m, eq, key) => {
        const num = labels[key.trim()] ?? "??";
        return eq ? `(${num})` : String(num);
      });
    }
    return parts.join("");
  }

  /** Markdown + LaTeX → HTML saneado. */
  function toHtml(markdown) {
    if (!window.marked || !setupPurify()) return plainHtml(markdown);
    const store = [];
    const protectedText = protectMath(numberEquations(markdown || ""), store);
    return sanitize(restoreMath(marked.parse(protectedText), store));
  }

  /** Resaltado + cabecera (lenguaje, Copiar, Guardar) para cada bloque de código del elemento. */
  function enhanceCodeBlocks(root) {
    root.querySelectorAll("pre > code").forEach((code) => {
      const pre = code.parentElement;
      if (pre.dataset.enhanced) return;
      const langClass = [...code.classList].find((c) => c.startsWith("language-"));
      const lang = langClass ? langClass.slice(9) : "";
      // Los diagramas los dibuja Mermaid (también los que vienen sin etiqueta de lenguaje)
      if (lang === "mermaid" || /^(graph|flowchart|mindmap|sequenceDiagram)\b/.test(code.innerText.trim())) return;
      pre.dataset.enhanced = "1";

      if (window.hljs) {
        try {
          if (lang && hljs.getLanguage(lang)) hljs.highlightElement(code);
          else hljs.highlightElement(code); // autodetección
        } catch (e) {}
      }

      const source = code.textContent;  // el texto original: lo usan Copiar, Guardar y Ejecutar
      const shownLang = lang || code.result?.language || "";
      splitLines(code);

      const wrapper = document.createElement("div");
      wrapper.className = "code-block";
      wrapper.classList.toggle("show-lines", codePrefs.lines);
      wrapper.classList.toggle("wrap", codePrefs.wrap);
      const runnable = PYTHON_LANGS.has(shownLang) && isLocalPage();
      const header = document.createElement("div");
      header.className = "code-header";
      header.innerHTML = `
        <span class="code-lang">${escapeAttr(shownLang || "código")}</span>
        <span class="code-actions">
          ${runnable ? '<button type="button" data-act="run" title="Ejecutar en tu laptop (te pide confirmación)">▶ Ejecutar</button>' : ""}
          <button type="button" data-act="lines" title="Mostrar u ocultar números de línea">#</button>
          <button type="button" data-act="wrap" title="Ajustar las líneas largas">↩</button>
          <button type="button" data-act="save" title="Guardar en el workspace">💾 Guardar</button>
          <button type="button" data-act="copy" title="Copiar al portapapeles">📋 Copiar</button>
        </span>`;
      pre.replaceWith(wrapper);
      wrapper.append(header, pre);

      header.querySelector('[data-act="copy"]').addEventListener("click", (e) => {
        copyText(source, e.currentTarget, "✓ Copiado");
      });
      for (const pref of ["lines", "wrap"]) {
        header.querySelector(`[data-act="${pref}"]`).addEventListener("click", () => {
          codePrefs[pref] = wrapper.classList.toggle(pref === "lines" ? "show-lines" : "wrap");
          saveCodePrefs();  // la próxima vez los bloques nuevos salen igual
        });
      }
      header.querySelector('[data-act="run"]')?.addEventListener("click", (e) => runPython(source, wrapper, e.currentTarget));
      header.querySelector('[data-act="save"]').addEventListener("click", async (e) => {
        const ext = { python: "py", py: "py", javascript: "js", js: "js", typescript: "ts", html: "html", css: "css",
                      json: "json", bash: "sh", shell: "sh", powershell: "ps1", sql: "sql", java: "java",
                      c: "c", cpp: "cpp", rust: "rs", go: "go", markdown: "md", latex: "tex", tex: "tex" }[lang] || "txt";
        const name = prompt("Nombre del archivo en el workspace:", `codigo_edith.${ext}`);
        if (!name) return;
        const btn = e.currentTarget;
        try {
          const res = await fetch("/api/workspace/file", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename: name, content: source }),
          });
          flash(btn, res.ok ? "✓ Guardado" : "✗ Error");
          if (res.ok && typeof loadWorkspaceFiles === "function") loadWorkspaceFiles();
        } catch (err) {
          flash(btn, "✗ Error");
        }
      });
    });

    // Doble clic sobre una fórmula: copiar su código LaTeX (para pegarlo en Obsidian, Word, etc.)
    root.querySelectorAll("[data-latex]").forEach((el) => {
      if (el.dataset.bound) return;
      el.dataset.bound = "1";
      el.addEventListener("dblclick", () => copyText(el.dataset.latex, el, null));
    });
  }

  // ---- Fase 7: números de línea, ajuste de líneas y ▶ Ejecutar (Python) ----
  const PYTHON_LANGS = new Set(["python", "py", "python3"]);
  const codePrefs = { lines: false, wrap: false };
  try { Object.assign(codePrefs, JSON.parse(localStorage.getItem("edith.code") || "{}")); } catch (e) {}
  function saveCodePrefs() {
    try { localStorage.setItem("edith.code", JSON.stringify(codePrefs)); } catch (e) {}
  }

  function isLocalPage() {  // el servidor solo ejecuta código pedido desde esta computadora
    return ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);
  }

  /** Una <span class="code-line"> por línea, sin romper el resaltado: las <span> de highlight.js que
   *  cruzan saltos de línea (cadenas o comentarios largos) se cierran y se vuelven a abrir. */
  function splitLines(code) {
    const lines = [];
    const open = [];
    let line = "";
    const re = /(<span[^>]*>)|(<\/span>)|(\n)|([^<\n]+|<)/g;
    let m;
    while ((m = re.exec(code.innerHTML))) {
      if (m[1]) { open.push(m[1]); line += m[1]; }
      else if (m[2]) { open.pop(); line += m[2]; }
      else if (m[3]) { lines.push(line + "</span>".repeat(open.length)); line = open.join(""); }
      else line += m[4];
    }
    if (line.replace(/<[^>]+>/g, "") !== "" || !lines.length) lines.push(line + "</span>".repeat(open.length));
    code.innerHTML = lines.map((l) => `<span class="code-line">${l.replace(/<[^>]+>/g, "") ? l : l + " "}</span>`).join("");
  }

  function confirmRun(source) {
    return new Promise((resolve) => {
      const backdrop = document.createElement("div");
      backdrop.className = "confirm-backdrop";
      const box = document.createElement("div");
      box.className = "confirm-modal";
      box.setAttribute("role", "dialog");
      const title = document.createElement("div");
      title.className = "confirm-title";
      title.textContent = "¿Ejecutar este código Python en tu laptop?";
      const pre = document.createElement("pre");
      pre.className = "confirm-command";
      pre.textContent = source;  // textContent: se muestra tal cual, sin interpretarlo
      const reason = document.createElement("div");
      reason.className = "confirm-reason";
      reason.textContent = "Se ejecuta con tus permisos (no es un entorno aislado), en workspace/ejecuciones y "
        + "durante 30 s como máximo. Ejecútalo solo si entiendes lo que hace.";
      const actions = document.createElement("div");
      actions.className = "confirm-actions";
      const deny = document.createElement("button");
      deny.type = "button";
      deny.className = "btn-deny";
      deny.textContent = "Cancelar";
      const allow = document.createElement("button");
      allow.type = "button";
      allow.className = "btn-allow";
      allow.textContent = "▶ Ejecutar";
      actions.append(deny, allow);
      box.append(title, pre, reason, actions);
      backdrop.append(box);
      document.body.append(backdrop);
      const done = (ok) => { backdrop.remove(); document.removeEventListener("keydown", onKey); resolve(ok); };
      const onKey = (e) => { if (e.key === "Escape") done(false); };
      document.addEventListener("keydown", onKey);
      deny.addEventListener("click", () => done(false));
      allow.addEventListener("click", () => done(true));
      deny.focus();  // un Enter por accidente cancela
    });
  }

  async function runPython(source, wrapper, btn) {
    if (!(await confirmRun(source))) return;
    let panel = wrapper.querySelector(".code-output");
    if (!panel) {
      panel = document.createElement("div");
      panel.className = "code-output";
      wrapper.append(panel);
    }
    panel.replaceChildren(Object.assign(document.createElement("div"), { className: "code-output-status", textContent: "⏳ Ejecutando…" }));
    btn.disabled = true;
    try {
      const res = await fetch("/api/code/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: source, language: "python" }),
      });
      const data = await res.json().catch(() => ({}));
      const status = panel.firstChild;
      if (!res.ok) {
        status.textContent = `✗ ${typeof data.detail === "string" ? data.detail : "No se pudo ejecutar (HTTP " + res.status + ")."}`;
        return;
      }
      status.textContent = data.timed_out ? `⌛ Se detuvo a los 30 s.`
        : data.exit_code === 0 ? `✓ Terminó en ${data.seconds} s.` : `✗ Terminó con código ${data.exit_code} (${data.seconds} s).`;
      for (const [text, cls] of [[data.stdout, "code-stdout"], [data.stderr, "code-stderr"]]) {
        if (!text) continue;
        const out = document.createElement("pre");
        out.className = cls;
        out.textContent = text;
        panel.append(out);
      }
      if (!data.stdout && !data.stderr) status.textContent += " (sin salida)";
    } catch (e) {
      panel.firstChild.textContent = "✗ No hay conexión con EDITH.";
    } finally {
      btn.disabled = false;
    }
  }

  function flash(btn, label) {
    const original = btn.dataset.label || btn.innerText;
    btn.dataset.label = original;
    btn.innerText = label;
    setTimeout(() => { btn.innerText = original; }, 1400);
  }

  async function copyText(text, el, label) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (err) {}
      ta.remove();
    }
    if (label) flash(el, label);
    else {
      el.classList.add("copied");
      setTimeout(() => el.classList.remove("copied"), 900);
    }
  }

  return { toHtml, enhanceCodeBlocks };
})();

window.EdithRender = EdithRender;
