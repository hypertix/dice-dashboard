// DICE 벤치 대시보드 프론트엔드 — WS delta 수신 + 캔버스 스트립 차트 + 제어/업데이트.
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
let lastLcdTs = 0;

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
  const l = badges.lcd;
  setBadge("b-lcd", l.state, l.state === "connected" ? l.addr : "미연결", l.detail);
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
  // HV 토글은 실제 상태를 따라감 (사용자가 만지는 중이 아닐 때)
  const hvToggle = document.getElementById("hv-toggle");
  if (document.activeElement !== hvToggle) hvToggle.checked = !!lastStatus.hv;
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

canvas.addEventListener("mousemove", e => { hoverX = e.offsetX; });
canvas.addEventListener("mouseleave", () => { hoverX = null; tooltip.hidden = true; });

// 데이터가 없어도 축이 흐르도록 5 Hz 재그리기
setInterval(drawChart, 200);
window.addEventListener("resize", drawChart);

// ---- 출력 제어 패널 ----
const WAVES = [[0, "사인"], [1, "구형"], [2, "톱니"], [3, "펄스"], [4, "임의(SRAM)"]];
const ctlRows = document.getElementById("ctl-rows");
for (const s of SERIES) {
  const tr = document.createElement("tr");
  tr.innerHTML =
    `<td><label class="ctl-ch"><input type="checkbox" id="en-${s.key}" checked>` +
    `<span class="sw" style="background:${s.color}"></span>${s.name}</label></td>` +
    `<td><select id="wv-${s.key}">` +
    WAVES.map(([v, n]) => `<option value="${v}">${n}</option>`).join("") +
    `</select></td>` +
    `<td><input type="number" id="fq-${s.key}" value="1000" min="1" max="200000" step="any"></td>` +
    `<td><input type="number" id="am-${s.key}" value="5" min="0" max="62" step="any"></td>` +
    `<td><input type="number" id="ph-${s.key}" value="0" min="0" max="359.99" step="any"></td>`;
  ctlRows.appendChild(tr);
}
const ctlMsg = document.getElementById("ctl-msg");
function say(el, text, isErr) {
  el.textContent = text;
  el.style.color = isErr ? cssVar("--critical") : cssVar("--muted")
  if (text) setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 6000);
}

document.getElementById("hv-toggle").addEventListener("change", async e => {
  const r = await api("/api/cmd", { action: "hv", on: e.target.checked });
  if (!r.ok) say(ctlMsg, r.error || "HV 명령 실패", true);
});
document.getElementById("btn-estop").addEventListener("click", async () => {
  const r = await api("/api/cmd", { action: "estop" });
  say(ctlMsg, r.ok ? "ESTOP 전송됨" : (r.error || "ESTOP 실패"), !r.ok);
});
document.getElementById("btn-stop").addEventListener("click", async () => {
  const r = await api("/api/cmd", { action: "stop", mask: 0x0F });
  say(ctlMsg, r.ok ? "전체 정지 전송됨" : (r.error || "정지 실패"), !r.ok);
});
document.getElementById("btn-apply").addEventListener("click", async () => {
  let mask = 0;
  for (const s of SERIES) {
    if (!document.getElementById(`en-${s.key}`).checked) continue;
    mask |= 1 << s.key;
    const r = await api("/api/cmd", {
      action: "waveform", ch: s.key + 1,
      type: +document.getElementById(`wv-${s.key}`).value,
      freq_hz: +document.getElementById(`fq-${s.key}`).value,
      amp_ma: +document.getElementById(`am-${s.key}`).value,
      phase_deg: +document.getElementById(`ph-${s.key}`).value,
    });
    if (!r.ok) { say(ctlMsg, `${s.name} 설정 실패: ${r.error || ""}`, true); return; }
  }
  if (!mask) { say(ctlMsg, "켤 채널이 없습니다 (체크박스 확인)", true); return; }
  const r = await api("/api/cmd", { action: "start", mask });
  say(ctlMsg, r.ok ? "적용 + 시작 전송됨" : (r.error || "시작 실패"), !r.ok);
});

// ---- LCD 스크린샷 ----
function refreshLcd(badges, lcdTs) {
  const img = document.getElementById("lcd-img");
  const empty = document.getElementById("lcd-empty");
  const info = document.getElementById("lcd-info");
  if (badges.lcd.state === "connected" && lcdTs > 0) {
    if (lcdTs !== lastLcdTs) {
      lastLcdTs = lcdTs;
      img.src = "/api/lcd/screen.png?t=" + lcdTs;
    }
    img.hidden = false; empty.hidden = true;
    info.textContent = "(" + fmtTime(lcdTs) + " 캡처)";
  } else {
    img.hidden = true; empty.hidden = false;
    info.textContent = "";
  }
}

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
    renderBadges(m.badges, m.fw_info);
    refreshLcd(m.badges, m.lcd_png_ts || 0);
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
