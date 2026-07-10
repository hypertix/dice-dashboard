// DICE 벤치 대시보드 프론트엔드 — WS delta 수신 + 캔버스 스트립 차트.
"use strict";

const SERIES = [
  { key: 0, name: "CH1", color: cssVar("--series-1") },
  { key: 1, name: "CH2", color: cssVar("--series-2") },
  { key: 2, name: "CH3", color: cssVar("--series-3") },
  { key: 3, name: "CH4", color: cssVar("--series-4") },
];
const WINDOW_SEC = 60;          // 차트 표시 구간
const MAX_PTS = 1500;           // 10 Hz × 2.5분
const MAX_CONSOLE = 500;
const MAX_TIMELINE = 200;

const statusPts = [];           // {ts, meas[4], hv, strm, run, alarm}
let lastStatus = null;
let serverOffset = 0;           // server now - client now (표시 시각 보정)

function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toTimeString().slice(0, 8);
}
function fmtUA(v) {
  if (v == null) return "—";
  if (Math.abs(v) >= 1000) return (v / 1000).toFixed(2) + '<span class="unit">mA</span>';
  return Math.round(v) + '<span class="unit">µA</span>';
}
function fmtUAText(v) {
  return Math.abs(v) >= 1000 ? (v / 1000).toFixed(2) + " mA" : Math.round(v) + " µA";
}

// ---- 범례 ----
const legendEl = document.getElementById("legend");
for (const s of SERIES) {
  const it = document.createElement("span");
  it.className = "item";
  it.innerHTML = `<span class="sw" style="background:${s.color}"></span>${s.name}`;
  if (s.key === 0) it.title = "CH1 측정 경로 고장 — 펌웨어에서 0 고정";
  legendEl.appendChild(it);
}

// ---- 배지 ----
const BADGE_CLASS = {
  connected: "ok", open: "ok",
  busy: "warn",
  error: "err",
  absent: "", disconnected: "", unknown: "",
};
function setBadge(id, state, sub, title) {
  const el = document.getElementById(id);
  el.className = "badge " + (BADGE_CLASS[state] ?? "");
  el.querySelector(".sub").textContent = sub || "—";
  el.title = title || "";
}
function renderBadges(badges, fwInfo) {
  const j = badges.jlink;
  setBadge("b-jlink", j.state,
    j.state === "connected" ? "S/N " + j.serials.join(",") :
    j.state === "error" ? "오류" : "미연결", j.detail);
  const c = badges.console;
  setBadge("b-console", c.state,
    c.port ? c.port + (c.state === "busy" ? " 점유됨" : c.state === "open" ? "" : " 끊김") : "없음",
    c.detail);
  document.getElementById("console-port").textContent = c.port ? "(" + c.port + ")" : "";
  const d = badges.dice;
  setBadge("b-dice", d.state,
    d.port ? d.port + (d.state === "busy" ? " 점유됨" : d.state === "open" ? "" : " 끊김") : "없음",
    d.detail);
  setBadge("b-fw", fwInfo ? "connected" : "unknown",
    fwInfo ? "v" + fwInfo.fw + " (proto " + fwInfo.proto + ")" : "—");
}

// ---- 스탯 타일 ----
function renderTiles() {
  for (const s of SERIES) {
    document.querySelector(`#t-ch${s.key + 1} .t-val`).innerHTML =
      lastStatus ? fmtUA(lastStatus.meas[s.key]) : "—";
  }
  const hv = document.getElementById("c-hv");
  const strm = document.getElementById("c-strm");
  const run = document.getElementById("c-run");
  const alarm = document.getElementById("c-alarm");
  if (!lastStatus) { hv.className = strm.className = run.className = alarm.className = "chip"; return; }
  hv.className = "chip" + (lastStatus.hv ? " on" : "");
  strm.className = "chip" + (lastStatus.strm ? " on" : "");
  const bits = [0, 1, 2, 3].map(i => (lastStatus.run >> i) & 1);
  run.textContent = "RUN " + bits.map((b, i) => b ? (i + 1) : "-").join("");
  run.className = "chip" + (lastStatus.run ? " on" : "");
  alarm.textContent = lastStatus.alarm ? "ALARM 0x" + lastStatus.alarm.toString(16).toUpperCase() : "ALARM";
  alarm.className = "chip" + (lastStatus.alarm ? " alarm-on" : "");
}

