/* SparkForge WebUI — Editor dock (JAG-150).
   Right-side resizable dock, one tab per file. CodeMirror 6 for code, plus
   per-type previews (markdown / image / pdf / html). Vendored libs only. */
import {
  EditorState, Compartment, EditorView, keymap, lineNumbers,
  highlightActiveLine, highlightActiveLineGutter, drawSelection, dropCursor,
  rectangularSelection, crosshairCursor, highlightSpecialChars,
  defaultKeymap, history, historyKeymap, indentWithTab,
  syntaxHighlighting, defaultHighlightStyle, bracketMatching, indentOnInput,
  foldGutter, foldKeymap, searchKeymap, highlightSelectionMatches,
  autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap,
  javascript, python, json, markdown, html, css, yaml, oneDark,
} from "./vendor/codemirror.js";

const TOKEN = () => localStorage.getItem("sf_token") || "";
const LS_W = "sf_ed_w";
const LS_TABS = "sf_ed_tabs";
const IMG_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "bmp", "avif"]);
const LANG_BY_EXT = {
  js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "javascript",
  ts: "javascript", tsx: "javascript", py: "python", json: "json",
  md: "markdown", markdown: "markdown", html: "html", htm: "html",
  css: "css", scss: "css", yml: "yaml", yaml: "yaml",
};

const $id = (id) => document.getElementById(id);
function authHeaders() { const t = TOKEN(); return t ? { Authorization: "Bearer " + t } : {}; }
async function jget(url) { const r = await fetch(url, { headers: authHeaders() }); return r.json(); }
async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
    body: JSON.stringify(body),
  });
  return r.json();
}

function extOf(p) { const m = /\.([a-z0-9]+)$/i.exec(p || ""); return m ? m[1].toLowerCase() : ""; }
function viewerFor(p) {
  const e = extOf(p);
  if (IMG_EXT.has(e)) return "image";
  if (e === "pdf") return "pdf";
  if (e === "md" || e === "markdown") return "markdown";
  if (e === "html" || e === "htm") return "html";
  return "code";
}
function langOf(p) { return LANG_BY_EXT[extOf(p)] || null; }
function langExt(name) {
  switch (name) {
    case "javascript": return javascript();
    case "python": return python();
    case "json": return json();
    case "markdown": return markdown();
    case "html": return html();
    case "css": return css();
    case "yaml": return yaml();
    default: return null;
  }
}
function basename(p) { const i = String(p).lastIndexOf("/"); return i >= 0 ? p.slice(i + 1) : String(p); }
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

class EditorHost {
  constructor(parent) { this.parent = parent; this.view = null; this.lang = new Compartment(); this.ro = new Compartment(); }
  mount(doc, langName, readOnly, onUpdate) {
    this.destroy();
    const exts = [
      lineNumbers(), highlightActiveLineGutter(), highlightSpecialChars(), history(),
      drawSelection(), dropCursor(), EditorState.allowMultipleSelections.of(true),
      indentOnInput(), syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      bracketMatching(), closeBrackets(), autocompletion(),
      rectangularSelection(), crosshairCursor(), highlightActiveLine(), highlightSelectionMatches(),
      foldGutter(),
      keymap.of([{ key: "Mod-s", run: () => { save(); return true; } },
        ...closeBracketsKeymap, ...defaultKeymap, ...searchKeymap, ...historyKeymap,
        ...foldKeymap, ...completionKeymap, indentWithTab]),
      oneDark,
      this.lang.of(langExt(langName) || []),
      this.ro.of(EditorState.readOnly.of(!!readOnly)),
    ];
    if (onUpdate) exts.push(EditorView.updateListener.of(onUpdate));
    this.view = new EditorView({ parent: this.parent, state: EditorState.create({ doc: doc || "", extensions: exts }) });
  }
  value() { return this.view ? this.view.state.doc.toString() : ""; }
  setValue(v) { if (this.view) this.view.dispatch({ changes: { from: 0, to: this.view.state.doc.length, insert: v || "" } }); }
  setLanguage(n) { if (this.view) this.view.dispatch({ effects: this.lang.reconfigure(langExt(n) || []) }); }
  setReadOnly(ro) { if (this.view) this.view.dispatch({ effects: this.ro.reconfigure(EditorState.readOnly.of(!!ro)) }); }
  focus() { if (this.view) this.view.focus(); }
  destroy() { if (this.view) { this.view.destroy(); this.view = null; } }
}

