// DICE 벤치 대시보드 프론트엔드 — WS delta 수신 + 스트립 차트 + LCD 복제 제어 + 업데이트.
"use strict";

const SERIES = [
  { key: 0, name: "CH1", color: cssVar("--series-1") },
  { key: 1, name: "CH2", color: cssVar("--series-2") },
  { key: 2, name: "CH3", color: cssVar("--series-3") },
  { key: 3, name: "CH4", color: cssVar("--series-4") },
];
// LCD 복제 UI 채널 색 — 스트립 차트 팔레트(--series-*)와 통일
const LCH = SERIES.map(s => s.color);
const WINDOW_SEC = 60;
const MAX_PTS = 1500;
const MAX_CONSOLE = 500;
const MAX_TIMELINE = 200;

const statusPts = [];
let lastStatus = null;
let serverOffset = 0;

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
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await r.json(); } catch (e) { /* 비 JSON 응답 */ }
  return { ok: r.ok && data.ok !== false, ...data };
}

// ---- 범례 ----
const legendEl = document.getElementById("legend");
for (const s of SERIES) {
  const it = document.createElement("span");
  it.className = "item";
  it.innerHTML = `<span class="sw" style="background:${s.color}"></span>${s.name}`;
  if (s.key === 0) it.title = "CH1 측정 경로 고장 — 펌웨어에서 0 고정 (출력은 정상)";
  legendEl.appendChild(it);
}

// ---- 배지 ----
const BADGE_CLASS = {
  connected: "ok", open: "ok",
  busy: "warn", idle: "warn", no_pong: "warn",
  error: "err", fail: "err",
  absent: "", disconnected: "", unknown: "",
};
function setBadge(id, state, sub, title) {
  const el = document.getElementById(id);
  el.className = "badge " + (BADGE_CLASS[state] ?? "");
  el.querySelector(".sub").textContent = sub || "—";
  el.title = title || "";
}
function agoText(ts) {
  const sec = Math.max(0, Date.now() / 1000 + serverOffset - ts);
  if (sec < 5) return "방금";
  if (sec < 60) return Math.round(sec) + "초 전";
  if (sec < 3600) return Math.round(sec / 60) + "분 전";
  return Math.round(sec / 3600) + "시간 전";
}
function renderBadges(badges, fwInfo, selftest) {
  const j = badges.jlink;
  setBadge("b-jlink", j.state,
    j.state === "connected" ? "S/N " + j.serials.join(",") :
    j.state === "error" ? "오류" : "미연결", j.detail);
  const c = badges.console;
  setBadge("b-console", c.state,
    !c.port ? "없음" :
    c.state === "busy" ? c.port + " 점유됨" :
    c.state === "idle" ? c.port + " 무수신" :
    c.state === "open" ? c.port + (c.last_rx ? " · " + agoText(c.last_rx) : "") :
    c.port + " 끊김",
    c.detail);
  document.getElementById("console-port").textContent = c.port ? "(" + c.port + ")" : "";
  const d = badges.dice;
  setBadge("b-dice", d.state,
    d.port ? d.port + (d.state === "busy" ? " 점유됨" : d.state === "open" ? "" : " 끊김") : "없음",
    d.detail);
  const m = badges.mcu || { state: "unknown" };
  setBadge("b-mcu", m.state,
    m.state === "connected" ? "PING OK" :
    m.state === "no_pong" ? "응답 없음" : "—", m.detail);
  // 자가진단(SELFTEST) — LCD 상태 화면과 동일 소스. bit=1 정상.
  for (const [id, key, name] of [["b-dac", "dac", "AD9106"], ["b-adc", "adc", "ADS131"]]) {
    if (!selftest) setBadge(id, "unknown", "—", "자가진단 결과 없음 (DICE 연결 시 자동 실행)");
    else if (selftest.error) setBadge(id, "busy", "진단 실패", "SELFTEST 응답: " + selftest.error);
    else setBadge(id, selftest[key] ? "connected" : "fail",
                  selftest[key] ? "정상" : "FAIL",
                  name + " SPI 프로브 " + (selftest[key] ? "정상" : "실패"));
  }
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
  const hvToggle = document.getElementById("hv-toggle");
  if (document.activeElement !== hvToggle) hvToggle.checked = !!lastStatus.hv;
  renderLcdRunState();
}