// ---- 콘솔 ----
const consoleEl = document.getElementById("console");
function classifyLine(line) {
  if (/FAIL|ERROR|Malloc failed|stack overflow/i.test(line)) return "fail";
  if (/dropped|WARN/i.test(line)) return "warn";
  if (/PASS|OK/.test(line)) return "pass";
  return "";
}
function addConsoleLines(items) {
  if (!items.length) return;
  const nearBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 40;
  for (const it of items) {
    const div = document.createElement("span");
    div.className = "ln " + classifyLine(it.line);
    div.innerHTML = `<span class="ts">${fmtTime(it.ts)}</span>`;
    div.appendChild(document.createTextNode(it.line));
    consoleEl.appendChild(div);
  }
  while (consoleEl.childNodes.length > MAX_CONSOLE) consoleEl.removeChild(consoleEl.firstChild);
  if (nearBottom) consoleEl.scrollTop = consoleEl.scrollHeight;
}

// ---- 타임라인 ----
const timelineEl = document.getElementById("timeline");
function addEvents(items) {
  for (const it of items) {
    const li = document.createElement("li");
    li.className = it.level;
    li.innerHTML = `<span class="ts">${fmtTime(it.ts)}</span>` +
      `<span class="src">${it.source}</span>`;
    const msg = document.createElement("span");
    msg.className = "msg";
    msg.textContent = it.msg;
    li.appendChild(msg);
    timelineEl.prepend(li);
  }
  while (timelineEl.childNodes.length > MAX_TIMELINE) timelineEl.removeChild(timelineEl.lastChild);
}

// ---- STATUS 포인트 ----
function addStatusPts(items) {
  for (const it of items) {
    statusPts.push(it);
    lastStatus = it;
  }
  while (statusPts.length > MAX_PTS) statusPts.shift();
  if (items.length) {
    renderTiles();
    document.getElementById("chart-empty").hidden = true;
  }
}

// ---- 차트 (캔버스 스트립 차트) ----
const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");
const tooltip = document.getElementById("tooltip");
let hoverX = null;              // 캔버스 CSS 좌표
const PAD = { l: 56, r: 52, t: 8, b: 22 };

function niceCeil(v) {
  if (v <= 0) return 100;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * exp >= v) return m * exp;
  return 10 * exp;
}