const state = { tabs: [], active: -1, host: null, preview: null, tabsEl: null, statusEl: null, toggleBtn: null, resizeEl: null, dock: null };

const STYLE = `
#editorDock{position:relative;flex:0 0 auto;min-height:0;background:var(--bg2,#0f1320);
  border-left:1px solid var(--line,#26304a);display:flex;flex-direction:column;z-index:5;font-size:12px}
#editorDock[hidden]{display:none}
#editorDock .ed-resize{position:absolute;left:-3px;top:0;bottom:0;width:6px;cursor:col-resize;z-index:6}
#editorDock .ed-head{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid var(--line,#26304a)}
#editorDock .ed-title{font-weight:600}
#editorDock .ed-status{flex:1;opacity:.7;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#editorDock .ed-tabs{display:flex;gap:4px;overflow-x:auto;padding:6px 8px;border-bottom:1px solid var(--line,#26304a)}
#editorDock .ed-tab{display:flex;gap:6px;align-items:center;padding:3px 8px;border:1px solid var(--line,#26304a);border-radius:6px;cursor:pointer;white-space:nowrap;font-family:monospace;font-size:11px}
#editorDock .ed-tab.active{border-color:var(--accent,#8b7bf0);background:rgba(139,123,240,.14)}
#editorDock .ed-tab .dirty{color:var(--warn,#e0b341)}
#editorDock .ed-tab .x{opacity:.55}
#editorDock .ed-body{flex:1;min-height:0;display:flex;flex-direction:row}
#editorDock .ed-tree{width:210px;flex:0 0 auto;overflow:auto;border-right:1px solid var(--line,#26304a);padding:6px;font-family:monospace;font-size:11px}
#editorDock .ed-tree[hidden]{display:none}
#editorDock .ed-main{flex:1;min-width:0;display:flex;flex-direction:column}
#editorDock .ed-trow{cursor:pointer;padding:2px 4px;border-radius:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#editorDock .ed-trow:hover{background:rgba(108,140,255,.12)}
#editorDock .ed-trow.active{background:rgba(139,123,240,.18)}
#editorDock .ed-host{flex:1;min-height:0;overflow:auto}
#editorDock .ed-host.hidden{display:none}
#editorDock .ed-preview{flex:1;min-height:0;overflow:auto;padding:12px;line-height:1.5}
#editorDock .ed-preview[hidden]{display:none}
#editorDock .ed-preview img{max-width:100%}
#editorDock .ed-preview iframe{width:100%;height:100%;border:0;background:#fff}
#editorDock .ed-preview .md h1,#editorDock .ed-preview .md h2{border-bottom:1px solid var(--line,#26304a);padding-bottom:4px}
#editorDock .ed-preview .md h1{color:#9db4ff}#editorDock .ed-preview .md h2{color:#a9e0c0}
#editorDock .ed-preview .md h3{color:#e0b341}
#editorDock .ed-preview .md code{background:rgba(255,255,255,.07);padding:1px 4px;border-radius:4px}
#editorDock .ed-preview .md pre{background:rgba(255,255,255,.05);padding:8px;border-radius:6px;overflow:auto}
#editorDock .ed-preview .md a{color:#7fb0ff}
#editorDock .ed-foot{display:flex;gap:6px;padding:8px 10px;border-top:1px solid var(--line,#26304a)}
#editorDock.ed-overlay{position:fixed;top:44px;right:0;bottom:0;height:auto;width:min(520px,92vw);z-index:40;box-shadow:-16px 0 40px rgba(0,0,0,.45)}
.ed-tab-note{color:var(--warn,#e0b341)}
`;