// ---- 콘솔 ----
const consoleEl = document.getElementById("console");
function classifyLine(line) {
  if (/CFG_ERROR=0x\s*0\b/.test(line)) return "";        // 정상 진단 라인 오탐 방지
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
let hoverX = null;
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

  let vmax = 100;
  for (const p of pts) for (const v of p.meas) if (v > vmax) vmax = v;
  vmax = niceCeil(vmax * 1.1);

  const xOf = ts => PAD.l + (ts - t0) / WINDOW_SEC * plotW;
  const yOf = v => PAD.t + plotH - (v / vmax) * plotH;

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
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let s = 0; s <= WINDOW_SEC; s += 15) {
    const ts = t0 + s, x = xOf(ts);
    ctx.fillText(fmtTime(ts).slice(3), x, h - PAD.b + 6);
  }
  ctx.strokeStyle = cssVar("--baseline");
  ctx.beginPath();
  ctx.moveTo(PAD.l, PAD.t + plotH + 0.5); ctx.lineTo(w - PAD.r, PAD.t + plotH + 0.5);
  ctx.stroke();

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

canvas.addEventListener("mousemove", e => { hoverX = e.offsetX; });
canvas.addEventListener("mouseleave", () => { hoverX = null; tooltip.hidden = true; });
setInterval(drawChart, 200);
window.addEventListener("resize", () => { drawChart(); drawPreview(); });

// ==== 출력 제어 — dice_lcd 출력제어 화면 복제 ====
const WAVES = ["사인"];
// 채널별 설정 (LCD 기본값과 동일: 사인 1 kHz, 50 mA P-P, 0°, 연속)
const chSettings = [0, 1, 2, 3].map(() => ({ type: 0, freq: 1000, ampPP: 50, phase: 0, cycles: 0 }));
let selCh = 0;

const chtabsEl = document.getElementById("chtabs");
for (let i = 0; i < 4; i++) {
  const b = document.createElement("button");
  b.style.setProperty("--chc", LCH[i]);
  b.innerHTML = `CH${i + 1}<span class="rundot"></span>`;
  b.addEventListener("click", () => { saveInputs(); selCh = i; loadInputs(); });
  chtabsEl.appendChild(b);
}
const wavesEl = document.getElementById("waves");
WAVES.forEach((name, t) => {
  const b = document.createElement("button");
  b.textContent = name;
  b.addEventListener("click", () => {
    chSettings[selCh].type = t;
    renderLcdSel();
    drawPreview();
  });
  wavesEl.appendChild(b);
});

const inFreq = document.getElementById("p-freq");
const inAmp = document.getElementById("p-amp");
const inPhase = document.getElementById("p-phase");
const inCycles = document.getElementById("p-cycles");

