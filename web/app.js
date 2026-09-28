const setupEl = document.getElementById("setup");
const setupForm = document.getElementById("setup-form");
const setupError = document.getElementById("setup-error");
const appEl = document.getElementById("app");
const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
const hudTime = document.getElementById("hud-time");
const hudCash = document.getElementById("hud-cash");
const selectedEl = document.getElementById("selected");
const inventoryEl = document.getElementById("inventory");
const marketEl = document.getElementById("market");
const proposalsEl = document.getElementById("proposals");
const aiLog = document.getElementById("ai-log");
const aiMode = document.getElementById("ai-mode");
const btnPause = document.getElementById("btn-pause");
const btnPass = document.getElementById("btn-pass");
const btnPlotBuy = document.getElementById("btn-plot-buy");
const btnPlotSell = document.getElementById("btn-plot-sell");
const btnBuild = document.getElementById("btn-build");
const btnProduce = document.getElementById("btn-produce");
const btnRoad = document.getElementById("btn-road");
const btnMerge = document.getElementById("btn-merge");
const roadSide = document.getElementById("road-side");
const btnMktBuyIron = document.getElementById("btn-mkt-buy-iron");
const btnMktSellSteel = document.getElementById("btn-mkt-sell-steel");
const btnAccept = document.getElementById("btn-accept");
const btnReject = document.getElementById("btn-reject");
const proposalIdInput = document.getElementById("proposal-id");
const mailTo = document.getElementById("mail-to");
const mailBody = document.getElementById("mail-body");
const mailLog = document.getElementById("mail-log");
const btnMailSend = document.getElementById("btn-mail-send");
const llmDebugPanel = document.getElementById("llm-debug-panel");
const llmDebugSummary = document.getElementById("llm-debug-summary");
const llmDebugSelect = document.getElementById("llm-debug-select");
const llmDebugTrace = document.getElementById("llm-debug-trace");
const btnLlmDebugRefresh = document.getElementById("btn-llm-debug-refresh");
const btnLlmDebugView = document.getElementById("btn-llm-debug-view");

let state = null;
let selected = null;
let lastOwnedClick = null;
let cellSize = 20;
let started = false;

function showGame() {
  started = true;
  setupEl.hidden = true;
  appEl.hidden = false;
  resize();
}

function showSetup(defaults) {
  started = false;
  setupEl.hidden = false;
  appEl.hidden = true;
  if (defaults) {
    if (defaults.ai_companies != null) document.getElementById("setup-companies").value = defaults.ai_companies;
    if (defaults.cities != null) document.getElementById("setup-cities").value = defaults.cities;
    if (defaults.map_size != null) document.getElementById("setup-map").value = defaults.map_size;
    if (defaults.llm_debug != null) document.getElementById("setup-llm-debug").checked = !!defaults.llm_debug;
  }
}

function resize() {
  if (appEl.hidden) return;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = Math.floor(rect.width);
  canvas.height = Math.floor(rect.height);
  draw();
}
window.addEventListener("resize", resize);

function tileAt(x, y) {
  if (!state) return null;
  return state.map.tiles.find((t) => t.x === x && t.y === y) || null;
}

function isPlayerOwned(plot) {
  return plot && plot.owner_kind === "company" && plot.owner_id === state.player_company_id;
}

function drawEdgeRoad(px, py, side, size) {
  const t = Math.max(2, Math.floor(size * 0.12));
  ctx.fillStyle = "#8a949e";
  if (side === "N") ctx.fillRect(px + 1, py + 1, size - 2, t);
  if (side === "S") ctx.fillRect(px + 1, py + size - 1 - t, size - 2, t);
  if (side === "W") ctx.fillRect(px + 1, py + 1, t, size - 2);
  if (side === "E") ctx.fillRect(px + size - 1 - t, py + 1, t, size - 2);
}

