const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
const hudTime = document.getElementById("hud-time");
const hudCash = document.getElementById("hud-cash");
const selectedEl = document.getElementById("selected");
const inventoryEl = document.getElementById("inventory");
const aiLog = document.getElementById("ai-log");
const btnPause = document.getElementById("btn-pause");
const btnBuy = document.getElementById("btn-buy");
const btnBuild = document.getElementById("btn-build");

let state = null;
let selected = null; // {x,y}
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

function draw() {
  if (!state) return;
  const { width, height } = state.map;
  cellSize = Math.floor(Math.min(canvas.width / width, canvas.height / height));
  const ox = Math.floor((canvas.width - width * cellSize) / 2);
  const oy = Math.floor((canvas.height - height * cellSize) / 2);

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#0e1317";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // faint grid
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
    else if (t.kind === "city") ctx.fillStyle = "#f0c14a";
    else if (t.kind === "plot") {
      if (t.plot?.building) ctx.fillStyle = "#c47a4a";
      else if (t.plot?.owner_company_id === state.player_company_id) ctx.fillStyle = "#2f8f6b";
      else if (t.plot?.owner_company_id) ctx.fillStyle = "#6b3f5a";
      else ctx.fillStyle = "#3f6b4f";
    } else continue;
    ctx.fillRect(px + 1, py + 1, cellSize - 2, cellSize - 2);

    if (t.kind === "city") {
      ctx.fillStyle = "#1a1408";
      ctx.font = `${Math.max(9, cellSize * 0.45)}px sans-serif`;
      ctx.fillText("C", px + 4, py + cellSize - 4);
    }
    if (t.plot?.building) {
      ctx.fillStyle = "#1a1008";
      ctx.font = `${Math.max(9, cellSize * 0.4)}px sans-serif`;
      ctx.fillText("B", px + 3, py + cellSize - 3);
      // production bar
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

  // city labels
  ctx.fillStyle = "#e7eef2";
  ctx.font = "12px sans-serif";
  for (const c of state.map.cities) {
    const px = ox + c.x * cellSize + cellSize + 4;
    const py = oy + c.y * cellSize + cellSize * 0.7;
    ctx.fillText(`${c.name} (${c.population})`, px, py);
  }
}

function refreshPanels() {
  if (!state) return;
  hudTime.textContent = `t=${state.time_sec.toFixed(1)}s` + (state.paused ? " PAUSED" : "");
  const player = state.companies.find((c) => c.id === state.player_company_id);
  hudCash.textContent = player ? `cash=${player.cash}` : "cash=—";
  inventoryEl.textContent = player ? JSON.stringify(player.inventory, null, 2) : "—";
  btnPause.textContent = state.paused ? "Resume" : "Pause";

  if (!selected) {
    selectedEl.textContent = "Click a plot";
    btnBuy.disabled = true;
    btnBuild.disabled = true;
    return;
  }
  const t = tileAt(selected.x, selected.y);
  selectedEl.textContent = JSON.stringify({ x: selected.x, y: selected.y, tile: t }, null, 2);
  const canBuy = t && t.kind === "plot" && t.plot && !t.plot.owner_company_id;
  const canBuild =
    t &&
    t.kind === "plot" &&
    t.plot &&
    t.plot.owner_company_id === state.player_company_id &&
    !t.plot.building;
  btnBuy.disabled = !canBuy;
  btnBuild.disabled = !canBuild;
}

function applyPayload(payload) {
  if (payload.state) state = payload.state;
  if (payload.ai) aiLog.textContent = payload.ai;
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
  selected = { x, y };
  refreshPanels();
  draw();
});

btnPause.addEventListener("click", async () => {
  const paused = !(state && state.paused);
  const res = await fetch("/api/pause", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paused }),
  });
  await res.json();
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
    body: JSON.stringify({ ...selected, building_type: "workshop" }),
  });
  const data = await res.json();
  if (!data.ok) alert(data.message);
});

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => applyPayload(JSON.parse(ev.data));
  ws.onclose = () => setTimeout(connect, 1000);
  // keepalive ping
  setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 15000);
}

resize();
connect();