function saveInputs() {
  const s = chSettings[selCh];
  s.freq = Math.min(200000, Math.max(1, +inFreq.value || 1));
  s.ampPP = Math.min(124, Math.max(0, +inAmp.value || 0));
  s.phase = ((+inPhase.value || 0) % 360 + 360) % 360;
  s.cycles = Math.max(0, Math.round(+inCycles.value || 0));
}
function loadInputs() {
  const s = chSettings[selCh];
  inFreq.value = s.freq;
  inAmp.value = s.ampPP;
  inPhase.value = s.phase;
  inCycles.value = s.cycles;
  renderLcdSel();
  renderLcdRunState();
  drawPreview();
}
// 값 변경 즉시 적용 — LCD(dicebackend pushWaveform)와 동일 동작.
// 스테퍼 연타 시 타임라인/시리얼 폭주를 막기 위해 250ms 디바운스로 모아 보낸다.
const pendingPush = new Set();
let pushTimer = null;
function schedulePush(chs) {
  chs.forEach(i => pendingPush.add(i));
  clearTimeout(pushTimer);
  pushTimer = setTimeout(async () => {
    const list = [...pendingPush];
    pendingPush.clear();
    for (const i of list) {
      const r = await sendWaveform(i);
      if (!r.ok) { say(ctlMsg, r.error || `CH${i + 1} 설정 적용 실패`, true); break; }
    }
  }, 250);
}
// 사인 주파수는 AD9106 DDS 튜닝 워드 공유로 4채널 공통 — LCD 와 동일하게 동기화
function syncFreqAll() {
  const f = chSettings[selCh].freq;
  chSettings.forEach(c => { c.freq = f; });
  schedulePush([0, 1, 2, 3]);
}
for (const el of [inFreq, inAmp, inPhase, inCycles]) {
  el.addEventListener("change", () => {
    const before = { ...chSettings[selCh] };
    saveInputs();
    const s = chSettings[selCh];
    if (s.freq !== before.freq) syncFreqAll();
    else if (s.ampPP !== before.ampPP || s.phase !== before.phase || s.cycles !== before.cycles)
      schedulePush([selCh]);
    loadInputs();
  });
}
// +/- 스테퍼 (주파수 ±100 Hz, 진폭 ±1 mA, 위상 ±15°, 버스트 ±1)
const STEP = { freq: 100, amp: 1, phase: 15, cycles: 1 };
document.querySelectorAll(".lcdui-params .step button").forEach(b => {
  b.addEventListener("click", () => {
    saveInputs();
    const s = chSettings[selCh], d = +b.dataset.d;
    if (b.dataset.p === "freq") {
      s.freq = Math.min(200000, Math.max(1, s.freq + d * STEP.freq));
      syncFreqAll();
    }
    if (b.dataset.p === "amp") { s.ampPP = Math.min(124, Math.max(0, s.ampPP + d * STEP.amp)); schedulePush([selCh]); }
    if (b.dataset.p === "phase") { s.phase = ((s.phase + d * STEP.phase) % 360 + 360) % 360; schedulePush([selCh]); }
    if (b.dataset.p === "cycles") { s.cycles = Math.max(0, s.cycles + d); schedulePush([selCh]); }
    loadInputs();
  });
});

function renderLcdSel() {
  [...chtabsEl.children].forEach((b, i) => b.classList.toggle("sel", i === selCh));
  [...wavesEl.children].forEach((b, t) => b.classList.toggle("sel", t === chSettings[selCh].type));
}
function renderLcdRunState() {
  const run = lastStatus ? lastStatus.run : 0;
  [...chtabsEl.children].forEach((b, i) => b.classList.toggle("running", !!(run >> i & 1)));
  const btn = document.getElementById("btn-ch-run");
  const running = !!(run >> selCh & 1);
  btn.textContent = running ? `■ CH${selCh + 1} 출력 정지` : `▶ CH${selCh + 1} 출력 시작`;
  btn.classList.toggle("running", running);
  const rms = document.getElementById("rms-sel");
  const v = lastStatus ? lastStatus.meas[selCh] : 0;
  rms.textContent = (v / 1000).toFixed(2) + " mA";
  rms.style.color = LCH[selCh];
}

