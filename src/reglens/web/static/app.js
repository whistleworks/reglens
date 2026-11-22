"use strict";
const body = document.body;
const form = document.getElementById("ask-form");
const input = document.getElementById("question");
const askBtn = document.getElementById("ask-btn");
const statusEl = document.getElementById("status");
const threadEl = document.getElementById("thread");
const resultEl = document.getElementById("result");
let lastRequestId = null;

const ID_RE = /\b(?:AIA|GDPR):[A-Za-z0-9]+(?::[A-Za-z0-9]+)*/g;

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

const anchorOf = (id) => `cite-${id.replace(/[^A-Za-z0-9]+/g, "-")}`;

/* Inline text: **bold** and canonical ids (AIA:art:6:par:2) as links to the citation rail.
   Built with DOM nodes only, never innerHTML, so model output cannot inject markup. */
function inline(parent, text) {
  const parts = text.split(/(\*\*[^*]+\*\*|(?<![\w*])\*[^*\s][^*]*\*(?![\w*]))/g);
  for (const part of parts) {
    if (!part) continue;
    if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
      const strong = el("strong");
      inline(strong, part.slice(2, -2));
      parent.append(strong);
      continue;
    }
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*") && !part.startsWith("**")) {
      const em = el("em");
      inline(em, part.slice(1, -1));
      parent.append(em);
      continue;
    }
    let last = 0;
    for (const m of part.matchAll(ID_RE)) {
      if (m.index > last) parent.append(part.slice(last, m.index));
      const chip = el("a", m[0], { href: `#${anchorOf(m[0])}`, class: "cite-chip" });
      chip.addEventListener("click", () => light(m[0]));
      parent.append(chip);
      last = m.index + m[0].length;
    }
    if (last < part.length) parent.append(part.slice(last));
  }
}

/* Minimal Markdown: headings, bullet and numbered lists, paragraphs. */
function renderMarkdown(target, text) {
  target.replaceChildren();
  let list = null;
  let para = [];
  const flush = () => {
    if (para.length) { const p = el("p"); inline(p, para.join(" ")); target.append(p); para = []; }
  };
  for (const raw of text.replace(/\r/g, "").split("\n")) {
    const line = raw.trim();
    if (!line) { flush(); list = null; continue; }
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line);
    if (heading) { flush(); list = null; const h = el("h4"); inline(h, heading[1]); target.append(h); continue; }
    if (bullet || numbered) {
      flush();
      const kind = bullet ? "UL" : "OL";
      if (!list || list.tagName !== kind) { list = el(kind.toLowerCase()); target.append(list); }
      const li = el("li"); inline(li, (bullet || numbered)[1]); list.append(li);
      continue;
    }
    list = null;
    para.push(line);
  }
  flush();
}

function light(id) {
  for (const li of document.querySelectorAll(".citations li")) li.classList.toggle("is-lit", li.id === anchorOf(id));
}

function render(data) {
  lastRequestId = data.request_id;
  resultEl.hidden = false;
  renderMarkdown(document.getElementById("answer"), data.answer || "");
  if (data.disclaimer) document.getElementById("disclaimer").textContent = data.disclaimer;

  const degraded = document.getElementById("degraded");
  degraded.hidden = data.mode !== "sources_only";
  degraded.textContent = data.mode === "sources_only"
    ? "Il generatore di risposte non è disponibile in questo momento: qui sotto trovi gli articoli più pertinenti." : "";

  const cites = document.getElementById("citations");
  cites.replaceChildren();
  document.getElementById("citations-title").textContent =
    data.citations.length ? "Articoli citati" : "Nessun articolo citato";
  for (const c of data.citations) {
    const li = el("li", "", { id: anchorOf(c.id) });
    li.append(el("span", c.id, { class: "cite-id" }));
    const title = c.title || "Apri il testo ufficiale";
    li.append(c.url
      ? el("a", title, { href: c.url, target: "_blank", rel: "noopener", class: "cite-title" })
      : el("span", title, { class: "cite-title" }));
    if (c.quote) li.append(el("blockquote", c.quote));
    cites.append(li);
  }

  const sources = document.getElementById("sources");
  const box = document.getElementById("sources-box");
  sources.replaceChildren();
  box.hidden = data.sources.length === 0;
  box.open = data.mode === "sources_only";
  for (const s of data.sources) {
    const li = el("li");
    li.append(el("a", `${s.id}, ${s.title}`, { href: s.url, target: "_blank", rel: "noopener" }));
    li.append(el("p", s.snippet));
    sources.append(li);
  }
  document.getElementById("feedback-status").textContent = "";
}

function setBusy(busy, message = "") {
  body.classList.toggle("is-busy", busy);
  askBtn.disabled = busy;
  statusEl.textContent = message;
}

async function ask(question) {
  body.classList.remove("is-empty");
  threadEl.hidden = false;
  resultEl.hidden = true;
  document.getElementById("asked").textContent = question;
  setBusy(true, "Cerco negli articoli dell'AI Act e del GDPR");
  window.scrollTo({ top: 0, behavior: "smooth" });

  const response = await fetch("/ui/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    setBusy(false, problem.detail || problem.title || `La richiesta non è andata a buon fine (errore ${response.status}). Riprova tra poco.`);
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const event = /^event: (.*)$/m.exec(raw)?.[1];
      const data = JSON.parse(/^data: (.*)$/m.exec(raw)?.[1] || "null");
      if (event === "sources") setBusy(true, "Ho trovato gli articoli, sto scrivendo la risposta");
      if (event === "answer") { setBusy(false); render(data); }
      if (event === "error") setBusy(false, (data && (data.detail || data.title)) || "La risposta non è arrivata. Riprova.");
    }
  }
  if (body.classList.contains("is-busy")) setBusy(false, "La risposta non è arrivata. Riprova.");
}

function submit() {
  const question = input.value.trim();
  if (!question || askBtn.disabled) return;
  input.value = "";
  autosize();
  ask(question).catch(() => setBusy(false, "Connessione assente: controlla che RegLens sia acceso e riprova."));
}

function autosize() {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}

form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
});

for (const btn of document.querySelectorAll(".examples button")) {
  btn.addEventListener("click", () => { input.value = btn.textContent; submit(); });
}

for (const btn of document.querySelectorAll("#feedback button")) {
  btn.addEventListener("click", async () => {
    if (!lastRequestId) return;
    const r = await fetch("/ui/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: lastRequestId, value: btn.dataset.value }),
    });
    document.getElementById("feedback-status").textContent = r.ok ? "Grazie, l'ho registrato." : "Non sono riuscito a salvarlo.";
  });
}

input.focus();