function drawChart() {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr; canvas.height = h * dpr;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const now = Date.now() / 1000 + serverOffset;
  const t0 = now - WINDOW_SEC;
  const pts = statusPts.filter(p => p.ts >= t0);
  const plotW = w - PAD.l - PAD.r, plotH = h - PAD.t - PAD.b;

  // y 스케일: 표시 구간 최대값 기준 nice ceil (µA)
  let vmax = 100;
  for (const p of pts) for (const v of p.meas) if (v > vmax) vmax = v;
  vmax = niceCeil(vmax * 1.1);

  const xOf = ts => PAD.l + (ts - t0) / WINDOW_SEC * plotW;
  const yOf = v => PAD.t + plotH - (v / vmax) * plotH;

  // 그리드 + y 라벨
  ctx.strokeStyle = cssVar("--grid");
  ctx.fillStyle = cssVar("--muted");
  ctx.font = "11px system-ui";
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const v = vmax * i / 4, y = Math.round(yOf(v)) + 0.5;
    ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(w - PAD.r, y); ctx.stroke();
    ctx.fillText(v >= 1000 ? (v / 1000) + "k" : String(Math.round(v)), PAD.l - 8, y);
  }
  // x 라벨 (시각, 15초 간격)
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let s = 0; s <= WINDOW_SEC; s += 15) {
    const ts = t0 + s, x = xOf(ts);
    ctx.fillText(fmtTime(ts).slice(3), x, h - PAD.b + 6);
  }
  // 베이스라인
  ctx.strokeStyle = cssVar("--baseline");
  ctx.beginPath();
  ctx.moveTo(PAD.l, PAD.t + plotH + 0.5); ctx.lineTo(w - PAD.r, PAD.t + plotH + 0.5);
  ctx.stroke();

  // 시리즈 라인 (2px) + 우측 직접 라벨
  const labelYs = [];
  for (const s of SERIES) {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.beginPath();
    let started = false, lastY = null;
    for (const p of pts) {
      const x = xOf(p.ts), y = yOf(Math.max(0, p.meas[s.key]));
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      lastY = y;
    }
    if (started) ctx.stroke();
    if (lastY != null) {
      // 직접 라벨 (CVD 보조 인코딩) — 겹치면 아래로 밀기
      let ly = Math.min(Math.max(lastY, PAD.t + 6), PAD.t + plotH - 6);
      while (labelYs.some(v => Math.abs(v - ly) < 13)) ly += 13;
      labelYs.push(ly);
      ctx.fillStyle = s.color;
      ctx.fillRect(w - PAD.r + 6, ly - 4, 8, 8);
      ctx.fillStyle = cssVar("--ink-2");
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.fillText(s.name, w - PAD.r + 18, ly);
    }
  }

  // 호버 크로스헤어 + 툴팁
  if (hoverX != null && pts.length) {
    const tsAt = t0 + (hoverX - PAD.l) / plotW * WINDOW_SEC;
    let best = pts[0];
    for (const p of pts) if (Math.abs(p.ts - tsAt) < Math.abs(best.ts - tsAt)) best = p;
    const x = xOf(best.ts);
    if (x >= PAD.l && x <= w - PAD.r) {
      ctx.strokeStyle = cssVar("--baseline");
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x + 0.5, PAD.t); ctx.lineTo(x + 0.5, PAD.t + plotH); ctx.stroke();
      for (const s of SERIES) {
        ctx.fillStyle = s.color;
        ctx.beginPath();
        ctx.arc(x, yOf(Math.max(0, best.meas[s.key])), 3.5, 0, Math.PI * 2);
        ctx.fill();
      }
      tooltip.hidden = false;
      tooltip.innerHTML = `<div class="tt-time">${fmtTime(best.ts)}</div>` +
        SERIES.map(s => `<div class="row"><span class="sw" style="background:${s.color}"></span>` +
          `${s.name} ${fmtUAText(best.meas[s.key])}</div>`).join("");
      const wrap = canvas.parentElement.getBoundingClientRect();
      let tx = x + 14;
      if (tx + tooltip.offsetWidth > wrap.width - 4) tx = x - tooltip.offsetWidth - 14;
      tooltip.style.left = tx + "px";
      tooltip.style.top = Math.max(4, PAD.t + 4) + "px";
    }
  } else {
    tooltip.hidden = true;
  }
}

canvas.addEventListener("mousemove", e => {
  hoverX = e.offsetX;
});
canvas.addEventListener("mouseleave", () => { hoverX = null; tooltip.hidden = true; });

// 데이터가 없어도 축이 흐르도록 5 Hz 재그리기
setInterval(drawChart, 200);
window.addEventListener("resize", drawChart);

// ---- WebSocket ----
const wsBadge = document.getElementById("ws-badge");
function setWs(state, text) {
  wsBadge.className = "badge " + state;
  wsBadge.querySelector(".label").textContent = text;
}
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => setWs("ok", "실시간 연결됨");
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    serverOffset = m.now - Date.now() / 1000;
    if (m.t === "snap") {
      consoleEl.textContent = "";
      timelineEl.textContent = "";
      statusPts.length = 0;
      lastStatus = null;
    }
    renderBadges(m.badges, m.fw_info);
    addConsoleLines(m.console || []);
    addEvents(m.events || []);
    addStatusPts(m.status_pts || []);
  };
  ws.onclose = () => {
    setWs("err", "서버 끊김 — 재연결 중…");
    setTimeout(connect, 2000);
  };
  ws.onerror = () => ws.close();
}
connect();