function buildDock() {
  if ($id("editorDock")) return;
  const style = document.createElement("style");
  style.textContent = STYLE;
  document.head.appendChild(style);

  const dock = document.createElement("aside");
  dock.id = "editorDock";
  dock.hidden = true;
  dock.innerHTML = `
    <div class="ed-resize"></div>
    <div class="ed-head"><span class="ed-title">Editor</span><span class="ed-status"></span>
      <button class="ed-files ghost" title="mostra/nascondi l'albero file">🗂 files</button>
      <button class="ed-refresh ghost" title="ricarica l'albero">↻</button>
      <button class="ed-x ghost" title="close (Esc)">✕</button></div>
    <div class="ed-body">
      <div class="ed-tree"></div>
      <div class="ed-main">
        <div class="ed-tabs"></div>
        <div class="ed-host"></div>
        <div class="ed-preview" hidden></div>
      </div>
    </div>
    <div class="ed-foot">
      <button class="ghost ed-save">save</button>
      <button class="ghost ed-revert">revert</button>
      <button class="ghost ed-toggle" hidden>render</button>
    </div>`;
  const anchor = $id("resize-right") || $id("rail");
  if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(dock, anchor);
  else document.body.appendChild(dock);
  state.dock = dock;
  state.tabsEl = dock.querySelector(".ed-tabs");
  state.statusEl = dock.querySelector(".ed-status");
  state.host = new EditorHost(dock.querySelector(".ed-host"));
  state.preview = dock.querySelector(".ed-preview");
  state.toggleBtn = dock.querySelector(".ed-toggle");
  state.resizeEl = dock.querySelector(".ed-resize");
  dock.querySelector(".ed-x").onclick = close;
  dock.querySelector(".ed-save").onclick = save;
  dock.querySelector(".ed-revert").onclick = revert;
  state.toggleBtn.onclick = toggleRender;
  state.treeEl = dock.querySelector(".ed-tree");
  state.treeEl.hidden = localStorage.getItem("sf_ed_tree") === "0";
  dock.querySelector(".ed-files").onclick = () => {
    const t = state.treeEl;
    t.hidden = !t.hidden;
    localStorage.setItem("sf_ed_tree", t.hidden ? "0" : "1");
    if (!t.hidden && !t.childElementCount) loadTree();
  };
  dock.querySelector(".ed-refresh").onclick = () => loadTree();

  const saved = parseInt(localStorage.getItem(LS_W) || "", 10);
  if (saved) dock.style.width = saved + "px";
  let dragging = false;
  state.resizeEl.addEventListener("mousedown", (e) => { dragging = true; e.preventDefault(); });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const right = dock.getBoundingClientRect().right;
    const w = Math.min(window.innerWidth - 120, Math.max(320, right - e.clientX));
    dock.style.width = w + "px";
    localStorage.setItem(LS_W, String(w));
  });
  window.addEventListener("mouseup", () => { dragging = false; });
  window.addEventListener("resize", applyResponsive);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || dock.hidden) return;
    const modal = document.querySelector("#diffView:not([hidden]), #skillView:not([hidden])");
    if (!modal) close();
  });
}

function applyResponsive() {
  if (!state.dock) return;
  const overlay = window.innerWidth < 1024;
  state.dock.classList.toggle("ed-overlay", overlay);
  state.dock.style.width = overlay ? "" : (parseInt(localStorage.getItem(LS_W) || "420", 10) + "px");
}

function activeTab() { return state.tabs[state.active] || null; }
function setStatus(m) { if (state.statusEl) state.statusEl.textContent = m || ""; }
function isCodeMode(t) { return t && (t.viewer === "code" || (t.viewer === "markdown" && t.mode === "code")); }

function syncActive() {
  const t = activeTab();
  if (t && isCodeMode(t) && state.host.view) {
    t.value = state.host.value();
    t.dirty = t.value !== t.saved;
  }
}

async function loadTree() {
  const box = state.treeEl;
  if (!box) return;
  box.innerHTML = '<div class="remaining">loading…</div>';
  const sid = localStorage.getItem("sf_session") || "";
  try {
    const d = await jget("/api/fs/list?session=" + encodeURIComponent(sid));
    if (d.error) { box.innerHTML = '<div class="remaining">' + esc(d.error) + "</div>"; return; }
    box.innerHTML = "";
    const root = document.createElement("div");
    root.className = "remaining";
    root.style.marginBottom = "4px";
    root.textContent = (d.root ? basename(d.root) : "workspace") + "/";
    box.appendChild(root);
    renderTree(box, d, 0);
    if (!d.count) box.insertAdjacentHTML("beforeend", '<div class="remaining">empty folder</div>');
  } catch (e) { box.innerHTML = '<div class="remaining">' + esc(e) + "</div>"; }
}

