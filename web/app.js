const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
const hudTime = document.getElementById("hud-time");
const hudCash = document.getElementById("hud-cash");
const selectedEl = document.getElementById("selected");
const inventoryEl = document.getElementById("inventory");
const marketEl = document.getElementById("market");
const aiLog = document.getElementById("ai-log");
const aiMode = document.getElementById("ai-mode");
const btnPause = document.getElementById("btn-pause");
const btnPass = document.getElementById("btn-pass");
const btnBuy = document.getElementById("btn-buy");
const btnBuild = document.getElementById("btn-build");
const btnProduce = document.getElementById("btn-produce");
const btnRoad = document.getElementById("btn-road");
const btnMerge = document.getElementById("btn-merge");
const btnMktBuyIron = document.getElementById("btn-mkt-buy-iron");
const btnMktSellSteel = document.getElementById("btn-mkt-sell-steel");
const btnMktBuyOrder = document.getElementById("btn-mkt-buy-order");
const btnMktRetract = document.getElementById("btn-mkt-retract");
const mktRetractId = document.getElementById("mkt-retract-id");
const tradeTo = document.getElementById("trade-to");
const proposalsEl = document.getElementById("proposals");
const proposalIdInput = document.getElementById("proposal-id");
const btnProposeSell = document.getElementById("btn-propose-sell");
const btnProposeBuy = document.getElementById("btn-propose-buy");
const btnAcceptProposal = document.getElementById("btn-accept-proposal");
const btnRejectProposal = document.getElementById("btn-reject-proposal");
const btnCancelProposal = document.getElementById("btn-cancel-proposal");
const mailTo = document.getElementById("mail-to");
const mailBody = document.getElementById("mail-body");
const mailLog = document.getElementById("mail-log");
const btnMailSend = document.getElementById("btn-mail-send");

let state = null;
let selected = null;
let lastOwnedClick = null;
let cellSize = 20;

