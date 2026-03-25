#!/usr/bin/env python3
"""
server.py — AI News Live Web Server
Serves the generated videos via a beautiful browser-based live TV player.
Replace YouTube RTMP entirely — just open the browser and watch.
"""

import os
import json
import time
import threading
import logging

from flask import Flask, jsonify, send_from_directory, Response, render_template_string
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("server")

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────
VIDEOS_DIR   = os.getenv("VIDEOS_DIR", "videos")
AUDIO_DIR    = os.getenv("AUDIO_DIR",  "audio")
HOST         = os.getenv("SERVER_HOST", "0.0.0.0")
PORT         = int(os.getenv("SERVER_PORT", "8080"))

os.makedirs(VIDEOS_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)

# ─────────────────────────────────────────────
#  SSE broadcaster — pushes playlist updates
#  to connected browsers in real time
# ─────────────────────────────────────────────
_sse_clients: list = []
_sse_lock = threading.Lock()


def broadcast_update():
    """Notify all SSE clients that the video list changed."""
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.append("update")
            except Exception:
                dead.append(q)
        for d in dead:
            _sse_clients.remove(d)


def watch_videos_folder():
    """Background thread — watches for new MP4s and broadcasts updates."""
    seen = set()
    while True:
        try:
            current = {f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")}
            if current != seen:
                seen = current
                broadcast_update()
        except Exception:
            pass
        time.sleep(5)


threading.Thread(target=watch_videos_folder, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
#  API routes
# ═══════════════════════════════════════════════════════════════

@app.route("/api/videos")
def api_videos():
    """Return sorted list of available MP4 filenames + metadata."""
    try:
        files = sorted(
            f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")
        )
        videos = []
        for f in files:
            path = os.path.join(VIDEOS_DIR, f)
            stat = os.stat(path)
            videos.append({
                "filename": f,
                "url":      f"/videos/{f}",
                "size_kb":  round(stat.st_size / 1024, 1),
                "modified": int(stat.st_mtime),
            })
        return jsonify({"videos": videos, "count": len(videos)})
    except Exception as e:
        return jsonify({"error": str(e), "videos": [], "count": 0}), 500


@app.route("/videos/<path:filename>")
def serve_video(filename: str):
    """Stream a video file to the browser."""
    return send_from_directory(
        os.path.abspath(VIDEOS_DIR),
        filename,
        mimetype="video/mp4"
    )


@app.route("/api/events")
def sse_events():
    """
    Server-Sent Events endpoint.
    The browser subscribes here to get notified when new videos arrive.
    """
    client_queue: list = []
    with _sse_lock:
        _sse_clients.append(client_queue)

    def generate():
        yield "data: connected\n\n"
        while True:
            if client_queue:
                client_queue.pop(0)
                yield "data: update\n\n"
            time.sleep(1)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":   "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.route("/api/status")
def api_status():
    """Health-check endpoint."""
    try:
        count = len([f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")])
    except Exception:
        count = 0
    return jsonify({"status": "running", "video_count": count})


# ═══════════════════════════════════════════════════════════════
#  Frontend — single-page TV player (served from Python string)
# ═══════════════════════════════════════════════════════════════

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>📡 AI News Live</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&family=Orbitron:wght@700;900&display=swap" rel="stylesheet" />
<style>
  /* ── Reset & Tokens ── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:         #050810;
    --surface:    #0d1117;
    --surface2:   #161b26;
    --border:     #1e2740;
    --accent:     #e53935;
    --accent2:    #ff6f60;
    --gold:       #ffd54f;
    --text:       #e8eaf6;
    --text-muted: #607d8b;
    --live-red:   #f44336;
    --glow:       rgba(229,57,53,0.25);
    --radius:     12px;
  }

  html, body {
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', sans-serif;
    overflow: hidden;
  }

  /* ── Layout ── */
  .shell {
    display: grid;
    grid-template-rows: 56px 1fr 48px;
    grid-template-columns: 1fr 320px;
    grid-template-areas:
      "header  header"
      "player  sidebar"
      "ticker  ticker";
    height: 100vh;
    gap: 0;
  }

  /* ── Header ── */
  header {
    grid-area: header;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    z-index: 10;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: 'Orbitron', sans-serif;
    font-size: 1.1rem;
    font-weight: 900;
    letter-spacing: 2px;
    color: var(--accent);
    text-shadow: 0 0 20px var(--glow);
  }
  .logo .icon { font-size: 1.4rem; animation: pulse 2s infinite; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.5; }
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 20px;
  }

  .live-badge {
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--live-red);
    color: #fff;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 2px;
    padding: 4px 12px;
    border-radius: 4px;
    animation: livepulse 1.5s infinite;
  }
  .live-badge .dot {
    width: 7px; height: 7px;
    background: #fff;
    border-radius: 50%;
  }
  @keyframes livepulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(244,67,54,0.6); }
    50%       { box-shadow: 0 0 0 8px rgba(244,67,54,0); }
  }

  #clock {
    font-size: 0.9rem;
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
    min-width: 80px;
    text-align: right;
  }

  #video-count-badge {
    font-size: 0.8rem;
    color: var(--text-muted);
  }

  /* ── Player ── */
  .player-area {
    grid-area: player;
    position: relative;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }

  #main-video {
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
  }

  /* Overlay shown when no video */
  #no-video-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 16px;
    background: radial-gradient(ellipse at center, #0d1840 0%, #000 70%);
  }
  #no-video-overlay .spinner {
    width: 60px; height: 60px;
    border: 4px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #no-video-overlay p { color: var(--text-muted); font-size: 0.9rem; }

  /* Progress bar across bottom of player */
  #progress-bar-wrap {
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 3px;
    background: rgba(255,255,255,0.08);
  }
  #progress-bar {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    transition: width 0.5s linear;
  }

  /* Now-playing label */
  #now-playing-label {
    position: absolute;
    top: 14px; left: 14px;
    background: rgba(0,0,0,0.7);
    backdrop-filter: blur(6px);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 0.78rem;
    color: var(--gold);
    max-width: 60%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    opacity: 0;
    transition: opacity 0.4s;
  }
  #now-playing-label.visible { opacity: 1; }

  /* ── Sidebar ── */
  .sidebar {
    grid-area: sidebar;
    background: var(--surface);
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .sidebar-header {
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  #playlist {
    flex: 1;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }

  .playlist-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    cursor: pointer;
    transition: background 0.2s;
  }
  .playlist-item:hover { background: var(--surface2); }
  .playlist-item.active {
    background: linear-gradient(90deg, rgba(229,57,53,0.15), transparent);
    border-left: 3px solid var(--accent);
  }

  .playlist-num {
    min-width: 24px;
    font-size: 0.7rem;
    color: var(--text-muted);
    text-align: center;
  }
  .playlist-item.active .playlist-num { color: var(--accent); }

  .playlist-info { flex: 1; overflow: hidden; }
  .playlist-name {
    font-size: 0.78rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--text);
  }
  .playlist-item.active .playlist-name { color: var(--gold); }
  .playlist-meta {
    font-size: 0.68rem;
    color: var(--text-muted);
    margin-top: 2px;
  }

  .playlist-play-icon {
    font-size: 0.8rem;
    color: var(--accent);
    opacity: 0;
    transition: opacity 0.2s;
  }
  .playlist-item.active .playlist-play-icon { opacity: 1; }

  /* Empty state */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 10px;
    color: var(--text-muted);
    font-size: 0.85rem;
    padding: 24px;
    text-align: center;
  }
  .empty-state .big { font-size: 2.5rem; }

  /* ── Ticker ── */
  .ticker {
    grid-area: ticker;
    background: var(--accent);
    overflow: hidden;
    display: flex;
    align-items: center;
  }
  .ticker-label {
    background: #b71c1c;
    color: #fff;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 2px;
    padding: 0 16px;
    height: 100%;
    display: flex;
    align-items: center;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .ticker-track-wrap {
    flex: 1;
    overflow: hidden;
    position: relative;
  }
  #ticker-track {
    display: inline-block;
    white-space: nowrap;
    font-size: 0.78rem;
    font-weight: 500;
    color: #fff;
    animation: ticker-scroll 30s linear infinite;
  }
  @keyframes ticker-scroll {
    0%   { transform: translateX(100vw); }
    100% { transform: translateX(-100%); }
  }

  /* ── Transitions ── */
  .fade-in {
    animation: fadeIn 0.5s ease;
  }
  @keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
  }

  /* ── Responsive ── */
  @media (max-width: 768px) {
    .shell {
      grid-template-areas:
        "header"
        "player"
        "sidebar"
        "ticker";
      grid-template-columns: 1fr;
      grid-template-rows: 56px 1fr 200px 48px;
      overflow-y: auto;
    }
    html, body { overflow: auto; }
  }