function renderTree(container, d, depth) {
  (d.dirs || []).forEach((dir) => {
    const row = document.createElement("div");
    row.className = "ed-trow";
    row.style.paddingLeft = (4 + depth * 12) + "px";
    row.textContent = "▸ 📁 " + dir.name;
    const kids = document.createElement("div");
    kids.hidden = true;
    let loaded = false;
    row.onclick = async () => {
      kids.hidden = !kids.hidden;
      row.textContent = (kids.hidden ? "▸" : "▾") + " 📁 " + dir.name;
      if (!kids.hidden && !loaded) {
        loaded = true;
        const sid = localStorage.getItem("sf_session") || "";
        try {
          const sub = await jget("/api/fs/list?session=" + encodeURIComponent(sid) + "&path=" + encodeURIComponent(dir.path));
          if (sub.error) kids.innerHTML = '<div class="remaining" style="padding-left:' + (16 + depth * 12) + 'px">' + esc(sub.error) + "</div>";
          else renderTree(kids, sub, depth + 1);
        } catch (e) { /* ignore */ }
      }
    };
    container.appendChild(row);
    container.appendChild(kids);
  });
  (d.files || []).forEach((f) => {
    const row = document.createElement("div");
    row.className = "ed-trow";
    row.style.paddingLeft = (16 + depth * 12) + "px";
    row.textContent = "📄 " + f.name;
    row.title = f.path;
    row.onclick = () => open(f.path);
    container.appendChild(row);
  });
}

function renderTabs() {
  const el = state.tabsEl; if (!el) return;
  el.innerHTML = "";
  state.tabs.forEach((t, i) => {
    const b = document.createElement("div");
    b.className = "ed-tab" + (i === state.active ? " active" : "");
    const nm = document.createElement("span"); nm.className = "nm"; nm.textContent = basename(t.path);
    b.appendChild(nm);
    if (t.dirty) { const d = document.createElement("span"); d.className = "dirty"; d.textContent = "●"; b.appendChild(d); }
    const x = document.createElement("span"); x.className = "x"; x.textContent = "✕";
    x.onclick = (e) => { e.stopPropagation(); closeTab(i); };
    b.appendChild(x);
    b.onclick = () => activate(i);
    el.appendChild(b);
  });
}

function persistTabs() {
  try { localStorage.setItem(LS_TABS, JSON.stringify({ paths: state.tabs.map((t) => t.path), active: state.active })); } catch (e) { /* ignore */ }
}

function showCode(show) {
  state.dock.querySelector(".ed-host").classList.toggle("hidden", !show);
  state.preview.hidden = show;
}

function renderActive() {
  const t = activeTab();
  if (!t) return;
  const code = isCodeMode(t);
  showCode(code);
  if (code) {
    state.host.mount(t.value, t.lang, t.readonly, onDocUpdate);
    state.host.setReadOnly(t.readonly);
    state.host.focus();
  } else if (t.viewer === "markdown") {
    const raw = t.value || "";
    const htm = window.marked ? window.marked.parse(raw) : esc(raw);
    const clean = window.DOMPurify ? window.DOMPurify.sanitize(htm) : esc(raw);
    state.preview.innerHTML = '<div class="md">' + clean + "</div>";
  } else if (t.viewer === "html") {
    state.preview.innerHTML = "";
    const ifr = document.createElement("iframe");
    ifr.setAttribute("sandbox", "");
    ifr.srcdoc = t.value || "";
    state.preview.appendChild(ifr);
  } else if (t.viewer === "image" || t.viewer === "pdf") {
    state.preview.innerHTML = "";
    const url = "/api/fs/raw?path=" + encodeURIComponent(t.path) + (TOKEN() ? "&token=" + encodeURIComponent(TOKEN()) : "");
    const node = document.createElement(t.viewer === "pdf" ? "iframe" : "img");
    node.src = url;
    if (t.viewer === "pdf") node.setAttribute("style", "width:100%;height:100%;border:0");
    state.preview.appendChild(node);
  } else {
    state.preview.innerHTML = '<div class="remaining">file binario — nessuna anteprima (' + esc(t.size ? t.size + " B" : "") + ")</div>";
  }

  const d = state.dock;
  d.querySelector(".ed-save").disabled = !!t.readonly;
  d.querySelector(".ed-revert").disabled = !!t.readonly;
  state.toggleBtn.hidden = t.viewer !== "markdown";
  state.toggleBtn.textContent = t.mode === "code" ? "render" : "code";
  updateStatus();
}

function updateStatus() {
  const t = activeTab();
  if (!t) { setStatus(""); return; }
  const bits = [t.path];
  if (t.readonly) bits.push("read-only");
  if (t.dirty) bits.push("● modified");
  setStatus(bits.join(" · "));
}

function onDocUpdate(u) {
  if (!u.docChanged) return;
  const t = activeTab();
  if (!t) return;
  t.value = state.host.value();
  const wasDirty = t.dirty;
  t.dirty = t.value !== t.saved;
  if (wasDirty !== t.dirty) renderTabs();
  updateStatus();
}

