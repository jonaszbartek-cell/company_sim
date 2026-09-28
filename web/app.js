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
const govContractsEl = document.getElementById("gov-contracts");
const plotsForSaleEl = document.getElementById("plots-for-sale");
const actionMsg = document.getElementById("action-msg");
const aiLog = document.getElementById("ai-log");
const aiMode = document.getElementById("ai-mode");
const btnPause = document.getElementById("btn-pause");
const btnPass = document.getElementById("btn-pass");
const btnPlotBuy = document.getElementById("btn-plot-buy");
const btnPlotSell = document.getElementById("btn-plot-sell");
const btnBuild = document.getElementById("btn-build");
const btnSetMethod = document.getElementById("btn-set-method");
const btnProduce = document.getElementById("btn-produce");
const btnRoad = document.getElementById("btn-road");
const btnMerge = document.getElementById("btn-merge");
const roadSide = document.getElementById("road-side");
const plotPrice = document.getElementById("plot-price");
const plotSellTo = document.getElementById("plot-sell-to");
const buildingIdSelect = document.getElementById("building-id");
const methodIdSelect = document.getElementById("method-id");
const goodsTo = document.getElementById("goods-to");
const goodsItem = document.getElementById("goods-item");
const goodsQty = document.getElementById("goods-qty");
const goodsPrice = document.getElementById("goods-price");
const btnProposeSell = document.getElementById("btn-propose-sell");
const btnProposeBuy = document.getElementById("btn-propose-buy");
const mktItem = document.getElementById("mkt-item");
const mktQty = document.getElementById("mkt-qty");
const mktPrice = document.getElementById("mkt-price");
const mktListingId = document.getElementById("mkt-listing-id");
const btnMktBuy = document.getElementById("btn-mkt-buy");
const btnMktSell = document.getElementById("btn-mkt-sell");
const btnMktBuyOrder = document.getElementById("btn-mkt-buy-order");
const btnMktRetractSell = document.getElementById("btn-mkt-retract-sell");
const btnMktRetractBuy = document.getElementById("btn-mkt-retract-buy");
const govId = document.getElementById("gov-id");
const govBid = document.getElementById("gov-bid");
const btnGovBid = document.getElementById("btn-gov-bid");
const btnGovFulfill = document.getElementById("btn-gov-fulfill");
const btnRefreshPlots = document.getElementById("btn-refresh-plots");
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
let contentFilled = false;
let pingTimer = null;

function showMsg(text, ok = true) {
  actionMsg.hidden = false;
  actionMsg.textContent = text;
  actionMsg.classList.toggle("ok", ok);
  actionMsg.classList.toggle("err", !ok);
}

async function postAction(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json();
  if (!data.ok) showMsg(data.message || "Action failed", false);
  else showMsg(data.message || "OK", true);
  return data;
}

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

function playerKey() {
  return `company:${state.player_company_id}`;
}

function contactOptions() {
  if (!state || !state.mailboxes) return [];
  const pid = playerKey();
  const options = [];
  for (const box of state.mailboxes.mailboxes || []) {
    const other = (box.participants || []).find((p) => p !== pid);
    if (other) options.push(other);
  }
  options.sort();
  return options;
}

function fillSelect(el, values, { keep = true, labels = null } = {}) {
  const prev = el.value;
  el.innerHTML = values
    .map((v, i) => {
      const label = labels ? labels[i] : v;
      return `<option value="${v}">${label}</option>`;
    })
    .join("");
  if (keep && prev && values.includes(prev)) el.value = prev;
}

function ensureContentSelects() {
  if (!state || !state.content) return;
  const items = (state.content.items || []).map((i) => i.id);
  const buildings = (state.content.buildings || []).map((b) => b.id);
  const methods = (state.content.production_methods || []).map((m) => m.id);
  const itemLabels = (state.content.items || []).map((i) => i.name || i.id);
  const buildingLabels = (state.content.buildings || []).map(
    (b) => `${b.name || b.id} ($${b.build_cost})`
  );
  const methodLabels = (state.content.production_methods || []).map((m) => m.name || m.id);

  if (!contentFilled || mktItem.options.length !== items.length) {
    fillSelect(mktItem, items, { labels: itemLabels });
    fillSelect(goodsItem, items, { labels: itemLabels });
    fillSelect(buildingIdSelect, buildings.length ? buildings : ["foundry"], {
      labels: buildingLabels.length ? buildingLabels : ["foundry"],
    });
    fillSelect(methodIdSelect, methods.length ? methods : ["make_steel"], {
      labels: methodLabels.length ? methodLabels : ["make_steel"],
    });
    contentFilled = true;
  }
}