function drawCombineMark(px, py, side, size) {
  ctx.strokeStyle = "rgba(125, 209, 255, 0.85)";
  ctx.lineWidth = 2;
  const m = Math.floor(size * 0.28);
  ctx.beginPath();
  if (side === "N") {
    ctx.moveTo(px + m, py + 2);
    ctx.lineTo(px + size - m, py + 2);
  } else if (side === "S") {
    ctx.moveTo(px + m, py + size - 2);
    ctx.lineTo(px + size - m, py + size - 2);
  } else if (side === "W") {
    ctx.moveTo(px + 2, py + m);
    ctx.lineTo(px + 2, py + size - m);
  } else if (side === "E") {
    ctx.moveTo(px + size - 2, py + m);
    ctx.lineTo(px + size - 2, py + size - m);
  }
  ctx.stroke();
  ctx.lineWidth = 1;
}

function draw() {
  if (!state || !state.map) return;
  const { width, height } = state.map;
  cellSize = Math.floor(Math.min(canvas.width / width, canvas.height / height));
  const ox = Math.floor((canvas.width - width * cellSize) / 2);
  const oy = Math.floor((canvas.height - height * cellSize) / 2);

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#0e1317";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.strokeStyle = "rgba(255,255,255,0.03)";
  ctx.beginPath();
  for (let x = 0; x <= width; x++) {
    ctx.moveTo(ox + x * cellSize, oy);
    ctx.lineTo(ox + x * cellSize, oy + height * cellSize);
  }
  for (let y = 0; y <= height; y++) {
    ctx.moveTo(ox, oy + y * cellSize);
    ctx.lineTo(ox + width * cellSize, oy + y * cellSize);
  }
  ctx.stroke();

  for (const t of state.map.tiles) {
    const px = ox + t.x * cellSize;
    const py = oy + t.y * cellSize;
    if (!t.plot) continue;

    if (t.plot.building) ctx.fillStyle = "#c47a4a";
    else if (isPlayerOwned(t.plot)) ctx.fillStyle = "#2f8f6b";
    else if (t.plot.owner_kind === "city") ctx.fillStyle = "#7a6a3a";
    else if (t.plot.owner_kind === "company") ctx.fillStyle = "#6b3f5a";
    else if (t.plot.plot_type === "specialized") ctx.fillStyle = "#4a6b3f";
    else ctx.fillStyle = "#3f6b4f";
    ctx.fillRect(px + 1, py + 1, cellSize - 2, cellSize - 2);

    if (t.city_id) {
      const idx = state.map.cities.findIndex((c) => c.id === t.city_id);
      const hues = [210, 140, 30, 300, 0];
      const h = hues[(idx >= 0 ? idx : 0) % hues.length];
      ctx.fillStyle = `hsla(${h}, 40%, 50%, 0.08)`;
      ctx.fillRect(px + 1, py + 1, cellSize - 2, cellSize - 2);
    }

    if (t.plot.plot_type === "specialized" && !t.plot.building) {
      ctx.fillStyle = "rgba(255,220,120,0.35)";
      ctx.fillRect(px + 2, py + 2, 3, 3);
    }

    if (t.plot.roads) {
      for (const side of ["N", "E", "S", "W"]) {
        if (t.plot.roads[side]) drawEdgeRoad(px, py, side, cellSize);
      }
    }
    if (t.plot.combined) {
      for (const side of Object.keys(t.plot.combined)) {
        drawCombineMark(px, py, side, cellSize);
      }
    }
    if (t.plot.group_size > 1) {
      ctx.strokeStyle = "rgba(125, 209, 255, 0.35)";
      ctx.strokeRect(px + 3, py + 3, cellSize - 6, cellSize - 6);
    }
    if (t.plot.reserved_proposal_id) {
      ctx.fillStyle = "rgba(240, 180, 60, 0.35)";
      ctx.fillRect(px + 1, py + 1, cellSize - 2, cellSize - 2);
    }
    if (t.plot.building) {
      ctx.fillStyle = "#1a1008";
      ctx.font = `${Math.max(9, cellSize * 0.4)}px sans-serif`;
      ctx.fillText(t.plot.owner_kind === "city" ? "M" : "B", px + 3, py + cellSize - 3);
    }
  }

  if (selected) {
    const px = ox + selected.x * cellSize;
    const py = oy + selected.y * cellSize;
    ctx.strokeStyle = "#3d9bfd";
    ctx.lineWidth = 2;
    ctx.strokeRect(px + 1, py + 1, cellSize - 2, cellSize - 2);
    ctx.lineWidth = 1;
  }

  ctx.fillStyle = "#e7eef2";
  ctx.font = "12px sans-serif";
  for (const c of state.map.cities) {
    const px = ox + c.center_x * cellSize + 4;
    const py = oy + c.center_y * cellSize - 4;
    ctx.fillText(`${c.name}`, px, py);
  }
}