function resize() {
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

function draw() {
  if (!state) return;
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
    if (t.kind === "road") ctx.fillStyle = "#5a6570";
    else if (t.kind === "plot") {
      if (t.plot?.building) ctx.fillStyle = "#c47a4a";
      else if (isPlayerOwned(t.plot)) ctx.fillStyle = "#2f8f6b";
      else if (t.plot?.owner_kind === "city") ctx.fillStyle = "#7a6a3a";
      else if (t.plot?.owner_kind === "company") ctx.fillStyle = "#6b3f5a";
      else if (t.plot?.plot_type === "specialized") ctx.fillStyle = "#4a6b3f";
      else ctx.fillStyle = "#3f6b4f";
    } else continue;
    ctx.fillRect(px + 1, py + 1, cellSize - 2, cellSize - 2);

    if (t.city_id) {
      const idx = state.map.cities.findIndex((c) => c.id === t.city_id);
      const hues = [210, 140, 30, 300, 0];
      const h = hues[(idx >= 0 ? idx : 0) % hues.length];
      ctx.fillStyle = `hsla(${h}, 40%, 50%, 0.08)`;
      ctx.fillRect(px + 1, py + 1, cellSize - 2, cellSize - 2);
    }

    if (t.plot?.plot_type === "specialized" && !t.plot.building && !t.plot.owner_id) {
      ctx.fillStyle = "rgba(255,220,120,0.35)";
      ctx.fillRect(px + 2, py + 2, 3, 3);
    }
    if (t.plot?.parcel_size > 1) {
      ctx.strokeStyle = "rgba(125, 209, 255, 0.7)";
      ctx.strokeRect(px + 2, py + 2, cellSize - 4, cellSize - 4);
    }
    if (t.plot?.building) {
      ctx.fillStyle = "#1a1008";
      ctx.font = `${Math.max(9, cellSize * 0.4)}px sans-serif`;
      ctx.fillText(t.plot.owner_kind === "city" ? "M" : "B", px + 3, py + cellSize - 3);
      const p = t.plot.building.progress || 0;
      ctx.fillStyle = "rgba(0,0,0,0.45)";
      ctx.fillRect(px + 2, py + 2, cellSize - 4, 3);
      ctx.fillStyle = "#7ad1ff";
      ctx.fillRect(px + 2, py + 2, (cellSize - 4) * p, 3);
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
    const sells = (state.market.sell_listings || []).slice(0, 6);
    const buys = (state.market.buy_listings || []).slice(0, 4);
    const sellTxt = sells.length
      ? sells.map((L) => `#${L.id} sell ${L.quantity}x ${L.item_id} @${L.price} (${L.owner_id})`).join("\n")
      : "(no sells)";
    const buyTxt = buys.length
      ? buys.map((L) => `#${L.id} buy ${L.quantity}x ${L.item_id} @${L.price} (${L.owner_id})`).join("\n")
      : "(no buys)";
    marketEl.textContent = `${sellTxt}\n---\n${buyTxt}`;
  }
  refreshTradeContacts();
  refreshProposals();
  refreshMailContacts();
  refreshMailLog();
  btnPause.textContent = state.paused ? "Resume" : "Pause";

  if (!selected) {
    selectedEl.textContent = "Click a plot / road candidate";
    btnBuy.disabled = true;
    btnBuild.disabled = true;
    btnProduce.disabled = true;
    btnRoad.disabled = true;
    btnMerge.disabled = true;
    return;
  }
  const t = tileAt(selected.x, selected.y);
  selectedEl.textContent = JSON.stringify({ x: selected.x, y: selected.y, tile: t }, null, 2);
  const canBuy = t && t.kind === "plot" && t.plot && !t.plot.owner_id;
  const canBuild = t && t.kind === "plot" && isPlayerOwned(t.plot) && !t.plot.building;
  const canProduce = t && t.kind === "plot" && isPlayerOwned(t.plot) && t.plot.building;
  const canRoad = t && ((t.kind === "plot" && t.plot && !t.plot.owner_id) || t.kind === "empty");
  let canMerge = false;
  if (lastOwnedClick && t && isPlayerOwned(t.plot) && !(lastOwnedClick.x === selected.x && lastOwnedClick.y === selected.y)) {
    const dist = Math.abs(lastOwnedClick.x - selected.x) + Math.abs(lastOwnedClick.y - selected.y);
    canMerge = dist === 1;
  }
  btnBuy.disabled = !canBuy;
  btnBuild.disabled = !canBuild;
  btnProduce.disabled = !canProduce;
  btnRoad.disabled = !canRoad;
  btnMerge.disabled = !canMerge;
}

function applyPayload(payload) {
  if (payload.state) state = payload.state;
  if (payload.ai) aiLog.textContent = payload.ai;
  if (payload.ai_mode) aiMode.textContent = `mode: ${payload.ai_mode}`;
  refreshPanels();
  draw();
}

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

btnBuy.addEventListener("click", async () => {
  if (!selected) return;
  const res = await fetch("/api/player/buy_plot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(selected),
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
    body: JSON.stringify(selected),
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

btnMktBuyOrder.addEventListener("click", async () => {
  const res = await fetch("/api/player/market/buy_order", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_id: "coal", quantity: 1, price: 8 }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnMktRetract.addEventListener("click", async () => {
  const listing_id = Number(mktRetractId.value);
  if (!listing_id) return;
  const res = await fetch("/api/player/market/retract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ listing_id }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

function refreshTradeContacts() {
  if (!tradeTo || !state || !state.mailboxes) return;
  const pid = `company:${state.player_company_id}`;
  const boxes = state.mailboxes.mailboxes || [];
  const prev = tradeTo.value;
  const options = [];
  for (const box of boxes) {
    const other = (box.participants || []).find((p) => p !== pid);
    if (!other) continue;
    options.push(other);
  }
  options.sort();
  tradeTo.innerHTML = options.map((k) => `<option value="${k}">${k}</option>`).join("");
  if (prev && options.includes(prev)) tradeTo.value = prev;
}

function refreshProposals() {
  if (!proposalsEl || !state) return;
  const mine = (state.proposals && state.proposals.proposals) || [];
  const pid = `company:${state.player_company_id}`;
  const relevant = mine.filter((p) => p.from === pid || p.to === pid);
  if (!relevant.length) {
    proposalsEl.textContent = "(no open proposals involving you)";
    return;
  }
  proposalsEl.textContent = relevant
    .map((p) => `#${p.id} ${p.side} ${p.quantity}x ${p.item_id} @${p.price} ${p.from}→${p.to}`)
    .join("\n");
}

btnProposeSell.addEventListener("click", async () => {
  const to = tradeTo.value;
  if (!to) return;
  const res = await fetch("/api/player/propose_sell", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, item_id: "steel", quantity: 1, price: 40 }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnProposeBuy.addEventListener("click", async () => {
  const to = tradeTo.value;
  if (!to) return;
  const res = await fetch("/api/player/propose_buy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, item_id: "iron", quantity: 1, price: 10 }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

btnAcceptProposal.addEventListener("click", async () => {
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

btnRejectProposal.addEventListener("click", async () => {
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

btnCancelProposal.addEventListener("click", async () => {
  const proposal_id = Number(proposalIdInput.value);
  if (!proposal_id) return;
  const res = await fetch("/api/player/cancel_proposal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposal_id }),
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

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => applyPayload(JSON.parse(ev.data));
  ws.onclose = () => setTimeout(connect, 1000);
  setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 15000);
}

resize();
connect();