function refreshContactSelects() {
  const contacts = contactOptions();
  fillSelect(plotSellTo, contacts);
  fillSelect(goodsTo, contacts);
  const prev = mailTo.value;
  fillSelect(
    mailTo,
    contacts,
    {
      keep: true,
      labels: contacts.map((c) => {
        const box = (state.mailboxes.mailboxes || []).find(
          (b) => (b.participants || []).includes(playerKey()) && (b.participants || []).includes(c)
        );
        return `${c} (${box?.message_count || 0})`;
      }),
    }
  );
  if (prev && contacts.includes(prev)) mailTo.value = prev;
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

function formatProposal(p) {
  if (p.proposal_type?.startsWith("plot_")) {
    return `#${p.id} ${p.proposal_type} (${p.plot_x},${p.plot_y}) @${p.price} ${p.from}→${p.to}`;
  }
  return `#${p.id} ${p.proposal_type || p.side} ${p.quantity}x ${p.item_id} @${p.price} ${p.from}→${p.to}`;
}

function refreshProposals() {
  const props = state?.proposals?.proposals || [];
  if (!props.length) {
    proposalsEl.textContent = "(none)";
    return;
  }
  proposalsEl.innerHTML = "";
  for (const p of props) {
    const row = document.createElement("div");
    row.className = "list-row";
    const text = document.createElement("span");
    text.textContent = formatProposal(p);
    const actions = document.createElement("div");
    actions.className = "list-actions";
    const accept = document.createElement("button");
    accept.type = "button";
    accept.textContent = "Accept";
    accept.addEventListener("click", () =>
      postAction("/api/player/accept_proposal", { proposal_id: p.id })
    );
    const reject = document.createElement("button");
    reject.type = "button";
    reject.textContent = "Reject";
    reject.addEventListener("click", () =>
      postAction("/api/player/reject_proposal", { proposal_id: p.id })
    );
    actions.append(accept, reject);
    row.append(text, actions);
    proposalsEl.appendChild(row);
  }
}

function refreshGovContracts() {
  const contracts = state?.government_contracts?.contracts || [];
  if (!contracts.length) {
    govContractsEl.textContent = "(none)";
    return;
  }
  govContractsEl.innerHTML = "";
  for (const c of contracts) {
    const row = document.createElement("div");
    row.className = "list-row";
    const req = Object.entries(c.requirements || {})
      .map(([k, v]) => `${v}x ${k}`)
      .join(", ");
    const bids = (c.bids || []).map((b) => `${b.company_id}:$${b.price}`).join(", ");
    const text = document.createElement("span");
    text.textContent = `#${c.id} [${c.status}] city=${c.city_id} need={${req}}${
      c.winner_company_id ? ` winner=${c.winner_company_id}` : ""
    }${bids ? ` bids=${bids}` : ""}`;
    const actions = document.createElement("div");
    actions.className = "list-actions";
    if (c.status === "open") {
      const bidBtn = document.createElement("button");
      bidBtn.type = "button";
      bidBtn.textContent = "Bid";
      bidBtn.addEventListener("click", () => {
        govId.value = String(c.id);
        const price = Number(govBid.value);
        if (!Number.isFinite(price) || price < 0) {
          showMsg("Enter a bid price", false);
          return;
        }
        postAction("/api/player/bid_government_contract", {
          contract_id: c.id,
          price,
        });
      });
      actions.appendChild(bidBtn);
    }
    if (c.status === "awarded" && c.winner_company_id === state.player_company_id) {
      const fulfillBtn = document.createElement("button");
      fulfillBtn.type = "button";
      fulfillBtn.textContent = "Fulfill";
      fulfillBtn.addEventListener("click", () =>
        postAction("/api/player/fulfill_government_contract", { contract_id: c.id })
      );
      actions.appendChild(fulfillBtn);
    }
    row.append(text, actions);
    govContractsEl.appendChild(row);
  }
}

function refreshPanels() {
  if (!state) return;
  ensureContentSelects();
  refreshContactSelects();

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
    const sells = state.market.sell_listings || [];
    const buys = state.market.buy_listings || [];
    const sellLines = sells.length
      ? sells.map((L) => `S#${L.id} ${L.quantity}x ${L.item_id} @${L.price} (${L.owner_kind}:${L.owner_id})`)
      : ["(no sell listings)"];
    const buyLines = buys.length
      ? buys.map((L) => `B#${L.id} ${L.quantity}x ${L.item_id} @${L.price} (${L.owner_kind}:${L.owner_id})`)
      : ["(no buy orders)"];
    marketEl.textContent = [...sellLines, ...buyLines].join("\n");
  }

  refreshProposals();
  refreshGovContracts();
  refreshMailLog();
  refreshLlmDebugPanel();
  btnPause.textContent = state.paused ? "Resume" : "Pause";

  if (!selected) {
    selectedEl.textContent = "Click a plot";
    btnPlotBuy.disabled = true;
    btnPlotSell.disabled = true;
    btnBuild.disabled = true;
    btnSetMethod.disabled = true;
    btnProduce.disabled = true;
    btnRoad.disabled = true;
    btnMerge.disabled = true;
    return;
  }
  const t = tileAt(selected.x, selected.y);
  const summary = {
    x: selected.x,
    y: selected.y,
    owner: t?.plot ? `${t.plot.owner_kind}:${t.plot.owner_id}` : null,
    type: t?.plot?.plot_type,
    value: t?.plot?.value,
    group: t?.plot?.group_size,
    bonus: t?.plot?.production_bonus,
    roads: t?.plot?.roads,
    reserved: t?.plot?.reserved_proposal_id,
    building: t?.plot?.building || null,
    merge_with: lastOwnedClick,
  };
  selectedEl.textContent = JSON.stringify(summary, null, 2);
  if (t?.plot?.value != null && document.activeElement !== plotPrice) {
    plotPrice.value = String(t.plot.value);
  }
  if (t?.plot?.building?.production_method_id) {
    const mid = t.plot.building.production_method_id;
    if ([...methodIdSelect.options].some((o) => o.value === mid)) methodIdSelect.value = mid;
  }

  const canBuy =
    t && t.plot && t.plot.owner_id && !isPlayerOwned(t.plot) && !t.plot.reserved_proposal_id;
  const canSell = t && isPlayerOwned(t.plot) && !t.plot.reserved_proposal_id;
  const canBuild = t && isPlayerOwned(t.plot) && !t.plot.building && !t.plot.reserved_proposal_id;
  const canProduce = t && isPlayerOwned(t.plot) && t.plot.building;
  const canMethod = canProduce;
  const canRoad = t && isPlayerOwned(t.plot);
  let canMerge = false;
  if (
    lastOwnedClick &&
    t &&
    isPlayerOwned(t.plot) &&
    !(lastOwnedClick.x === selected.x && lastOwnedClick.y === selected.y)
  ) {
    const dist = Math.abs(lastOwnedClick.x - selected.x) + Math.abs(lastOwnedClick.y - selected.y);
    canMerge = dist === 1;
  }
  btnPlotBuy.disabled = !canBuy;
  btnPlotSell.disabled = !canSell;
  btnBuild.disabled = !canBuild;
  btnSetMethod.disabled = !canMethod;
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
  contentFilled = false;
  state = data.state;
  showGame();
  refreshPanels();
  draw();
  loadPlotsForSale();
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
  await postAction("/api/pause", { paused });
});