function refreshPanels() {
  if (!state) return;
  const acted = state.companies?.find((c) => c.id === state.player_company_id)?.acted_this_day;
  hudTime.textContent =
    `day ${state.day}` +
    (state.paused ? " PAUSED" : "") +
    (acted ? " (you acted)" : "") +
    (state.current_turn ? ` | AI:${state.current_turn}` : "");
  const player = state.companies.find((c) => c.id === state.player_company_id);
  hudCash.textContent = player ? `cash=${player.cash}` : "cash=—";
  inventoryEl.textContent = player ? JSON.stringify(player.inventory, null, 2) : "—";
  if (state.market) {
    const sells = (state.market.sell_listings || []).slice(0, 8);
    marketEl.textContent = sells.length
      ? sells.map((L) => `#${L.id} ${L.quantity}x ${L.item_id} @${L.price}`).join("\n")
      : "(no sell listings)";
  }
  if (state.proposals) {
    const props = state.proposals.proposals || [];
    proposalsEl.textContent = props.length
      ? props
          .map((p) => {
            if (p.proposal_type?.startsWith("plot_")) {
              return `#${p.id} ${p.proposal_type} (${p.plot_x},${p.plot_y}) @${p.price} ${p.from}→${p.to}`;
            }
            return `#${p.id} ${p.proposal_type || p.side} ${p.quantity}x ${p.item_id} @${p.price} ${p.from}→${p.to}`;
          })
          .join("\n")
      : "(none)";
  }
  refreshMailContacts();
  refreshMailLog();
  refreshLlmDebugPanel();
  btnPause.textContent = state.paused ? "Resume" : "Pause";

  if (!selected) {
    selectedEl.textContent = "Click a plot";
    btnPlotBuy.disabled = true;
    btnPlotSell.disabled = true;
    btnBuild.disabled = true;
    btnProduce.disabled = true;
    btnRoad.disabled = true;
    btnMerge.disabled = true;
    return;
  }
  const t = tileAt(selected.x, selected.y);
  selectedEl.textContent = JSON.stringify({ x: selected.x, y: selected.y, tile: t }, null, 2);
  const canBuy =
    t && t.plot && t.plot.owner_id && !isPlayerOwned(t.plot) && !t.plot.reserved_proposal_id;
  const canSell = t && isPlayerOwned(t.plot) && !t.plot.reserved_proposal_id;
  const canBuild = t && isPlayerOwned(t.plot) && !t.plot.building && !t.plot.reserved_proposal_id;
  const canProduce = t && isPlayerOwned(t.plot) && t.plot.building;
  const canRoad = t && isPlayerOwned(t.plot);
  let canMerge = false;
  if (lastOwnedClick && t && isPlayerOwned(t.plot) && !(lastOwnedClick.x === selected.x && lastOwnedClick.y === selected.y)) {
    const dist = Math.abs(lastOwnedClick.x - selected.x) + Math.abs(lastOwnedClick.y - selected.y);
    canMerge = dist === 1;
  }
  btnPlotBuy.disabled = !canBuy;
  btnPlotSell.disabled = !canSell;
  btnBuild.disabled = !canBuild;
  btnProduce.disabled = !canProduce;
  btnRoad.disabled = !canRoad;
  btnMerge.disabled = !canMerge;
}

function applyPayload(payload) {
  if (payload.type === "setup" || payload.started === false) {
    if (!started) showSetup(payload.defaults || payload);
    return;
  }
  if (payload.state) {
    state = payload.state;
    if (!started) showGame();
  }
  if (payload.ai) aiLog.textContent = payload.ai;
  if (payload.ai_mode) aiMode.textContent = `mode: ${payload.ai_mode}`;
  if (started) {
    refreshPanels();
    draw();
  }
}

setupForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  setupError.hidden = true;
  const body = {
    ai_companies: Number(document.getElementById("setup-companies").value),
    cities: Number(document.getElementById("setup-cities").value),
    map_size: Number(document.getElementById("setup-map").value),
    llm_debug: document.getElementById("setup-llm-debug").checked,
  };
  const res = await fetch("/api/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!data.ok) {
    setupError.textContent = data.message || "Setup failed";
    setupError.hidden = false;
    return;
  }
  state = data.state;
  showGame();
  refreshPanels();
  draw();
});

canvas.addEventListener("click", (ev) => {
  if (!state) return;
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const mx = (ev.clientX - rect.left) * scaleX;
  const my = (ev.clientY - rect.top) * scaleY;
  const { width, height } = state.map;
  const ox = Math.floor((canvas.width - width * cellSize) / 2);
  const oy = Math.floor((canvas.height - height * cellSize) / 2);
  const x = Math.floor((mx - ox) / cellSize);
  const y = Math.floor((my - oy) / cellSize);
  if (x < 0 || y < 0 || x >= width || y >= height) return;
  const prev = selected;
  selected = { x, y };
  const t = tileAt(x, y);
  if (t && isPlayerOwned(t.plot)) {
    if (prev && (prev.x !== x || prev.y !== y)) lastOwnedClick = prev;
    else if (!lastOwnedClick) lastOwnedClick = { x, y };
  }
  refreshPanels();
  draw();
});

btnPause.addEventListener("click", async () => {
  const paused = !(state && state.paused);
  await fetch("/api/pause", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paused }),
  });
});

