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
const plotsForSaleEl = document.getElementById("plots-for-sale");
const govContractsEl = document.getElementById("gov-contracts");
const aiLog = document.getElementById("ai-log");
const aiMode = document.getElementById("ai-mode");
const btnPause = document.getElementById("btn-pause");
const btnPass = document.getElementById("btn-pass");
const btnStatus = document.getElementById("btn-status");
const btnPlotBuy = document.getElementById("btn-plot-buy");
const btnPlotSell = document.getElementById("btn-plot-sell");
const btnBuild = document.getElementById("btn-build");
const btnProduce = document.getElementById("btn-produce");
const btnSetMethod = document.getElementById("btn-set-method");
const btnRoad = document.getElementById("btn-road");
const btnMerge = document.getElementById("btn-merge");
const roadSide = document.getElementById("road-side");
const buildId = document.getElementById("build-id");
const methodId = document.getElementById("method-id");
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
const toolSelect = document.getElementById("tool-select");
const toolDesc = document.getElementById("tool-desc");
const toolArgs = document.getElementById("tool-args");
const toolResult = document.getElementById("tool-result");
const btnToolRun = document.getElementById("btn-tool-run");
const btnToolAutofill = document.getElementById("btn-tool-autofill");

let state = null;
let selected = null;
let lastOwnedClick = null;
let cellSize = 20;
let started = false;
let playerTools = [];

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  return res.json();
}