btnPlotBuy.addEventListener("click", async () => {
  if (!selected) return;
  const t = tileAt(selected.x, selected.y);
  if (!t?.plot?.owner_id) return;
  const price = Number(plotPrice.value);
  if (!Number.isFinite(price) || price < 0) {
    showMsg("Invalid price", false);
    return;
  }
  const to = `${t.plot.owner_kind}:${t.plot.owner_id}`;
  await postAction("/api/player/propose_plot_buy", {
    to,
    x: selected.x,
    y: selected.y,
    price,
  });
});

btnPlotSell.addEventListener("click", async () => {
  if (!selected) return;
  const to = plotSellTo.value;
  if (!to) {
    showMsg("Pick a buyer", false);
    return;
  }
  const price = Number(plotPrice.value);
  if (!Number.isFinite(price) || price < 0) {
    showMsg("Invalid price", false);
    return;
  }
  await postAction("/api/player/propose_plot_sell", {
    to,
    x: selected.x,
    y: selected.y,
    price,
  });
});

btnBuild.addEventListener("click", async () => {
  if (!selected) return;
  await postAction("/api/player/build", {
    ...selected,
    building_id: buildingIdSelect.value || "foundry",
  });
});

btnSetMethod.addEventListener("click", async () => {
  if (!selected) return;
  await postAction("/api/player/set_production_method", {
    ...selected,
    method_id: methodIdSelect.value,
  });
});