// 파형 미리보기 (10 ms 창, 설정 파형 합성 — LCD 스코프 영역과 동일 배치)
const pvCanvas = document.getElementById("preview");
function drawPreview() {
  const dpr = window.devicePixelRatio || 1;
  const w = pvCanvas.clientWidth, h = pvCanvas.clientHeight;
  if (!w || !h) return;
  if (pvCanvas.width !== w * dpr || pvCanvas.height !== h * dpr) {
    pvCanvas.width = w * dpr; pvCanvas.height = h * dpr;
  }
  const c = pvCanvas.getContext("2d");
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, w, h);
  const s = chSettings[selCh];
  const ampPk = s.ampPP / 2;
  const yFull = Math.max(1, ampPk * 1.25);
  // 그리드
  c.strokeStyle = "#1d2946";
  c.lineWidth = 1;
  for (let i = 1; i < 8; i++) {
    const x = Math.round(w * i / 8) + 0.5;
    c.beginPath(); c.moveTo(x, 0); c.lineTo(x, h); c.stroke();
  }
  for (let i = 1; i < 4; i++) {
    const y = Math.round(h * i / 4) + 0.5;
    c.beginPath(); c.moveTo(0, y); c.lineTo(w, y); c.stroke();
  }
  c.fillStyle = "#5a647c";
  c.font = "10px system-ui";
  c.textAlign = "left"; c.textBaseline = "top";
  c.fillText(`+${yFull.toFixed(0)} mA`, 5, 4);
  c.textBaseline = "bottom";
  c.fillText(`−${yFull.toFixed(0)} mA`, 5, h - 4);
  c.textAlign = "right";
  c.fillText("10 ms", w - 6, h - 4);
  c.textBaseline = "top";
  c.fillText("설정 미리보기 (실측 아님)", w - 6, 4);
  // 파형
  const mid = h / 2, T = 0.01;
  const periods = s.freq * T;
  c.strokeStyle = LCH[selCh];
  c.lineWidth = 2;
  if (s.ampPP <= 0) {
    c.beginPath(); c.moveTo(0, mid); c.lineTo(w, mid); c.stroke();
  } else if (periods > w / 6) {
    // 창 안에 주기가 너무 많으면 envelope 밴드로 표시
    const yA = mid - (ampPk / yFull) * (h / 2);
    const yB = mid + (ampPk / yFull) * (h / 2);
    c.globalAlpha = 0.25;
    c.fillStyle = LCH[selCh];
    c.fillRect(0, yA, w, yB - yA);
    c.globalAlpha = 1;
    c.beginPath(); c.moveTo(0, yA); c.lineTo(w, yA); c.stroke();
    c.beginPath(); c.moveTo(0, yB); c.lineTo(w, yB); c.stroke();
  } else {
    c.beginPath();
    for (let x = 0; x <= w; x++) {
      const t = x / w * T;
      const ph = s.freq * t + s.phase / 360;
      const v = Math.sin(2 * Math.PI * ph);
      const y = mid - (v * ampPk / yFull) * (h / 2);
      if (x === 0) c.moveTo(x, y); else c.lineTo(x, y);
    }
    c.stroke();
  }
}

// ---- 제어 명령 ----
const ctlMsg = document.getElementById("ctl-msg");
function say(el, text, isErr) {
  el.textContent = text;
  el.style.color = isErr ? "#ef5350" : "";
  if (text) setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 6000);
}
async function sendWaveform(i) {
  const s = chSettings[i];
  return api("/api/cmd", {
    action: "waveform", ch: i + 1, type: s.type,
    freq_hz: s.freq, amp_ma: s.ampPP / 2,            // UI 는 P-P, 프로토콜은 peak
    phase_deg: s.phase, cycles: s.cycles,
  });
}
document.getElementById("hv-toggle").addEventListener("change", async e => {
  const r = await api("/api/cmd", { action: "hv", on: e.target.checked });
  if (!r.ok) say(ctlMsg, r.error || "HV 명령 실패", true);
});
document.getElementById("btn-estop").addEventListener("click", async () => {
  const r = await api("/api/cmd", { action: "estop" });
  say(ctlMsg, r.ok ? "비상정지 전송됨" : (r.error || "비상정지 실패"), !r.ok);
});
document.getElementById("btn-ch-run").addEventListener("click", async () => {
  saveInputs();
  const running = lastStatus && (lastStatus.run >> selCh & 1);
  if (running) {
    const r = await api("/api/cmd", { action: "stop", mask: 1 << selCh });
    say(ctlMsg, r.ok ? `CH${selCh + 1} 정지` : (r.error || "정지 실패"), !r.ok);
  } else {
    const r1 = await sendWaveform(selCh);
    if (!r1.ok) { say(ctlMsg, r1.error || "설정 실패", true); return; }
    const r2 = await api("/api/cmd", { action: "start", mask: 1 << selCh });
    say(ctlMsg, r2.ok ? `CH${selCh + 1} 시작` : (r2.error || "시작 실패"), !r2.ok);
  }
});
document.getElementById("btn-all-start").addEventListener("click", async () => {
  saveInputs();
  for (let i = 0; i < 4; i++) {
    const r = await sendWaveform(i);
    if (!r.ok) { say(ctlMsg, `CH${i + 1} 설정 실패: ${r.error || ""}`, true); return; }
  }
  const r = await api("/api/cmd", { action: "start", mask: 0x0F });
  say(ctlMsg, r.ok ? "전체 시작" : (r.error || "시작 실패"), !r.ok);
});
document.getElementById("btn-all-stop").addEventListener("click", async () => {
  const r = await api("/api/cmd", { action: "stop", mask: 0x0F });
  say(ctlMsg, r.ok ? "전체 정지" : (r.error || "정지 실패"), !r.ok);
});
loadInputs();

