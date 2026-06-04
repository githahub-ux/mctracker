from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


HOST = "0.0.0.0"
PORT = 8000
DEFAULT_MC_HOST = "donutsmp.net"
DEFAULT_MC_PORT = 25565
POLL_INTERVAL_SECONDS = 5 * 60
PING_TIMEOUT_SECONDS = 15
HISTORY_FILE = Path(__file__).with_name("player_history.json")
MAX_HISTORY_POINTS_PER_SERVER = 7 * 24 * 12
TIMESTAMP_FORMAT = "%Y:%d:%m %H:%M:%S"

if POLL_INTERVAL_SECONDS % 60 == 0:
    poll_minutes = POLL_INTERVAL_SECONDS // 60
    POLL_INTERVAL_LABEL = f"{poll_minutes} minute{'s' if poll_minutes != 1 else ''}"
else:
    POLL_INTERVAL_LABEL = f"{POLL_INTERVAL_SECONDS} second{'s' if POLL_INTERVAL_SECONDS != 1 else ''}"

history_lock = threading.Lock()


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Minecraft Player Tracker</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101418;
      --panel: #171d22;
      --panel-2: #20272d;
      --line: #2d3840;
      --text: #edf4ef;
      --muted: #a5b1aa;
      --green: #63d471;
      --green-soft: rgba(99, 212, 113, 0.18);
      --gold: #f0c05a;
      --red: #ff6b6b;
      --stone: #8d9aa0;
      --focus: #7cc7ff;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background:
        linear-gradient(180deg, rgba(35, 52, 40, 0.28), transparent 280px),
        var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }

    button,
    input {
      font: inherit;
    }

    .shell {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 32px;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    .block-mark {
      width: 42px;
      height: 42px;
      border-radius: 8px;
      background:
        linear-gradient(135deg, #6ebd58 0 50%, #4b8e3e 50%),
        #5da64b;
      box-shadow: inset 0 -7px 0 rgba(0, 0, 0, 0.18);
      flex: 0 0 auto;
    }

    h1 {
      margin: 0;
      font-size: clamp(1.35rem, 2vw, 2.05rem);
      line-height: 1.1;
      font-weight: 800;
    }

    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 34px;
      padding: 7px 11px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      background: rgba(23, 29, 34, 0.78);
      white-space: nowrap;
    }

    .dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--stone);
      box-shadow: 0 0 0 4px rgba(141, 154, 160, 0.15);
    }

    .dot.online {
      background: var(--green);
      box-shadow: 0 0 0 4px rgba(99, 212, 113, 0.16);
    }

    .dot.offline {
      background: var(--red);
      box-shadow: 0 0 0 4px rgba(255, 107, 107, 0.16);
    }

    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(23, 29, 34, 0.94);
      box-shadow: 0 18px 48px rgba(0, 0, 0, 0.24);
    }

    .controls {
      display: grid;
      grid-template-columns: minmax(210px, 1fr) 118px auto auto;
      gap: 10px;
      align-items: end;
      padding: 14px;
      margin-bottom: 14px;
    }

    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
    }

    input {
      width: 100%;
      min-height: 42px;
      border: 1px solid #3b484f;
      border-radius: 8px;
      padding: 0 12px;
      color: var(--text);
      background: #10161a;
      outline: none;
    }

    input:focus {
      border-color: var(--focus);
      box-shadow: 0 0 0 3px rgba(124, 199, 255, 0.18);
    }

    .button-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    button {
      min-height: 42px;
      border: 1px solid transparent;
      border-radius: 8px;
      padding: 0 14px;
      color: #0d1510;
      background: var(--green);
      font-weight: 800;
      cursor: pointer;
    }

    button.secondary {
      color: var(--text);
      border-color: #3a464d;
      background: #20282e;
    }

    button:hover {
      filter: brightness(1.06);
    }

    button:active {
      transform: translateY(1px);
    }

    .dashboard {
      display: grid;
      grid-template-columns: 1fr 320px;
      gap: 14px;
    }

    .chart-panel {
      min-width: 0;
      padding: 16px;
    }

    .chart-head {
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }

    h2 {
      margin: 0;
      font-size: 1rem;
      line-height: 1.25;
    }

    .subtle {
      color: var(--muted);
      font-size: 0.86rem;
      margin-top: 4px;
    }

    .chart-wrap {
      position: relative;
      width: 100%;
      height: 430px;
      overflow: hidden;
      border-radius: 8px;
      border: 1px solid #2e3940;
      background:
        linear-gradient(180deg, rgba(99, 212, 113, 0.06), rgba(99, 212, 113, 0)),
        #11181c;
    }

    canvas {
      display: block;
      width: 100%;
      height: 100%;
    }

    .empty-state {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      text-align: center;
      color: var(--muted);
      padding: 18px;
      pointer-events: none;
    }

    .chart-tooltip {
      position: absolute;
      z-index: 2;
      min-width: 138px;
      max-width: 220px;
      padding: 8px 10px;
      border: 1px solid #3c4a51;
      border-radius: 8px;
      color: var(--text);
      background: rgba(13, 19, 22, 0.94);
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.28);
      font-size: 0.82rem;
      line-height: 1.35;
      pointer-events: none;
      transform: translate(-50%, calc(-100% - 12px));
      display: none;
    }

    .chart-tooltip strong {
      display: block;
      font-size: 1rem;
      line-height: 1.2;
      margin-bottom: 2px;
    }

    .side {
      display: grid;
      gap: 14px;
      align-content: start;
    }

    .stat-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .stat {
      padding: 14px;
      min-height: 104px;
    }

    .stat .label {
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 800;
      text-transform: uppercase;
    }

    .value {
      margin-top: 8px;
      font-size: clamp(1.45rem, 3vw, 2.2rem);
      font-weight: 900;
      line-height: 1;
      overflow-wrap: anywhere;
    }

    .value.small {
      font-size: 1.18rem;
      line-height: 1.15;
    }

    .meta-panel {
      padding: 14px;
    }

    .meta-list {
      display: grid;
      gap: 11px;
      margin-top: 12px;
    }

    .meta-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-top: 1px solid rgba(255, 255, 255, 0.06);
      padding-top: 10px;
      color: var(--muted);
      font-size: 0.9rem;
    }

    .meta-row strong {
      color: var(--text);
      font-weight: 800;
      text-align: right;
      overflow-wrap: anywhere;
    }

    .message {
      min-height: 22px;
      color: var(--muted);
      font-size: 0.9rem;
    }

    .message.error {
      color: #ffb2b2;
    }

    @media (max-width: 900px) {
      .topbar {
        align-items: start;
        flex-direction: column;
      }

      .controls {
        grid-template-columns: 1fr 112px;
      }

      .button-row {
        grid-column: 1 / -1;
      }

      .dashboard {
        grid-template-columns: 1fr;
      }

      .chart-wrap {
        height: 360px;
      }
    }

    @media (max-width: 560px) {
      .shell {
        width: min(100% - 20px, 1180px);
        padding-top: 14px;
      }

      .controls,
      .stat-grid {
        grid-template-columns: 1fr;
      }

      .chart-head {
        flex-direction: column;
      }

      .chart-wrap {
        height: 310px;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="block-mark" aria-hidden="true"></div>
        <div>
          <h1>Minecraft Player Tracker</h1>
          <div class="subtle" id="activeServer">No server selected</div>
        </div>
      </div>
      <div class="status-pill" aria-live="polite">
        <span class="dot" id="statusDot"></span>
        <span id="statusText">Idle</span>
      </div>
    </header>

    <form class="panel controls" id="serverForm">
      <label>
        Server address
        <input id="hostInput" name="host" autocomplete="off" spellcheck="false" placeholder="example.com">
      </label>
      <label>
        Port
        <input id="portInput" name="port" inputmode="numeric" pattern="[0-9]*">
      </label>
      <div class="button-row">
        <button type="submit" id="trackButton">Track</button>
        <button type="button" class="secondary" id="refreshButton">Refresh</button>
      </div>
      <div class="message" id="message" aria-live="polite"></div>
    </form>

    <section class="dashboard">
      <section class="panel chart-panel">
        <div class="chart-head">
          <div>
            <h2>Players online</h2>
            <div class="subtle" id="rangeText">Waiting for data</div>
          </div>
        <div class="subtle" id="nextText">Every __POLL_INTERVAL_LABEL__</div>
        </div>
        <div class="chart-wrap">
          <canvas id="chartCanvas" aria-label="Player count graph"></canvas>
          <div class="chart-tooltip" id="chartTooltip"></div>
          <div class="empty-state" id="emptyState">Start tracking to collect player counts.</div>
        </div>
      </section>

      <aside class="side">
        <section class="stat-grid">
          <div class="panel stat">
            <div class="label">Online</div>
            <div class="value" id="onlineValue">--</div>
          </div>
          <div class="panel stat">
            <div class="label">Capacity</div>
            <div class="value" id="maxValue">--</div>
          </div>
          <div class="panel stat">
            <div class="label">Peak</div>
            <div class="value small" id="peakValue">--</div>
          </div>
          <div class="panel stat">
            <div class="label">Samples</div>
            <div class="value small" id="samplesValue">0</div>
          </div>
        </section>

        <section class="panel meta-panel">
          <h2>Server</h2>
          <div class="meta-list">
            <div class="meta-row"><span>Last check</span><strong id="lastValue">--</strong></div>
          </div>
        </section>
      </aside>
    </section>
  </main>

  <script>
    const POLL_INTERVAL_MS = __POLL_INTERVAL_MS__;
    const POLL_INTERVAL_LABEL = "__POLL_INTERVAL_LABEL__";

    const els = {
      form: document.getElementById("serverForm"),
      host: document.getElementById("hostInput"),
      port: document.getElementById("portInput"),
      track: document.getElementById("trackButton"),
      refresh: document.getElementById("refreshButton"),
      message: document.getElementById("message"),
      activeServer: document.getElementById("activeServer"),
      statusDot: document.getElementById("statusDot"),
      statusText: document.getElementById("statusText"),
      online: document.getElementById("onlineValue"),
      max: document.getElementById("maxValue"),
      samples: document.getElementById("samplesValue"),
      last: document.getElementById("lastValue"),
      peak: document.getElementById("peakValue"),
      range: document.getElementById("rangeText"),
      next: document.getElementById("nextText"),
      canvas: document.getElementById("chartCanvas"),
      tooltip: document.getElementById("chartTooltip"),
      empty: document.getElementById("emptyState")
    };

    const CONFIG_DEFAULT_HOST = __DEFAULT_MC_HOST_JSON__;
    const CONFIG_DEFAULT_PORT = __DEFAULT_MC_PORT__;
    const configuredDefaultKey = `${CONFIG_DEFAULT_HOST}:${CONFIG_DEFAULT_PORT}`;

    if (localStorage.getItem("mcTrackerConfiguredDefault") !== configuredDefaultKey) {
      localStorage.setItem("mcTrackerHost", CONFIG_DEFAULT_HOST);
      localStorage.setItem("mcTrackerPort", String(CONFIG_DEFAULT_PORT));
      localStorage.setItem("mcTrackerConfiguredDefault", configuredDefaultKey);
    }

    let history = [];
    let currentServer = {
      host: localStorage.getItem("mcTrackerHost") || CONFIG_DEFAULT_HOST,
      port: Number(localStorage.getItem("mcTrackerPort") || CONFIG_DEFAULT_PORT)
    };
    let pollTimer = null;
    let countdownTimer = null;
    let nextPollAt = 0;
    let loading = false;
    let chartPoints = [];

    els.host.value = currentServer.host;
    els.port.value = String(currentServer.port);

    function serverLabel(server = currentServer) {
      if (!server.host) return "No server selected";
      return `${server.host}:${server.port}`;
    }

    function setMessage(text, isError = false) {
      els.message.textContent = text;
      els.message.classList.toggle("error", isError);
    }

    function setStatus(kind, text) {
      els.statusDot.className = `dot ${kind || ""}`.trim();
      els.statusText.textContent = text;
    }

    function pad(value) {
      return String(value).padStart(2, "0");
    }

    function timestampToMs(timestamp) {
      if (!timestamp) return NaN;

      if (typeof timestamp === "number" && Number.isFinite(timestamp)) {
        return timestamp * 1000;
      }

      if (typeof timestamp === "string") {
        const match = timestamp.match(/^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);
        if (match) {
          const [, year, day, month, hour, minute, second] = match.map(Number);
          return new Date(year, month - 1, day, hour, minute, second).getTime();
        }

        const parsed = Date.parse(timestamp);
        if (Number.isFinite(parsed)) return parsed;
      }

      return NaN;
    }

    function formatStoredTimeFromMs(timeMs) {
      if (!Number.isFinite(timeMs)) return "--";
      const date = new Date(timeMs);
      return `${date.getFullYear()}:${pad(date.getDate())}:${pad(date.getMonth() + 1)} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
    }

    function formatTime(timestamp) {
      if (!timestamp) return "--";
      if (typeof timestamp === "string") return timestamp;
      return formatStoredTimeFromMs(timestampToMs(timestamp));
    }

    function compactTime(timestamp) {
      const timeMs = timestampToMs(timestamp);
      if (!Number.isFinite(timeMs)) return "--";
      const date = new Date(timeMs);
      return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    function updateCountdown() {
      if (!nextPollAt) {
        els.next.textContent = `Every ${POLL_INTERVAL_LABEL}`;
        return;
      }

      const remaining = Math.max(0, nextPollAt - Date.now());
      const minutes = Math.floor(remaining / 60000);
      const seconds = Math.floor((remaining % 60000) / 1000);
      els.next.textContent = `Next check ${minutes}:${String(seconds).padStart(2, "0")}`;
    }

    function scheduleNextPoll() {
      clearTimeout(pollTimer);
      clearInterval(countdownTimer);
      nextPollAt = Date.now() + POLL_INTERVAL_MS;
      updateCountdown();
      countdownTimer = setInterval(updateCountdown, 1000);
      pollTimer = setTimeout(() => refreshStatus(false), POLL_INTERVAL_MS);
    }

    function readServerFromForm() {
      let host = els.host.value.trim();
      let portText = els.port.value || "25565";

      if (host.includes(":") && !host.startsWith("[") && host.split(":").length === 2) {
        const parts = host.split(":");
        host = parts[0];
        portText = parts[1] || portText;
        els.host.value = host;
        els.port.value = portText;
      }

      const port = Number(portText);

      if (!host) {
        throw new Error("Enter a server address.");
      }
      if (!Number.isInteger(port) || port < 1 || port > 65535) {
        throw new Error("Use a port from 1 to 65535.");
      }

      return { host, port };
    }

    async function fetchJson(url) {
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok || data.error) {
        throw new Error(data.error || `Request failed with ${response.status}`);
      }
      return data;
    }

    async function loadHistory() {
      const query = new URLSearchParams({
        host: currentServer.host,
        port: String(currentServer.port)
      });
      const data = await fetchJson(`/api/history?${query.toString()}`);
      history = data.history || [];
      render();
    }

    async function refreshStatus(manual) {
      if (loading) return;
      loading = true;
      els.refresh.disabled = true;
      els.track.disabled = true;
      setStatus("", "Checking");
      if (manual) setMessage("Checking server...");

      try {
        const query = new URLSearchParams({
          host: currentServer.host,
          port: String(currentServer.port)
        });
        const data = await fetchJson(`/api/status?${query.toString()}`);
        history = data.history || [];
        render(data.sample);
        setStatus(data.sample.online ? "online" : "offline", data.sample.online ? "Online" : "Offline");
        setMessage(data.sample.online ? "Latest sample saved." : (data.sample.error || "Server did not respond."), !data.sample.online);
        scheduleNextPoll();
      } catch (error) {
        setStatus("offline", "Error");
        setMessage(error.message, true);
        scheduleNextPoll();
      } finally {
        loading = false;
        els.refresh.disabled = false;
        els.track.disabled = false;
      }
    }

    function render(sample) {
      const latest = sample || history[history.length - 1];
      els.activeServer.textContent = serverLabel();
      els.samples.textContent = String(history.length);
      els.empty.style.display = history.length ? "none" : "grid";

      if (latest) {
        els.online.textContent = latest.players_online ?? "--";
        els.max.textContent = latest.players_max ?? "--";
        els.last.textContent = formatTime(latest.timestamp);
        setStatus(latest.online ? "online" : "offline", latest.online ? "Online" : "Offline");
      } else {
        els.online.textContent = "--";
        els.max.textContent = "--";
        els.last.textContent = "--";
      }

      const onlinePoints = history.filter((point) => point.online && Number.isFinite(point.players_online));
      const peak = onlinePoints.reduce((best, point) => Math.max(best, point.players_online), 0);
      els.peak.textContent = onlinePoints.length ? String(peak) : "--";

      if (history.length >= 2) {
        els.range.textContent = `${formatTime(history[0].timestamp)} to ${formatTime(history[history.length - 1].timestamp)}`;
      } else if (history.length === 1) {
        els.range.textContent = "1 sample collected";
      } else {
        els.range.textContent = "Waiting for data";
      }

      drawChart();
    }

    function drawChart() {
      const canvas = els.canvas;
      const ctx = canvas.getContext("2d");
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const timedHistory = history
        .map((point) => ({ ...point, timeMs: timestampToMs(point.timestamp) }))
        .filter((point) => Number.isFinite(point.timeMs));

      chartPoints = [];
      els.tooltip.style.display = "none";

      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, rect.width, rect.height);

      const pad = { top: 24, right: 24, bottom: 44, left: 48 };
      const width = rect.width - pad.left - pad.right;
      const height = rect.height - pad.top - pad.bottom;

      ctx.strokeStyle = "#2d3840";
      ctx.lineWidth = 1;
      ctx.fillStyle = "#a5b1aa";
      ctx.font = "12px Inter, system-ui, sans-serif";

      const onlineValues = timedHistory.map((point) => Number(point.players_online || 0));
      const maxValues = timedHistory.map((point) => Number(point.players_max || 0));
      const yMax = Math.max(10, ...onlineValues, ...maxValues);
      const niceMax = Math.ceil(yMax / 5) * 5;

      for (let i = 0; i <= 5; i++) {
        const y = pad.top + (height * i) / 5;
        const value = Math.round(niceMax - (niceMax * i) / 5);
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + width, y);
        ctx.stroke();
        ctx.fillText(String(value), 12, y + 4);
      }

      ctx.beginPath();
      ctx.moveTo(pad.left, pad.top);
      ctx.lineTo(pad.left, pad.top + height);
      ctx.lineTo(pad.left + width, pad.top + height);
      ctx.stroke();

      if (!timedHistory.length) return;

      const minTime = timedHistory[0].timeMs;
      const maxTime = timedHistory[timedHistory.length - 1].timeMs;
      const timeSpan = Math.max(1, maxTime - minTime);

      function xFor(point) {
        return pad.left + ((point.timeMs - minTime) / timeSpan) * width;
      }

      function yFor(value) {
        return pad.top + height - (Number(value || 0) / niceMax) * height;
      }

      const labelCount = Math.min(4, timedHistory.length);
      for (let i = 0; i < labelCount; i++) {
        const index = Math.round((i * (timedHistory.length - 1)) / Math.max(1, labelCount - 1));
        const point = timedHistory[index];
        const x = xFor(point);
        ctx.fillStyle = "#a5b1aa";
        ctx.fillText(compactTime(point.timestamp), Math.max(8, x - 22), pad.top + height + 28);
      }

      const capacityPoints = timedHistory.filter((point) => point.online && Number.isFinite(point.players_max));
      if (capacityPoints.length) {
        ctx.beginPath();
        capacityPoints.forEach((point, index) => {
          const x = xFor(point);
          const y = yFor(point.players_max);
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.strokeStyle = "rgba(240, 192, 90, 0.72)";
        ctx.setLineDash([6, 6]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      const linePoints = timedHistory.filter((point) => point.online && Number.isFinite(point.players_online));
      if (!linePoints.length) return;

      ctx.beginPath();
      linePoints.forEach((point, index) => {
        const x = xFor(point);
        const y = yFor(point.players_online);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = "#63d471";
      ctx.lineWidth = 3;
      ctx.stroke();

      ctx.lineTo(xFor(linePoints[linePoints.length - 1]), pad.top + height);
      ctx.lineTo(xFor(linePoints[0]), pad.top + height);
      ctx.closePath();
      const fill = ctx.createLinearGradient(0, pad.top, 0, pad.top + height);
      fill.addColorStop(0, "rgba(99, 212, 113, 0.22)");
      fill.addColorStop(1, "rgba(99, 212, 113, 0.01)");
      ctx.fillStyle = fill;
      ctx.fill();

      chartPoints = linePoints.map((point) => {
        const x = xFor(point);
        const y = yFor(point.players_online);

        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = "#edf4ef";
        ctx.fill();
        ctx.strokeStyle = "#63d471";
        ctx.lineWidth = 2;
        ctx.stroke();

        return { x, y, point };
      });
    }

    function hideChartTooltip() {
      els.tooltip.style.display = "none";
    }

    function updateChartTooltip(event) {
      if (!chartPoints.length) {
        hideChartTooltip();
        return;
      }

      const rect = els.canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;
      let nearest = null;
      let nearestDistance = Infinity;

      chartPoints.forEach((candidate) => {
        const distance = Math.hypot(candidate.x - mouseX, candidate.y - mouseY);
        if (distance < nearestDistance) {
          nearest = candidate;
          nearestDistance = distance;
        }
      });

      if (!nearest || nearestDistance > 14) {
        hideChartTooltip();
        return;
      }

      const count = Number(nearest.point.players_online || 0);
      const countLabel = count === 1 ? "1 player" : `${count} players`;
      const countNode = document.createElement("strong");
      const timeNode = document.createElement("span");
      countNode.textContent = countLabel;
      timeNode.textContent = formatTime(nearest.point.timestamp);

      els.tooltip.replaceChildren(countNode, timeNode);
      els.tooltip.style.display = "block";

      const tooltipRect = els.tooltip.getBoundingClientRect();
      const left = Math.min(
        Math.max(nearest.x, tooltipRect.width / 2 + 8),
        rect.width - tooltipRect.width / 2 - 8
      );
      const top = Math.max(nearest.y, tooltipRect.height + 16);

      els.tooltip.style.left = `${left}px`;
      els.tooltip.style.top = `${top}px`;
    }

    els.form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        currentServer = readServerFromForm();
        localStorage.setItem("mcTrackerHost", currentServer.host);
        localStorage.setItem("mcTrackerPort", String(currentServer.port));
        setMessage("");
        await loadHistory();
        await refreshStatus(true);
      } catch (error) {
        setMessage(error.message, true);
      }
    });

    els.refresh.addEventListener("click", async () => {
      try {
        currentServer = readServerFromForm();
        localStorage.setItem("mcTrackerHost", currentServer.host);
        localStorage.setItem("mcTrackerPort", String(currentServer.port));
        await refreshStatus(true);
      } catch (error) {
        setMessage(error.message, true);
      }
    });

    window.addEventListener("resize", drawChart);
    els.canvas.addEventListener("mousemove", updateChartTooltip);
    els.canvas.addEventListener("mouseleave", hideChartTooltip);

    if (currentServer.host) {
      loadHistory()
        .then(() => refreshStatus(true))
        .catch((error) => setMessage(error.message, true));
    } else {
      render();
    }
  </script>
</body>
</html>
"""

INDEX_HTML = (
    INDEX_HTML
    .replace("__POLL_INTERVAL_MS__", str(POLL_INTERVAL_SECONDS * 1000))
    .replace("__POLL_INTERVAL_LABEL__", POLL_INTERVAL_LABEL)
    .replace("__DEFAULT_MC_HOST_JSON__", json.dumps(DEFAULT_MC_HOST))
    .replace("__DEFAULT_MC_PORT__", str(DEFAULT_MC_PORT))
)


def read_varint(sock: socket.socket) -> int:
    value = 0
    shift = 0

    for _ in range(5):
        data = sock.recv(1)
        if not data:
            raise TimeoutError("The server closed the connection.")
        byte = data[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
        shift += 7

    raise ValueError("Received an invalid VarInt from the server.")


def write_varint(value: int) -> bytes:
    if value < 0:
        value &= 0xFFFFFFFF

    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            output.append(byte | 0x80)
        else:
            output.append(byte)
            return bytes(output)


def write_utf(text: str) -> bytes:
    encoded = text.encode("utf-8")
    return write_varint(len(encoded)) + encoded


def make_packet(packet_id: int, payload: bytes = b"") -> bytes:
    packet = write_varint(packet_id) + payload
    return write_varint(len(packet)) + packet


def read_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(length - len(chunks))
        if not chunk:
            raise TimeoutError("The server closed the connection.")
        chunks.extend(chunk)
    return bytes(chunks)


def ping_minecraft_server(host: str, port: int) -> dict[str, Any]:
    with socket.create_connection((host, port), timeout=PING_TIMEOUT_SECONDS) as sock:
        sock.settimeout(PING_TIMEOUT_SECONDS)

        handshake = (
            write_varint(760)
            + write_utf(host)
            + struct.pack(">H", port)
            + write_varint(1)
        )
        sock.sendall(make_packet(0, handshake))
        sock.sendall(make_packet(0))

        packet_length = read_varint(sock)
        packet_data = read_exact(sock, packet_length)
        packet_offset = 0

        packet_id, packet_offset = read_varint_from_bytes(packet_data, packet_offset)
        if packet_id != 0:
            raise ValueError("The server returned an unexpected status packet.")

        json_length, packet_offset = read_varint_from_bytes(packet_data, packet_offset)
        status_text = packet_data[packet_offset : packet_offset + json_length].decode("utf-8")
        status = json.loads(status_text)

    players = status.get("players", {})

    return {
        "timestamp": format_history_timestamp(),
        "online": True,
        "players_online": int(players.get("online", 0)),
        "players_max": int(players.get("max", 0)),
    }


def read_varint_from_bytes(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0

    for _ in range(5):
        if offset >= len(data):
            raise ValueError("The server returned a truncated packet.")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7

    raise ValueError("Received an invalid VarInt from the server.")


def server_key(host: str, port: int) -> str:
    return f"{host.lower()}:{port}"


def format_history_timestamp(timestamp: Any = None) -> str:
    if timestamp is None:
        timestamp = time.time()
    return time.strftime(TIMESTAMP_FORMAT, time.localtime(timestamp))


def normalize_history_timestamp(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        stripped_value = value.strip()
        try:
            parsed_time = time.strptime(stripped_value, TIMESTAMP_FORMAT)
        except ValueError:
            value = stripped_value
        else:
            return time.strftime(TIMESTAMP_FORMAT, parsed_time)

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return format_history_timestamp()

    if numeric_value > 9_999_999_999:
        numeric_value /= 1000

    return format_history_timestamp(numeric_value)


def load_all_history() -> dict[str, list[dict[str, Any]]]:
    if not HISTORY_FILE.exists():
        return {}

    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}

    if isinstance(data, dict):
        return {
            str(key): value
            for key, value in data.items()
            if isinstance(value, list)
        }

    return {}


def compact_sample(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": normalize_history_timestamp(sample.get("timestamp")),
        "online": bool(sample.get("online", False)),
        "players_online": int(sample.get("players_online", 0) or 0),
        "players_max": int(sample.get("players_max", 0) or 0),
    }


def save_all_history(history: dict[str, list[dict[str, Any]]]) -> None:
    with HISTORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(history, file, indent=2)


def get_history(host: str, port: int) -> list[dict[str, Any]]:
    key = server_key(host, port)
    with history_lock:
        return [compact_sample(sample) for sample in load_all_history().get(key, [])]


def append_history(host: str, port: int, sample: dict[str, Any]) -> list[dict[str, Any]]:
    key = server_key(host, port)
    with history_lock:
        all_history = load_all_history()
        server_history = [compact_sample(item) for item in all_history.get(key, [])]
        server_history.append(compact_sample(sample))
        server_history = server_history[-MAX_HISTORY_POINTS_PER_SERVER:]
        all_history[key] = server_history
        save_all_history(all_history)
        return list(server_history)


def parse_server_query(path: str) -> tuple[str, int]:
    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    host = (query.get("host", [DEFAULT_MC_HOST])[0] or DEFAULT_MC_HOST).strip()
    port_text = query.get("port", [str(DEFAULT_MC_PORT)])[0]

    if host.count(":") == 1 and not host.startswith("["):
        host_part, port_part = host.rsplit(":", 1)
        if port_part:
            host = host_part
            port_text = port_part

    try:
        port = int(port_text)
    except ValueError as error:
        raise ValueError("Port must be a number.") from error

    if not host:
        raise ValueError("Server address is required.")
    if port < 1 or port > 65535:
        raise ValueError("Port must be between 1 and 65535.")

    return host, port


def error_sample(error: Exception) -> dict[str, Any]:
    return {
        "timestamp": format_history_timestamp(),
        "online": False,
        "players_online": 0,
        "players_max": 0,
        "error": str(error),
    }


class TrackerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self.send_html(INDEX_HTML)
            return

        if parsed.path == "/api/history":
            self.handle_history()
            return

        if parsed.path == "/api/status":
            self.handle_status()
            return

        self.send_error(404, "Not found")

    def handle_history(self) -> None:
        try:
            host, port = parse_server_query(self.path)
            self.send_json({
                "server": {"host": host, "port": port},
                "history": get_history(host, port),
            })
        except Exception as error:
            self.send_json({"error": str(error)}, status=400)

    def handle_status(self) -> None:
        try:
            host, port = parse_server_query(self.path)
            try:
                sample = ping_minecraft_server(host, port)
            except Exception as error:
                sample = error_sample(error)

            history = append_history(host, port, sample)
            self.send_json({
                "server": {"host": host, "port": port},
                "sample": sample,
                "history": history,
            })
        except Exception as error:
            self.send_json({"error": str(error)}, status=400)

    def send_html(self, html: str) -> None:
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} - {format % args}")


def main() -> None:
    address = (HOST, int(os.environ.get("PORT", PORT)))
    server = ThreadingHTTPServer(address, TrackerHandler)
    url = f"http://{address[0]}:{address[1]}"

    print("Minecraft Player Tracker")
    print(f"Open {url}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping tracker.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