function showGame() {
  started = true;
  setupEl.hidden = true;
  appEl.hidden = false;
  resize();
  loadPlayerTools();
  refreshContentSelects();
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

function refreshContentSelects() {
  if (!state || !state.content) return;
  const buildings = state.content.buildings || [];
  const methods = state.content.production_methods || state.content.production || [];
  if (buildings.length) {
    const prev = buildId.value;
    buildId.innerHTML = buildings
      .map((b) => `<option value="${b.id}">${b.id}</option>`)
      .join("");
    if (prev && [...buildId.options].some((o) => o.value === prev)) buildId.value = prev;
  }
  if (methods.length) {
    const prev = methodId.value;
    methodId.innerHTML = methods
      .map((m) => `<option value="${m.id}">${m.id}</option>`)
      .join("");
    if (prev && [...methodId.options].some((o) => o.value === prev)) methodId.value = prev;
  }
}

function refreshGovPanel() {
  if (!state || !state.government_contracts) {
    govContractsEl.textContent = "—";
    return;
  }
  const contracts = state.government_contracts.contracts || state.government_contracts || [];
  const list = Array.isArray(contracts) ? contracts : [];
  if (!list.length) {
    govContractsEl.textContent = "(none)";
    return;
  }
  govContractsEl.textContent = list
    .slice(0, 12)
    .map((c) => {
      const req = c.requirements
        ? Object.entries(c.requirements).map(([k, v]) => `${v}x ${k}`).join(", ")
        : "";
      return `#${c.id} ${c.status || "?"} ${req} bids=${(c.bids || []).length}` +
        (c.awarded_to ? ` → ${c.awarded_to}` : "") +
        (c.winning_price != null ? ` @${c.winning_price}` : "");
    })
    .join("\n");
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
  refreshContentSelects();
  if (state.market) {
    const sells = (state.market.sell_listings || []).slice(0, 8);
    const buys = (state.market.buy_listings || []).slice(0, 6);
    const sellTxt = sells.length
      ? sells.map((L) => `S#${L.id} ${L.quantity}x ${L.item_id} @${L.price}`).join("\n")
      : "(no sells)";
    const buyTxt = buys.length
      ? buys.map((L) => `B#${L.id} ${L.quantity}x ${L.item_id} @${L.price}`).join("\n")
      : "(no buys)";
    marketEl.textContent = `${sellTxt}\n---\n${buyTxt}`;
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
  refreshGovPanel();
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
    btnSetMethod.disabled = true;
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
  btnSetMethod.disabled = !canProduce;
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
  const data = await api("/api/setup", body);
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
  await api("/api/pause", { paused });
});

btnStatus.addEventListener("click", async () => {
  const data = await api("/api/player/action", { name: "get_status", arguments: {} });
  toolResult.textContent = JSON.stringify(data, null, 2);
  toolSelect.value = "get_status";
  renderToolArgs();
});

btnPlotBuy.addEventListener("click", async () => {
  if (!selected) return;
  const t = tileAt(selected.x, selected.y);
  if (!t?.plot?.owner_id) return;
  const price = Number(prompt("Offer price for this plot?", String(t.plot.value || 100)));
  if (!Number.isFinite(price) || price < 0) return;
  const to = `${t.plot.owner_kind}:${t.plot.owner_id}`;
  const data = await api("/api/player/propose_plot_buy", { to, x: selected.x, y: selected.y, price });
  if (!data.ok) alert(data.message);
});

btnPlotSell.addEventListener("click", async () => {
  if (!selected) return;
  const to = prompt("Sell to (e.g. city:city_a or ai_1)", "city:city_a");
  if (!to) return;
  const price = Number(prompt("Ask price?", "150"));
  if (!Number.isFinite(price) || price < 0) return;
  const data = await api("/api/player/propose_plot_sell", { to, x: selected.x, y: selected.y, price });
  if (!data.ok) alert(data.message);
});

btnBuild.addEventListener("click", async () => {
  if (!selected) return;
  const data = await api("/api/player/build", {
    ...selected,
    building_id: buildId.value || "foundry",
  });
  if (!data.ok) alert(data.message);
});

btnSetMethod.addEventListener("click", async () => {
  if (!selected) return;
  const data = await api("/api/player/set_production_method", {
    ...selected,
    method_id: methodId.value || "make_steel",
  });
  if (!data.ok) alert(data.message);
  else toolResult.textContent = data.message || "method set";
});

btnRoad.addEventListener("click", async () => {
  if (!selected) return;
  const data = await api("/api/player/build_road", { ...selected, side: roadSide.value });
  if (!data.ok) alert(data.message);
});

btnMerge.addEventListener("click", async () => {
  if (!selected || !lastOwnedClick) return;
  const data = await api("/api/player/merge_plots", {
    x1: lastOwnedClick.x,
    y1: lastOwnedClick.y,
    x2: selected.x,
    y2: selected.y,
  });
  if (!data.ok) alert(data.message);
  else lastOwnedClick = selected;
});

btnProduce.addEventListener("click", async () => {
  if (!selected) return;
  const data = await api("/api/player/produce", selected);
  if (!data.ok) alert(data.message);
});

btnPass.addEventListener("click", async () => {
  const data = await api("/api/player/pass", {});
  if (!data.ok) alert(data.message);
});

btnAccept.addEventListener("click", async () => {
  const proposal_id = Number(proposalIdInput.value);
  if (!proposal_id) return;
  const data = await api("/api/player/accept_proposal", { proposal_id });
  if (!data.ok) alert(data.message);
});

btnReject.addEventListener("click", async () => {
  const proposal_id = Number(proposalIdInput.value);
  if (!proposal_id) return;
  const data = await api("/api/player/reject_proposal", { proposal_id });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-propose-sell").addEventListener("click", async () => {
  const data = await api("/api/player/propose_sell", {
    to: document.getElementById("trade-to").value.trim(),
    item_id: document.getElementById("trade-item").value.trim(),
    quantity: Number(document.getElementById("trade-qty").value),
    price: Number(document.getElementById("trade-price").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-propose-buy").addEventListener("click", async () => {
  const data = await api("/api/player/propose_buy", {
    to: document.getElementById("trade-to").value.trim(),
    item_id: document.getElementById("trade-item").value.trim(),
    quantity: Number(document.getElementById("trade-qty").value),
    price: Number(document.getElementById("trade-price").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-mkt-buy").addEventListener("click", async () => {
  const data = await api("/api/player/market/buy", {
    item_id: document.getElementById("mkt-item").value.trim(),
    quantity: Number(document.getElementById("mkt-qty").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-mkt-sell").addEventListener("click", async () => {
  const data = await api("/api/player/market/sell", {
    item_id: document.getElementById("mkt-item").value.trim(),
    quantity: Number(document.getElementById("mkt-qty").value),
    price: Number(document.getElementById("mkt-price").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-mkt-buy-order").addEventListener("click", async () => {
  const data = await api("/api/player/market/buy_order", {
    item_id: document.getElementById("mkt-item").value.trim(),
    quantity: Number(document.getElementById("mkt-qty").value),
    price: Number(document.getElementById("mkt-price").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-mkt-retract-sell").addEventListener("click", async () => {
  const data = await api("/api/player/market/retract_sell", {
    listing_id: Number(document.getElementById("mkt-listing").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-mkt-retract-buy").addEventListener("click", async () => {
  const data = await api("/api/player/market/retract_buy", {
    listing_id: Number(document.getElementById("mkt-listing").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-gov-refresh").addEventListener("click", async () => {
  const data = await api("/api/government_contracts");
  if (!data.ok) {
    govContractsEl.textContent = data.message || "failed";
    return;
  }
  const contracts = data.data?.contracts || data.data || [];
  const list = Array.isArray(contracts) ? contracts : [];
  govContractsEl.textContent = list.length
    ? JSON.stringify(list, null, 2)
    : "(none)";
});

document.getElementById("btn-gov-bid").addEventListener("click", async () => {
  const data = await api("/api/player/bid_government_contract", {
    contract_id: Number(document.getElementById("gov-id").value),
    price: Number(document.getElementById("gov-price").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-gov-fulfill").addEventListener("click", async () => {
  const data = await api("/api/player/fulfill_government_contract", {
    contract_id: Number(document.getElementById("gov-id").value),
  });
  if (!data.ok) alert(data.message);
});

document.getElementById("btn-refresh-plots").addEventListener("click", async () => {
  const data = await fetch("/api/plots_for_sale?limit=24").then((r) => r.json());
  if (!data.ok) {
    plotsForSaleEl.textContent = data.message || "failed";
    return;
  }
  const plots = data.data?.plots || data.data || [];
  plotsForSaleEl.textContent = Array.isArray(plots) && plots.length
    ? plots.map((p) => `(${p.x},${p.y}) ${p.owner || p.owner_key || "?"} value=${p.value}`).join("\n")
    : JSON.stringify(data, null, 2);
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
  const data = await api("/api/player/message", { to, body });
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

async function loadPlayerTools() {
  try {
    const data = await fetch("/api/player/tools").then((r) => r.json());
    playerTools = data.tools || [];
    const prev = toolSelect.value;
    toolSelect.innerHTML = playerTools
      .map((t) => `<option value="${t.name}">${t.name}</option>`)
      .join("");
    if (prev && playerTools.some((t) => t.name === prev)) toolSelect.value = prev;
    renderToolArgs();
  } catch (e) {
    toolDesc.textContent = String(e);
  }
}

function currentTool() {
  return playerTools.find((t) => t.name === toolSelect.value) || null;
}

function renderToolArgs() {
  const tool = currentTool();
  toolArgs.innerHTML = "";
  if (!tool) {
    toolDesc.textContent = "—";
    return;
  }
  toolDesc.textContent = tool.description || "";
  const params = tool.parameters || {};
  const required = new Set(tool.required || []);
  for (const [key, schema] of Object.entries(params)) {
    const label = document.createElement("label");
    const req = required.has(key) ? " *" : "";
    label.textContent = `${key}${req}`;
    const type = schema.type || "string";
    let input;
    if (type === "object") {
      input = document.createElement("textarea");
      input.rows = 2;
      input.placeholder = '{}';
      input.dataset.json = "1";
    } else {
      input = document.createElement("input");
      input.type = type === "integer" || type === "number" ? "number" : "text";
      if (schema.enum) {
        input = document.createElement("select");
        for (const v of schema.enum) {
          const opt = document.createElement("option");
          opt.value = v;
          opt.textContent = v;
          input.appendChild(opt);
        }
      }
    }
    input.dataset.key = key;
    input.dataset.type = type;
    if (schema.description) input.title = schema.description;
    label.appendChild(input);
    toolArgs.appendChild(label);
  }
}

function collectToolArguments() {
  const args = {};
  for (const el of toolArgs.querySelectorAll("[data-key]")) {
    const key = el.dataset.key;
    const type = el.dataset.type;
    let raw = el.value;
    if (raw === "" || raw == null) continue;
    if (el.dataset.json === "1") {
      try {
        args[key] = JSON.parse(raw);
      } catch {
        throw new Error(`Invalid JSON for ${key}`);
      }
    } else if (type === "integer") {
      args[key] = Number.parseInt(raw, 10);
    } else if (type === "number") {
      args[key] = Number(raw);
    } else {
      args[key] = raw;
    }
  }
  return args;
}

function autofillToolArgs() {
  for (const el of toolArgs.querySelectorAll("[data-key]")) {
    const key = el.dataset.key;
    if ((key === "x" || key === "x1" || key === "x2") && selected) {
      if (key === "x2" && lastOwnedClick) el.value = lastOwnedClick.x;
      else if (key === "x1" && lastOwnedClick) el.value = lastOwnedClick.x;
      else if (key === "x") el.value = selected.x;
      else if (key === "x1") el.value = selected.x;
    }
    if ((key === "y" || key === "y1" || key === "y2") && selected) {
      if (key === "y2" && lastOwnedClick) el.value = lastOwnedClick.y;
      else if (key === "y1" && lastOwnedClick) el.value = lastOwnedClick.y;
      else if (key === "y") el.value = selected.y;
      else if (key === "y1") el.value = selected.y;
    }
    if (key === "x2" && selected) el.value = selected.x;
    if (key === "y2" && selected) el.value = selected.y;
    if (key === "side") el.value = roadSide.value;
    if (key === "building_id") el.value = buildId.value;
    if (key === "method_id") el.value = methodId.value;
    if (key === "item_id" && !el.value) el.value = document.getElementById("mkt-item").value || "iron_ore";
    if (key === "to" && selected) {
      const t = tileAt(selected.x, selected.y);
      if (t?.plot?.owner_id && !isPlayerOwned(t.plot)) {
        el.value = `${t.plot.owner_kind}:${t.plot.owner_id}`;
      }
    }
  }
}

toolSelect.addEventListener("change", renderToolArgs);
btnToolAutofill.addEventListener("click", autofillToolArgs);
btnToolRun.addEventListener("click", async () => {
  const name = toolSelect.value;
  if (!name) return;
  try {
    const arguments_ = collectToolArguments();
    const data = await api("/api/player/action", { name, arguments: arguments_ });
    toolResult.textContent = JSON.stringify(data, null, 2);
    if (!data.ok) alert(data.message || "tool failed");
  } catch (e) {
    toolResult.textContent = String(e);
    alert(String(e));
  }
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