</style>
</head>
<body>
<div class="shell">

  <!-- ── Header ─────────────────────────────── -->
  <header>
    <div class="logo">
      <span class="icon">📡</span>
      AI&nbsp;NEWS&nbsp;LIVE
    </div>
    <div class="header-right">
      <span id="video-count-badge">0 videos</span>
      <div class="live-badge"><div class="dot"></div>LIVE</div>
      <span id="clock">--:--:--</span>
    </div>
  </header>

  <!-- ── Player ─────────────────────────────── -->
  <div class="player-area">
    <div id="no-video-overlay">
      <div class="spinner"></div>
      <p>Waiting for video content…</p>
      <p style="font-size:0.75rem;">Run <code style="color:var(--accent)">python generate.py --loop</code> to start generating news videos.</p>
    </div>
    <video id="main-video" autoplay playsinline onclick="toggleMute()" style="display:none"></video>
    <div id="controls-hint" style="position:absolute; bottom:20px; right:24px; background:rgba(0,0,0,0.6); color:white; padding:6px 12px; border-radius:4px; font-size:0.7rem; pointer-events:none; opacity:0.7;">CLICK FOR SOUND</div>
    <div id="now-playing-label"></div>
    <div id="progress-bar-wrap"><div id="progress-bar"></div></div>
  </div>

  <!-- ── Sidebar ─────────────────────────────── -->
  <aside class="sidebar">
    <div class="sidebar-header">
      <span>▶ UP NEXT</span>
      <span id="queue-count">–</span>
    </div>
    <div id="playlist">
      <div class="empty-state">
        <div class="big">🎬</div>
        <span>No videos yet.<br/>Generate some news!</span>
      </div>
    </div>
  </aside>

  <!-- ── Ticker ─────────────────────────────── -->
  <div class="ticker">
    <div class="ticker-label">BREAKING</div>
    <div class="ticker-track-wrap">
      <span id="ticker-track">
        Powered by Gemini AI  ·  Auto-generated news summaries  ·  24/7 AI News Live  ·  
        Start generate.py to populate your channel  ·  
        Connecting to live feed…
      </span>
    </div>
  </div>

