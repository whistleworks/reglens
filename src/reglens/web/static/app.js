"use strict";
const form = document.getElementById("ask-form");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
let lastRequestId = null;

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function render(data) {
  lastRequestId = data.request_id;
  resultEl.hidden = false;
  document.getElementById("answer").textContent = data.answer;
  document.getElementById("disclaimer").textContent = data.disclaimer;
  const degraded = document.getElementById("degraded");
  degraded.hidden = data.mode !== "sources_only";
  degraded.textContent = data.mode === "sources_only"
    ? "Modalità solo fonti: il generatore di risposte non è disponibile." : "";
  const cites = document.getElementById("citations");
  cites.replaceChildren();
  document.getElementById("citations-title").hidden = data.citations.length === 0;
  for (const c of data.citations) {
    const li = el("li");
    const label = c.title ? `${c.id} · ${c.title}` : c.id;
    li.append(c.url ? el("a", label, { href: c.url, target: "_blank", rel: "noopener" }) : el("span", label));
    if (c.quote) li.append(el("blockquote", c.quote));
    cites.append(li);
  }
  const sources = document.getElementById("sources");
  sources.replaceChildren();
  document.getElementById("sources-box").hidden = data.sources.length === 0;
  document.getElementById("sources-box").open = data.mode === "sources_only";
  for (const s of data.sources) {
    const li = el("li");
    li.append(el("a", `${s.id} · ${s.title}`, { href: s.url, target: "_blank", rel: "noopener" }));
    li.append(el("p", s.snippet));
    sources.append(li);
  }
  document.getElementById("feedback-status").textContent = "";
}

async function ask(question) {
  statusEl.textContent = "Ricerca nelle fonti…";
  resultEl.hidden = true;
  const response = await fetch("/ui/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    statusEl.textContent = problem.detail || problem.title || `Errore ${response.status}`;
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
      if (event === "status") statusEl.textContent = "Ricerca nelle fonti e generazione della risposta…";
      if (event === "answer") { render(data); statusEl.textContent = ""; }
      if (event === "error") statusEl.textContent = data.detail || data.title;
    }
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const question = document.getElementById("question").value.trim();
  if (question) ask(question).catch(() => { statusEl.textContent = "Errore di rete."; });
});

for (const btn of document.querySelectorAll("#feedback button")) {
  btn.addEventListener("click", async () => {
    if (!lastRequestId) return;
    const r = await fetch("/ui/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: lastRequestId, value: btn.dataset.value }),
    });
    document.getElementById("feedback-status").textContent = r.ok ? "Grazie!" : "Errore";
  });
}