btnRoad.addEventListener("click", async () => {
  if (!selected) return;
  await postAction("/api/player/build_road", {
    ...selected,
    side: roadSide.value,
  });
});

btnMerge.addEventListener("click", async () => {
  if (!selected || !lastOwnedClick) return;
  const data = await postAction("/api/player/merge_plots", {
    x1: lastOwnedClick.x,
    y1: lastOwnedClick.y,
    x2: selected.x,
    y2: selected.y,
  });
  if (data.ok) lastOwnedClick = selected;
});

btnProduce.addEventListener("click", async () => {
  if (!selected) return;
  await postAction("/api/player/produce", selected);
});

btnPass.addEventListener("click", async () => {
  await postAction("/api/player/pass");
});

btnProposeSell.addEventListener("click", async () => {
  await postAction("/api/player/propose_sell", {
    to: goodsTo.value,
    item_id: goodsItem.value,
    quantity: Number(goodsQty.value),
    price: Number(goodsPrice.value),
  });
});

btnProposeBuy.addEventListener("click", async () => {
  await postAction("/api/player/propose_buy", {
    to: goodsTo.value,
    item_id: goodsItem.value,
    quantity: Number(goodsQty.value),
    price: Number(goodsPrice.value),
  });
});

btnMktBuy.addEventListener("click", async () => {
  await postAction("/api/player/market/buy", {
    item_id: mktItem.value,
    quantity: Number(mktQty.value),
  });
});

btnMktSell.addEventListener("click", async () => {
  await postAction("/api/player/market/sell", {
    item_id: mktItem.value,
    quantity: Number(mktQty.value),
    price: Number(mktPrice.value),
  });
});

btnMktBuyOrder.addEventListener("click", async () => {
  await postAction("/api/player/market/buy_order", {
    item_id: mktItem.value,
    quantity: Number(mktQty.value),
    price: Number(mktPrice.value),
  });
});

btnMktRetractSell.addEventListener("click", async () => {
  const listing_id = Number(mktListingId.value);
  if (!listing_id) {
    showMsg("Enter listing #", false);
    return;
  }
  await postAction("/api/player/market/retract_sell", { listing_id });
});

btnMktRetractBuy.addEventListener("click", async () => {
  const listing_id = Number(mktListingId.value);
  if (!listing_id) {
    showMsg("Enter listing #", false);
    return;
  }
  await postAction("/api/player/market/retract_buy", { listing_id });
});

btnGovBid.addEventListener("click", async () => {
  const contract_id = Number(govId.value);
  const price = Number(govBid.value);
  if (!contract_id) {
    showMsg("Enter contract #", false);
    return;
  }
  await postAction("/api/player/bid_government_contract", { contract_id, price });
});

btnGovFulfill.addEventListener("click", async () => {
  const contract_id = Number(govId.value);
  if (!contract_id) {
    showMsg("Enter contract #", false);
    return;
  }
  await postAction("/api/player/fulfill_government_contract", { contract_id });
});

async function loadPlotsForSale() {
  try {
    const res = await fetch("/api/plots_for_sale?limit=12");
    const data = await res.json();
    if (!data.ok) {
      plotsForSaleEl.textContent = data.message || "failed";
      return;
    }
    const plots = data.data?.plots || [];
    plotsForSaleEl.textContent = plots.length
      ? plots
          .map(
            (p) =>
              `(${p.x},${p.y}) ${p.plot_type} val=${p.value} ${p.owner}`
          )
          .join("\n")
      : "(none)";
  } catch (e) {
    plotsForSaleEl.textContent = String(e);
  }
}

btnRefreshPlots.addEventListener("click", () => {
  loadPlotsForSale();
});

function refreshMailLog() {
  if (!state || !state.mailboxes) {
    mailLog.textContent = "—";
    return;
  }
  const pid = playerKey();
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
  const data = await postAction("/api/player/message", { to, body });
  if (data.ok) mailBody.value = "";
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
  ws.onclose = () => {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
    setTimeout(connect, 1000);
  };
  if (pingTimer) clearInterval(pingTimer);
  pingTimer = setInterval(() => {
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
      loadPlotsForSale();
    } else {
      showSetup(data.defaults);
    }
  } catch {
    showSetup();
  }
  connect();
}

boot();