async function open(path) {
  if (!path) return;
  buildDock();
  const existing = state.tabs.findIndex((t) => t.path === path);
  if (existing >= 0) { activate(existing); show(); return; }
  let d;
  try { d = await jget("/api/fs/read?path=" + encodeURIComponent(path)); }
  catch (e) { show(); setStatus("errore: " + e); return; }
  if (!d || d.error) { show(); setStatus(d && d.error ? d.error : "read error"); return; }
  const viewer = (d.binary && viewerFor(d.path) === "code") ? "binary" : viewerFor(d.path);
  const tab = {
    path: d.path, viewer,
    lang: langOf(d.path),
    mode: "render",
    saved: d.text || "", value: d.text || "",
    dirty: false,
    readonly: !!d.truncated || viewer === "binary",
    size: d.size,
  };
  state.tabs.push(tab);
  state.active = state.tabs.length - 1;
  renderTabs();
  renderActive();
  persistTabs();
  show();
}

function activate(i) {
  if (i === state.active) return;
  syncActive();
  state.active = i;
  renderTabs();
  renderActive();
  persistTabs();
  show();
}

function closeTab(i) {
  const t = state.tabs[i];
  if (!t) return;
  if (t.dirty && !window.confirm('Chiudere "' + basename(t.path) + '" con modifiche non salvate?')) return;
  if (i === state.active) syncActive();
  state.tabs.splice(i, 1);
  if (state.tabs.length === 0) { state.active = -1; close(); return; }
  state.active = Math.min(i, state.tabs.length - 1);
  renderTabs();
  renderActive();
  persistTabs();
}

async function save() {
  const t = activeTab(); if (!t) { setStatus("nessun file aperto"); return; }
  if (t.readonly) { setStatus("file read-only"); return; }
  syncActive();
  try {
    const r = await jpost("/api/fs/write", { path: t.path, content: t.value });
    if (r.error) { setStatus("errore: " + r.error); return; }
    t.saved = t.value; t.dirty = false;
    renderTabs(); updateStatus();
    setStatus("salvato · " + r.bytes + " byte");
  } catch (e) { setStatus("errore: " + e); }
}

function revert() {
  const t = activeTab(); if (!t) return;
  t.value = t.saved;
  t.dirty = false;
  renderTabs();
  renderActive();
  setStatus("ripristinato");
}

function toggleRender() {
  const t = activeTab(); if (!t || t.viewer !== "markdown") return;
  syncActive();
  t.mode = t.mode === "code" ? "render" : "code";
  renderActive();
}

function show() {
  buildDock();
  state.dock.hidden = false;
  applyResponsive();
  if (state.treeEl && !state.treeEl.hidden && !state.treeEl.childElementCount) loadTree();
}
function close() { syncActive(); if (state.dock) state.dock.hidden = true; }
function toggle(e) {
  if (!$id("editorDock")) buildDock();
  if (state.dock.hidden) { if (!state.tabs.length) restoreTabs(); else show(); } else close();
}

async function restoreTabs() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(LS_TABS) || "null"); } catch (e) { saved = null; }
  if (!saved || !Array.isArray(saved.paths) || !saved.paths.length) { show(); return; }
  for (const p of saved.paths.slice(0, 12)) {
    try {
      await open(p);
    } catch (e) { /* skip */ }
  }
  if (typeof saved.active === "number" && saved.active >= 0 && saved.active < state.tabs.length) {
    state.active = saved.active; renderTabs(); renderActive();
  }
  show();
}

function init() {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", buildDock);
  else buildDock();
}

async function refresh(path) {
  const i = state.tabs.findIndex((t) => t.path === path);
  if (i < 0) { open(path); return; }
  try {
    const d = await jget("/api/fs/read?path=" + encodeURIComponent(path));
    if (d && !d.error) {
      state.tabs[i].saved = d.text || "";
      state.tabs[i].value = d.text || "";
      state.tabs[i].dirty = false;
      renderTabs();
      if (state.active === i) renderActive();
    }
  } catch (e) { /* ignore */ }
}
function closePath(path) { const i = state.tabs.findIndex((t) => t.path === path); if (i >= 0) closeTab(i); }
function has(path) { return state.tabs.some((t) => t.path === path); }

window.SparkEditor = {
  open: (p) => { open(p); },
  save,
  refresh,
  closePath,
  has,
  close,
  toggle,
  isOpen: () => !!$id("editorDock") && !$id("editorDock").hidden,
  restore: restoreTabs,
};

init();

export { open, close, toggle };