// ---- 펌웨어 업데이트 (dice-ota) ----
let fwRelease = null;
const fwInfoEl = document.getElementById("fw-info");
const fwApplyBtn = document.getElementById("btn-fw-apply");
const fwMsg = document.getElementById("fw-msg");
document.getElementById("btn-fw-check").addEventListener("click", async () => {
  fwInfoEl.textContent = "조회 중…";
  const r = await fetch("/api/fw/check").then(x => x.json());
  if (r.error) {
    fwRelease = null; fwApplyBtn.disabled = true;
    fwInfoEl.textContent = r.error;
    return;
  }
  fwRelease = r;
  const a = r.assets[0];
  fwInfoEl.innerHTML =
    `최신 릴리스: <b>${r.tag}</b> (${(r.published_at || "").slice(0, 10)})<br>` +
    `파일: ${a.name} (${Math.round(a.size / 1024)} KB)` +
    (r.notes ? `<br><span class="muted">${r.notes}</span>` : "");
  fwApplyBtn.disabled = false;
});
fwApplyBtn.addEventListener("click", async () => {
  if (!fwRelease) return;
  const a = fwRelease.assets[0];
  if (!confirm(`펌웨어 ${fwRelease.tag} (${a.name})를 J-Link 로 플래시합니다.\n` +
               `보드가 리셋됩니다. 진행할까요?`)) return;
  const r = await api("/api/fw/apply",
    { tag: fwRelease.tag, asset_name: a.name, asset_url: a.url });
  say(fwMsg, r.ok ? "업데이트 시작 — 타임라인에서 진행 확인" : (r.error || "시작 실패"), !r.ok);
});
function renderFwUpdate(fu) {
  if (!fu) return;
  if (fu.phase === "idle") {
    if (fwApplyBtn.dataset.busy) { fwApplyBtn.dataset.busy = ""; fwApplyBtn.disabled = !fwRelease; }
  } else {
    fwApplyBtn.dataset.busy = "1"; fwApplyBtn.disabled = true;
    say(fwMsg, fu.detail, false);
  }
}

// ---- 대시보드 자기 업데이트 ----
const updMsg = document.getElementById("upd-msg");
document.getElementById("btn-upd-check").addEventListener("click", async () => {
  updMsg.textContent = "확인 중…";
  const r = await fetch("/api/update/check").then(x => x.json());
  if (r.error) { updMsg.textContent = r.error; return; }
  if (r.behind === 0) { updMsg.textContent = "최신 버전입니다 (" + r.current + ")"; return; }
  updMsg.textContent = `${r.behind}개 업데이트 있음`;
  if (confirm(`대시보드 업데이트 ${r.behind}건:\n${(r.log || []).join("\n")}\n\n` +
              `지금 적용하고 재시작할까요?`)) {
    const a = await api("/api/update/apply");
    updMsg.textContent = a.ok ? "적용됨 — 재시작 중… (자동 재연결)" : (a.error || "실패");
  }
});

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
      if (m.version) document.getElementById("dash-ver").textContent = m.version;
    }
    renderBadges(m.badges, m.fw_info, m.selftest);
    renderFwUpdate(m.fw_update);
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
