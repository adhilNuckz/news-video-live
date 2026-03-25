#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# streamer.sh — 24/7 YouTube RTMP Streamer
#
# Reads videos.txt (concat playlist) and streams continuously.
# Loops forever; creates a fallback slate if no videos exist yet.
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Load .env variables (if present) ──────────────────────────────
if [ -f .env ]; then
    # Export only KEY=VALUE lines; skip comments and blanks
    export $(grep -v '^\s*#' .env | grep '=' | xargs)
fi

# ── Configuration ─────────────────────────────────────────────────
STREAM_KEY="${YOUTUBE_STREAM_KEY:-YOUR_STREAM_KEY_HERE}"
RTMP_URL="rtmp://a.rtmp.youtube.com/live2/${STREAM_KEY}"

VIDEOS_DIR="${VIDEOS_DIR:-videos}"
VIDEOS_TXT="${VIDEOS_TXT:-videos.txt}"
FALLBACK_VIDEO="${FALLBACK_VIDEO:-fallback.mp4}"

VIDEO_BITRATE="${VIDEO_BITRATE:-2000k}"
AUDIO_BITRATE="${AUDIO_BITRATE:-128k}"
FPS="${FPS:-24}"

LOG_FILE="streamer.log"

# ── Logging helper ────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# ── Create output dirs ────────────────────────────────────────────
mkdir -p "$VIDEOS_DIR"

# ─────────────────────────────────────────────────────────────────
# generate_fallback_video
# Creates a 30-second "standby" slate if no real videos exist yet.
# ─────────────────────────────────────────────────────────────────
generate_fallback_video() {
    log "Generating fallback slate video: $FALLBACK_VIDEO"
    ffmpeg -y \
        -f lavfi -i "color=c=black:s=1280x720:r=${FPS}:d=30" \
        -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
        -vf "drawtext=text='📡 AI News Live — Starting Soon':fontsize=40:\
fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:\
box=1:boxcolor=black@0.5:boxborderw=12" \
        -c:v libx264 -preset ultrafast -crf 28 \
        -c:a aac -b:a 64k \
        -t 30 -shortest \
        "$FALLBACK_VIDEO" 2>>"$LOG_FILE" \
    && log "Fallback video ready." \
    || log "WARNING: Could not create fallback video."
}

# ─────────────────────────────────────────────────────────────────
# ensure_playlist
# Builds or refreshes videos.txt.
# Falls back to the slate video if the folder is empty.
# ─────────────────────────────────────────────────────────────────
ensure_playlist() {
    local mp4_count
    mp4_count=$(find "$VIDEOS_DIR" -maxdepth 1 -name "*.mp4" | wc -l)

    if [ "$mp4_count" -eq 0 ]; then
        log "No videos in $VIDEOS_DIR — using fallback slate."
        [ -f "$FALLBACK_VIDEO" ] || generate_fallback_video
        echo "file '${FALLBACK_VIDEO}'" > "$VIDEOS_TXT"
    else
        # Rebuild playlist from current folder contents
        # (generate.py also does this, but we refresh here too)
        {
            find "$VIDEOS_DIR" -maxdepth 1 -name "*.mp4" | sort \
            | while read -r f; do echo "file '$f'"; done
        } > "$VIDEOS_TXT"
        log "Playlist updated: $mp4_count video(s)."
    fi
}

# ─────────────────────────────────────────────────────────────────
# stream_once
# Runs ONE pass of the FFmpeg concat → RTMP pipeline.
# Returns when the playlist is exhausted (then the loop re-runs).
# ─────────────────────────────────────────────────────────────────
stream_once() {
    log "▶ Starting FFmpeg stream → ${RTMP_URL%%/*}/***"

    ffmpeg -hide_banner -loglevel warning \
        -re \
        -f concat -safe 0 \
        -i "$VIDEOS_TXT" \
        -vf "fps=${FPS},format=yuv420p" \
        -c:v libx264 -preset ultrafast \
        -b:v "${VIDEO_BITRATE}" \
        -maxrate "${VIDEO_BITRATE}" \
        -bufsize "$(echo "${VIDEO_BITRATE}" | sed 's/k//'| awk '{print $1*2}')k" \
        -g $((FPS * 2)) \
        -c:a aac -b:a "${AUDIO_BITRATE}" -ar 44100 \
        -f flv \
        "${RTMP_URL}" \
        2>>"$LOG_FILE"

    log "FFmpeg exited (playlist exhausted or error). Restarting…"
}

# ─────────────────────────────────────────────────────────────────
# MAIN — infinite loop
# ─────────────────────────────────────────────────────────────────
log "══════════════════════════════════════════════"
log "AI News Streamer starting."
log "Stream target: YouTube Live (RTMP)"
log "══════════════════════════════════════════════"

while true; do
    ensure_playlist
    stream_once || true   # 'true' prevents set -e from killing the loop
    sleep 2               # brief pause before restarting
done
