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

  /** Markdown + LaTeX → HTML saneado. */
  function toHtml(markdown) {
    if (!window.marked || !setupPurify()) return plainHtml(markdown);
    const store = [];
    const protectedText = protectMath(markdown || "", store);
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

      const wrapper = document.createElement("div");
      wrapper.className = "code-block";
      const header = document.createElement("div");
      header.className = "code-header";
      header.innerHTML = `
        <span class="code-lang">${escapeAttr(lang || code.result?.language || "código")}</span>
        <span class="code-actions">
          <button type="button" data-act="save" title="Guardar en el workspace">💾 Guardar</button>
          <button type="button" data-act="copy" title="Copiar al portapapeles">📋 Copiar</button>
        </span>`;
      pre.replaceWith(wrapper);
      wrapper.append(header, pre);

      header.querySelector('[data-act="copy"]').addEventListener("click", (e) => {
        copyText(code.innerText, e.currentTarget, "✓ Copiado");
      });
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
            body: JSON.stringify({ filename: name, content: code.innerText }),
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