btnPlotBuy.addEventListener("click", async () => {
  if (!selected) return;
  const t = tileAt(selected.x, selected.y);
  if (!t?.plot?.owner_id) return;
  const price = Number(prompt("Offer price for this plot?", String(t.plot.value || 100)));
  if (!Number.isFinite(price) || price < 0) return;
  const to = `${t.plot.owner_kind}:${t.plot.owner_id}`;
  const res = await fetch("/api/player/propose_plot_buy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, x: selected.x, y: selected.y, price }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnPlotSell.addEventListener("click", async () => {
  if (!selected) return;
  const to = prompt("Sell to (e.g. city:city_a or ai_1)", "city:city_a");
  if (!to) return;
  const price = Number(prompt("Ask price?", "150"));
  if (!Number.isFinite(price) || price < 0) return;
  const res = await fetch("/api/player/propose_plot_sell", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, x: selected.x, y: selected.y, price }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnBuild.addEventListener("click", async () => {
  if (!selected) return;
  const res = await fetch("/api/player/build", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...selected, building_id: "foundry" }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnRoad.addEventListener("click", async () => {
  if (!selected) return;
  const res = await fetch("/api/player/build_road", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...selected, side: roadSide.value }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnMerge.addEventListener("click", async () => {
  if (!selected || !lastOwnedClick) return;
  const res = await fetch("/api/player/merge_plots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      x1: lastOwnedClick.x,
      y1: lastOwnedClick.y,
      x2: selected.x,
      y2: selected.y,
    }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
  else lastOwnedClick = selected;
});

btnProduce.addEventListener("click", async () => {
  if (!selected) return;
  const res = await fetch("/api/player/produce", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(selected),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnPass.addEventListener("click", async () => {
  const res = await fetch("/api/player/pass", { method: "POST" });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnAccept.addEventListener("click", async () => {
  const proposal_id = Number(proposalIdInput.value);
  if (!proposal_id) return;
  const res = await fetch("/api/player/accept_proposal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposal_id }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnReject.addEventListener("click", async () => {
  const proposal_id = Number(proposalIdInput.value);
  if (!proposal_id) return;
  const res = await fetch("/api/player/reject_proposal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposal_id }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnMktBuyIron.addEventListener("click", async () => {
  const res = await fetch("/api/player/market/buy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_id: "iron", quantity: 1 }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnMktSellSteel.addEventListener("click", async () => {
  const res = await fetch("/api/player/market/sell", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_id: "steel", quantity: 1, price: 40 }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

function refreshMailContacts() {
  if (!state || !state.mailboxes) return;
  const pid = `company:${state.player_company_id}`;
  const boxes = state.mailboxes.mailboxes || [];
  const prev = mailTo.value;
  const options = [];
  for (const box of boxes) {
    const other = (box.participants || []).find((p) => p !== pid);
    if (!other) continue;
    options.push({ key: other, count: box.message_count || 0 });
  }
  options.sort((a, b) => a.key.localeCompare(b.key));
  mailTo.innerHTML = options
    .map((o) => `<option value="${o.key}">${o.key} (${o.count})</option>`)
    .join("");
  if (prev && options.some((o) => o.key === prev)) mailTo.value = prev;
}

function refreshMailLog() {
  if (!state || !state.mailboxes) {
    mailLog.textContent = "—";
    return;
  }
  const pid = `company:${state.player_company_id}`;
  const withKey = mailTo.value;
  const box = (state.mailboxes.mailboxes || []).find(
    (b) => (b.participants || []).includes(pid) && (b.participants || []).includes(withKey)
  );
  if (!box || !box.messages || !box.messages.length) {
    mailLog.textContent = "(empty)";
    return;
  }
  mailLog.textContent = box.messages
    .slice(-12)
    .map((m) => `[d${m.day}] ${m.from} → ${m.to}: ${m.body}`)
    .join("\n");
}

mailTo.addEventListener("change", refreshMailLog);

btnMailSend.addEventListener("click", async () => {
  const to = mailTo.value;
  const body = (mailBody.value || "").trim();
  if (!to || !body) return;
  const res = await fetch("/api/player/message", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, body }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
  else mailBody.value = "";
});

function refreshLlmDebugPanel() {
  if (!state || !state.llm_debug || !state.llm_debug.enabled) {
    llmDebugPanel.hidden = true;
    return;
  }
  llmDebugPanel.hidden = false;
  const parts = [];
  if (state.llm_debug.last_summary) parts.push(state.llm_debug.last_summary);
  const instr = state.llm_debug.instructions || [];
  if (instr.length) parts.push(`instructions: ${instr.join(", ")}`);
  llmDebugSummary.textContent = parts.length ? parts.join("\n") : "debug on — waiting for AI turns";
}

async function loadLlmDebugTraces() {
  const res = await fetch("/api/llm_debug");
  const data = await res.json();
  if (!data.ok) {
    llmDebugTrace.textContent = data.message || "failed to load";
    return;
  }
  const prev = llmDebugSelect.value;
  const traces = data.traces || [];
  llmDebugSelect.innerHTML = traces
    .map((t) => {
      const line = t.line || "";
      const parts = line.trim().split(/\s+/);
      const rel = parts[parts.length - 1] || line;
      return `<option value="${rel}">${line}</option>`;
    })
    .join("");
  if (prev && [...llmDebugSelect.options].some((o) => o.value === prev)) {
    llmDebugSelect.value = prev;
  }
  if (data.last_summary) {
    llmDebugSummary.textContent = data.last_summary;
  }
  const instr = data.instructions || [];
  if (instr.length) {
    llmDebugSummary.textContent =
      (llmDebugSummary.textContent || "") +
      (llmDebugSummary.textContent ? "\n" : "") +
      `instructions: ${instr.join(", ")}`;
  }
}

btnLlmDebugRefresh.addEventListener("click", () => {
  loadLlmDebugTraces().catch((e) => {
    llmDebugTrace.textContent = String(e);
  });
});

btnLlmDebugView.addEventListener("click", async () => {
  const path = llmDebugSelect.value;
  if (!path) {
    llmDebugTrace.textContent = "(no trace selected)";
    return;
  }
  const res = await fetch(`/api/llm_debug/trace?path=${encodeURIComponent(path)}`);
  const data = await res.json();
  if (!data.ok) {
    llmDebugTrace.textContent = data.message || "failed";
    return;
  }
  llmDebugTrace.textContent = data.text || "(empty)";
});

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => applyPayload(JSON.parse(ev.data));
  ws.onclose = () => setTimeout(connect, 1000);
  setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 15000);
}

async function boot() {
  try {
    const res = await fetch("/api/state");
    const data = await res.json();
    if (data.started && data.state) {
      state = data.state;
      showGame();
      refreshPanels();
      draw();
    } else {
      showSetup(data.defaults);
    }
  } catch {
    showSetup();
  }
  connect();
}

boot();