</div>

<script>
/* ════════════════════════════════════════════
   State
═══════════════════════════════════════════ */
let playlist     = [];   // [{filename, url, size_kb, modified}, ...]
let currentIndex = 0;
let isPlaying    = false;

const videoEl       = document.getElementById('main-video');
const overlay       = document.getElementById('no-video-overlay');
const nowLabel      = document.getElementById('now-playing-label');
const progressBar   = document.getElementById('progress-bar');
const playlistEl    = document.getElementById('playlist');
const queueCount    = document.getElementById('queue-count');
const countBadge    = document.getElementById('video-count-badge');
const tickerTrack   = document.getElementById('ticker-track');

/* ════════════════════════════════════════════
   Clock
═══════════════════════════════════════════ */
function updateClock() {
  document.getElementById('clock').textContent =
    new Date().toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}
setInterval(updateClock, 1000);
updateClock();

/* ════════════════════════════════════════════
   Fetch playlist from API
═══════════════════════════════════════════ */
async function fetchPlaylist() {
  try {
    const r    = await fetch('/api/videos');
    const data = await r.json();
    return data.videos || [];
  } catch { return []; }
}

/* ════════════════════════════════════════════
   Render sidebar
═══════════════════════════════════════════ */
function renderSidebar() {
  if (playlist.length === 0) {
    playlistEl.innerHTML = `
      <div class="empty-state">
        <div class="big">🎬</div>
        <span>No videos yet.<br/>Generate some news!</span>
      </div>`;
    queueCount.textContent = '–';
    return;
  }

  queueCount.textContent = playlist.length + ' videos';
  countBadge.textContent  = playlist.length + ' videos';

  playlistEl.innerHTML = playlist.map((v, i) => {
    const name = v.filename.replace(/\.mp4$/, '').replace(/_/g, ' ');
    const date = new Date(v.modified * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    const active = (i === currentIndex) ? 'active' : '';
    return `
      <div class="playlist-item ${active}" data-index="${i}" onclick="jumpTo(${i})">
        <div class="playlist-num">${i + 1}</div>
        <div class="playlist-info">
          <div class="playlist-name">${name}</div>
          <div class="playlist-meta">${v.size_kb} KB · ${date}</div>
        </div>
        <div class="playlist-play-icon">▶</div>
      </div>`;
  }).join('');

  /* Scroll active item into view */
  const activeEl = playlistEl.querySelector('.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

/* ════════════════════════════════════════════
   Ticker update
═══════════════════════════════════════════ */
function updateTicker() {
  if (playlist.length === 0) return;
  const names = playlist.map(v => v.filename.replace(/\.mp4$/, '').replace(/_/g, ' '));
  tickerTrack.textContent = names.join('  ·  ') + '  ·  ';
}

/* ════════════════════════════════════════════
   Play a video at index
═══════════════════════════════════════════ */
function playAt(index) {
  if (playlist.length === 0) return;
  currentIndex = ((index % playlist.length) + playlist.length) % playlist.length;
  const vid = playlist[currentIndex];

  overlay.style.display = 'none';
  videoEl.style.display  = 'block';
  videoEl.src = vid.url + '?t=' + Date.now(); // bust cache
  videoEl.load();
  
  /* Attemp autoplay */
  const p = videoEl.play();
  if (p) {
    p.catch(() => {
      /* Autoplay blocked — start muted and show the button */
      videoEl.muted = true;
      videoEl.play();
      document.getElementById('unmute-overlay').style.display = 'flex';
    });
  }

  /* Now-playing label */
  const name = vid.filename.replace(/\.mp4$/, '').replace(/_/g, ' ');
  nowLabel.textContent = '▶ ' + name;
  nowLabel.classList.add('visible');
  setTimeout(() => nowLabel.classList.remove('visible'), 4000);

  isPlaying = true;
  renderSidebar();
}

function toggleMute() {
  videoEl.muted = !videoEl.muted;
  if (!videoEl.muted) videoEl.volume = 1.0;
  updateSoundUI();
}

function updateSoundUI() {
  const hint = document.getElementById('controls-hint');
  hint.textContent = videoEl.muted ? "CLICK FOR SOUND" : "SOUND ON";
  hint.style.background = videoEl.muted ? "rgba(229,57,53,0.8)" : "rgba(76,175,80,0.8)";
  setTimeout(() => hint.style.opacity = videoEl.muted ? "0.7" : "0", 2000);
}

function jumpTo(index) { playAt(index); }

/* ════════════════════════════════════════════
   Video events — progress + auto-advance
═══════════════════════════════════════════ */
videoEl.addEventListener('timeupdate', () => {
  if (!videoEl.duration) return;
  const pct = (videoEl.currentTime / videoEl.duration) * 100;
  progressBar.style.width = pct + '%';
});

videoEl.addEventListener('volumechange', () => {
  updateSoundUI();
});

videoEl.addEventListener('ended', () => {
  progressBar.style.width = '0%';
  playAt(currentIndex + 1);  // advance to next
});

videoEl.addEventListener('error', () => {
  console.warn('Video error, skipping to next.');
  setTimeout(() => playAt(currentIndex + 1), 1500);
});

/* Check initial state */
updateSoundUI();

/* ════════════════════════════════════════════
   Load / refresh playlist
═══════════════════════════════════════════ */
async function refreshPlaylist(autoStart = false) {
  const fresh = await fetchPlaylist();

  /* If new videos arrived, append them without disrupting current play */
  const prevLen = playlist.length;
  playlist = fresh;

  renderSidebar();
  updateTicker();

  if (playlist.length > 0 && (!isPlaying || autoStart)) {
    playAt(currentIndex);
  }
}

/* ════════════════════════════════════════════
   Server-Sent Events — instant update
═══════════════════════════════════════════ */
function connectSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = (e) => {
    if (e.data === 'update') refreshPlaylist(false);
  };
  es.onerror = () => {
    es.close();
    setTimeout(connectSSE, 5000); // reconnect
  };
}

/* ════════════════════════════════════════════
   Bootstrap
═══════════════════════════════════════════ */
refreshPlaylist(true);
connectSSE();

/* Fallback poll every 15 s in case SSE drops */
setInterval(() => refreshPlaylist(false), 15000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


# ═══════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("══════════════════════════════════════")
    log.info(" AI News Live — Web Server")
    log.info(f" http://{HOST}:{PORT}")
    log.info(" Open the above URL in your browser.")
    log.info("══════════════════════════════════════")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
