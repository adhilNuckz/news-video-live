#!/usr/bin/env python3
"""
generate.py — AI News Content Generator
Fetches RSS → Summarizes with Gemini → TTS → FFmpeg video
Designed to run every 1–2 minutes via cron or a loop.
"""

import os
import re
import time
import hashlib
import logging
import subprocess
import textwrap
import feedparser

from gtts import gTTS
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ─────────────────────────────────────────────
#  Bootstrap
# ─────────────────────────────────────────────
load_dotenv()

def find_local_ffmpeg():
    """Try to find ffmpeg in local dirs and add to PATH."""
    search_dirs = [
        os.path.join(os.getcwd(), "ffmpeg", "bin"),
        os.path.join(os.getcwd(), "bin"),
    ]
    # Also look for any extracted BtbN folders
    for d in os.listdir("."):
        if os.path.isdir(d) and "ffmpeg" in d.lower():
            bin_path = os.path.join(os.getcwd(), d, "bin")
            if os.path.isdir(bin_path):
                search_dirs.append(bin_path)

    for d in search_dirs:
        if os.path.exists(os.path.join(d, "ffmpeg.exe")) or os.path.exists(os.path.join(d, "ffmpeg")):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            log.info(f"Added local FFmpeg to PATH: {d}")
            return True
    return False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("generator")

find_local_ffmpeg()

# ─────────────────────────────────────────────
#  Configuration (edit or set via .env)
# ─────────────────────────────────────────────
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
RSS_FEEDS = [
    { 'url': 'https://feeds.bbci.co.uk/news/world/rss.xml', 'source': 'BBC', 'country': 'Global', 'language': 'English' },
    { 'url': 'https://www.aljazeera.com/xml/rss/all.xml', 'source': 'Al Jazeera', 'country': 'Global', 'language': 'English' },
    { 'url': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml', 'source': 'NYT', 'country': 'Global', 'language': 'English' },
    { 'url': 'https://www.theguardian.com/world/rss', 'source': 'The Guardian', 'country': 'Global', 'language': 'English' },
    { 'url': 'https://rss.cnn.com/rss/edition_world.rss', 'source': 'CNN', 'country': 'Global', 'language': 'English' },
    { 'url': 'https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best', 'source': 'Reuters', 'country': 'Global', 'language': 'English' },
    
    # Sri Lanka
    { 'url': 'https://www.adaderana.lk/rss.php', 'source': 'Ada Derana', 'country': 'Sri Lanka', 'language': 'English' },
    { 'url': 'https://www.newsfirst.lk/rss/', 'source': 'News First', 'country': 'Sri Lanka', 'language': 'English' },
    { 'url': 'https://www.hirunews.lk/rss/english.xml', 'source': 'Hiru News', 'country': 'Sri Lanka', 'language': 'English' },
    { 'url': 'https://www.dailymirror.lk/rss/all', 'source': 'Daily Mirror', 'country': 'Sri Lanka', 'language': 'English' },

    # USA
    { 'url': 'https://feeds.foxnews.com/foxnews/national', 'source': 'Fox News', 'country': 'USA', 'language': 'English' },
    { 'url': 'https://www.npr.org/rss/rss.php?id=1001', 'source': 'NPR', 'country': 'USA', 'language': 'English' },

    # UK
    { 'url': 'https://feeds.bbci.co.uk/news/uk/rss.xml', 'source': 'BBC UK', 'country': 'UK', 'language': 'English' },
    { 'url': 'https://www.theguardian.com/uk/rss', 'source': 'The Guardian UK', 'country': 'UK', 'language': 'English' },

    # India
    { 'url': 'https://timesofindia.indiatimes.com/rssfeedstopstories.cms', 'source': 'Times of India', 'country': 'India', 'language': 'English' },
    { 'url': 'https://www.thehindu.com/news/national/feeder/default.rss', 'source': 'The Hindu', 'country': 'India', 'language': 'English' },
    
    # Australia
    { 'url': 'https://www.abc.net.au/news/feed/51120/rss.xml', 'source': 'ABC News AU', 'country': 'Australia', 'language': 'English' }
]
VIDEOS_DIR       = os.getenv("VIDEOS_DIR", "videos")
AUDIO_DIR        = os.getenv("AUDIO_DIR", "audio")
USED_NEWS_FILE   = os.getenv("USED_NEWS_FILE", "used_news.txt")
VIDEOS_TXT       = os.getenv("VIDEOS_TXT", "videos.txt")
LOOP_INTERVAL    = int(os.getenv("LOOP_INTERVAL_SECONDS", "10"))   # seconds between runs (reduced)
MAX_VIDEOS       = int(os.getenv("MAX_VIDEOS", "200"))             # trim old videos beyond this
VIDEO_WIDTH      = 1280
VIDEO_HEIGHT     = 720
VIDEO_FPS        = 24
FFMPEG_PRESET    = "ultrafast"
TTS_LANG         = os.getenv("TTS_LANG", "en")
FONT_SIZE        = 36
WRAP_WIDTH       = 55   # characters per line for word-wrap

# ─────────────────────────────────────────────
#  Gemini setup
# ─────────────────────────────────────────────
if GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None
    log.warning("GEMINI_API_KEY not set — will use raw article text as fallback.")


# ═══════════════════════════════════════════════════════════════
#  Helper utilities
# ═══════════════════════════════════════════════════════════════

def ensure_dirs():
    """Create output directories if they don't exist."""
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)


def load_used_links() -> set:
    """Return set of already-processed article URLs."""
    if not os.path.exists(USED_NEWS_FILE):
        return set()
    with open(USED_NEWS_FILE, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_link_used(link: str):
    """Append a processed URL to the used-links file."""
    with open(USED_NEWS_FILE, "a", encoding="utf-8") as f:
        f.write(link.strip() + "\n")


def sanitize_text(text: str) -> str:
    """
    Strip characters that break FFmpeg drawtext.
    Removes: single-quotes, double-quotes, colons, backslashes, brackets, special unicode.
    """
    text = re.sub(r"[\"':\\=\[\]{}|<>]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Keep only printable ASCII to avoid font encoding issues
    text = text.encode("ascii", errors="ignore").decode("ascii")
    return text


def wrap_text(text: str, width: int = WRAP_WIDTH) -> str:
    """Word-wrap text and join with \\n for FFmpeg drawtext."""
    lines = textwrap.wrap(text, width=width)
    # FFmpeg drawtext uses literal \n in the text value
    return r"\n".join(lines)


def unique_id(link: str) -> str:
    """Short unique ID derived from the article URL."""
    return hashlib.md5(link.encode()).hexdigest()[:10]


# ═══════════════════════════════════════════════════════════════
#  Step 1 – Fetch RSS
# ═══════════════════════════════════════════════════════════════

def fetch_articles(used_links: set) -> list[dict]:
    """
    Parse all configured RSS feeds and return unseen articles.
    Each article: {"title": ..., "summary": ..., "link": ..., "source": ..., "country": ..., "image_url": ...}
    """
    articles = []
    for feed_info in RSS_FEEDS:
        feed_url = feed_info["url"].strip()
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                link = getattr(entry, "link", "")
                if not link or link in used_links:
                    continue
                title   = getattr(entry, "title",   "No Title")
                summary = getattr(entry, "summary", getattr(entry, "description", ""))
                # Strip HTML tags from summary
                summary = re.sub(r"<[^>]+>", "", summary).strip()
                
                # Image extraction from feed
                image_url = ""
                # Professional news feeds often use media:content or media:thumbnail
                if hasattr(entry, "media_content") and entry.media_content:
                    image_url = entry.media_content[0].get("url", "")
                elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0].get("url", "")
                elif hasattr(entry, "links"):
                    for l in entry.links:
                        if "image" in l.get("type", ""):
                            image_url = l.get("href", "")
                            break
                
                # Fallback: scan summary/content for <img> tags
                if not image_url:
                    raw_content = getattr(entry, "summary", "") + getattr(entry, "content", [{}])[0].get("value", "")
                    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_content)
                    if img_match:
                        image_url = img_match.group(1)

                articles.append({
                    "title": title, 
                    "summary": summary, 
                    "link": link,
                    "source": feed_info["source"],
                    "country": feed_info["country"],
                    "image_url": image_url
                })
        except Exception as exc:
            log.error("RSS fetch failed for %s: %s", feed_url, exc)
    return articles


# ═══════════════════════════════════════════════════════════════
#  Step 2 – Summarize with Gemini
# ═══════════════════════════════════════════════════════════════

def summarize(title: str, raw_text: str, source_name: str = "", country_hint: str = "") -> str:
    """
    Send article text to Gemini; fall back to raw text on error.
    """
    raw_combined = f"{title}. {raw_text}"[:2000]   # cap to reduce tokens

    found_country = ""
    # 1. Use explicit country if available and not 'Global'
    if country_hint and country_hint != "Global":
        found_country = f"In {country_hint}, "
    
    # 2. Heuristic check if no country yet
    if not found_country:
        countries = ["Ukraine", "Russia", "Israel", "Gaza", "USA", "UK", "China", "India", "Germany", "France", "Japan", "Iran"]
        for c in countries:
            if re.search(rf"\b{c}\b", raw_combined, re.IGNORECASE):
                found_country = f"In {c}, "
                break
    
    # 3. Use source name fallback
    if not found_country and source_name:
        found_country = f"Reported by {source_name}: "
            
    try:
        if gemini_client is None:
            # First title only + detected country
            return f"{found_country}{title}"[:180]

        prompt = (
            "Summarize the following news article in exactly THREE comprehensive, punchy sentences. "
            "IMPORTANT: Start the first sentence by clearly identifying the COUNTRY or REGION this news is about. "
            f"This news is from {source_name} " + (f"({country_hint})" if country_hint else "") + ". "
            "Keep the result to roughly 60-80 words for a 45-second broadcast.\n\n"
            f"Article:\n{raw_combined}"
        )
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as exc:
        log.warning("Gemini error (%s) — using raw text fallback.", exc)
        return f"{found_country}{title}"[:180]


# ═══════════════════════════════════════════════════════════════
#  Step 3 – Text-to-Speech
# ═══════════════════════════════════════════════════════════════

def text_to_speech(text: str, audio_path: str) -> bool:
    """
    Convert text to an MP3 file using gTTS.
    Returns True on success.
    """
    try:
        tts = gTTS(text=text, lang=TTS_LANG, slow=False)
        tts.save(audio_path)
        log.info("Audio saved: %s", audio_path)
        return True
    except Exception as exc:
        log.error("TTS failed: %s", exc)
        return False


def fetch_news_image(query_text: str, output_path: str, feed_image_url: str = "") -> bool:
    """
    Fetch a background image for the news video.
    Priority: 1. RSS Feed image, 2. Dynamic Search, 3. Neutral fallback.
    """
    import requests

    # 1. RSS Feed Image (High relevance)
    if feed_image_url:
        log.info(f"Downloading direct RSS image: {feed_image_url}")
        try:
            r = requests.get(feed_image_url, timeout=15, stream=True)
            if r.status_code == 200:
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                return True
        except Exception as exc:
            log.warning(f"Feed image download failed: {exc}")

    # 2. Search Fallback
    # Extract keywords from the text (avoiding small/stop words)
    words = [w for w in re.findall(r'\b\w+\b', query_text.lower()) 
             if len(w) > 4 and w not in {"about", "which", "there", "their", "would"}]
    query = "+".join(words[:4]) or "news"
    
    # Use 'news' tag to avoid random/quirky images like cats
    url = f"https://loremflickr.com/1280/720/{query},news/all"
    
    log.info(f"Fetching news image for query: {query}")
    try:
        r = requests.get(url, timeout=15, stream=True)
        if r.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return True
        return False
    except Exception as exc:
        log.warning(f"Image search failed: {exc}")
        return False


def get_audio_duration(audio_path: str) -> float:
    """Use ffprobe to get audio duration in seconds."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ],
            capture_output=True, text=True, timeout=15
        )
        return float(result.stdout.strip())
    except Exception as exc:
        log.warning("ffprobe duration failed: %s — defaulting to 30s", exc)
        return 30.0


# ═══════════════════════════════════════════════════════════════
#  Step 4 – Generate Video with FFmpeg
# ═══════════════════════════════════════════════════════════════

def generate_video(
    title: str,
    summary: str,
    audio_path: str,
    image_path: str,
    video_path: str,
    duration: float
) -> bool:
    """
    Build a 1280×720 video with a NEWS-SPECIFIC dynamic background.
    """
    safe_title   = sanitize_text(title)
    safe_summary = sanitize_text(summary)
    
    # Check if we have the specific news image, otherwise fall back to global background
    bg_source = image_path if os.path.exists(image_path) else "background.png"
    if not os.path.exists(bg_source):
        # Final safety fallback 
        vf_input = f"color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:r={VIDEO_FPS}:d={duration}"
        input_args = ["-f", "lavfi", "-i", vf_input]
    else:
        input_args = ["-loop", "1", "-i", bg_source]

    # Wrap summary lines for drawtext
    wrapped_summary = wrap_text(safe_summary, width=WRAP_WIDTH)

    watermark = (
        "drawtext=text='📡 AI NEWS LIVE':"
        f"fontsize=22:fontcolor=white:x=20:y=20:"
        "box=1:boxcolor=red@0.8:boxborderw=6"
    )

    title_filter = (
        f"drawtext=text='{safe_title[:80]}':"
        f"fontsize={FONT_SIZE}:fontcolor=yellow:"
        f"x=(w-text_w)/2:y=80:"
        "box=1:boxcolor=black@0.5:boxborderw=4:"
        "line_spacing=8"
    )

    summary_filter = (
        f"drawtext=text='{wrapped_summary}':"
        f"fontsize=28:fontcolor=white:"
        f"x=(w-text_w)/2:y=200:"
        "box=1:boxcolor=black@0.4:boxborderw=8:"
        "line_spacing=10"
    )

    ticker_filter = (
        "drawtext=text='Powered by Gemini AI  |  Auto-generated news summary':"
        "fontsize=18:fontcolor=white@0.8:"
        "x=(w-text_w)/2:y=h-40:"
        "box=1:boxcolor=black@0.6:boxborderw=4"
    )

    # Build the filter string based on input type
    if "lavfi" in input_args[0]:
        filter_str = f"{watermark},{title_filter},{summary_filter},{ticker_filter}[v]"
    else:
        # Just scale the background image and overlay text (no shaky zoompan)
        filter_str = (
            f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"{watermark},{title_filter},{summary_filter},{ticker_filter}[v]"
        )

    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-i", audio_path,
        "-filter_complex", filter_str,
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", FFMPEG_PRESET,
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", str(duration),
        "-shortest",
        "-movflags", "+faststart",
        video_path
    ]

    log.info("Running FFmpeg to generate video...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.error("FFmpeg video error:\n%s", result.stderr[-1000:])
            return False
        log.info("Video saved: %s", video_path)
        return True
    except subprocess.TimeoutExpired:
        log.error("FFmpeg timed out generating video.")
        return False
    except FileNotFoundError:
        log.error("FFmpeg not found — please install FFmpeg and add it to PATH.")
        return False


# ═══════════════════════════════════════════════════════════════
#  Step 5 – Playlist management
# ═══════════════════════════════════════════════════════════════

def rebuild_playlist():
    """
    Rewrite videos.txt with all MP4s currently in the videos/ folder.
    The streamer.sh script reads this file with the concat demuxer.
    """
    mp4_files = sorted(
        f for f in os.listdir(VIDEOS_DIR) if f.endswith(".mp4")
    )

    # Trim playlist if too many videos (keeps disk usage bounded)
    if len(mp4_files) > MAX_VIDEOS:
        excess = mp4_files[:len(mp4_files) - MAX_VIDEOS]
        for old in excess:
            old_path = os.path.join(VIDEOS_DIR, old)
            try:
                os.remove(old_path)
                log.info("Pruned old video: %s", old_path)
            except OSError:
                pass
        mp4_files = mp4_files[len(mp4_files) - MAX_VIDEOS:]

    with open(VIDEOS_TXT, "w", encoding="utf-8") as f:
        for mp4 in mp4_files:
            # Use forward slashes; the concat demuxer accepts them on Linux
            f.write(f"file '{VIDEOS_DIR}/{mp4}'\n")

    log.info("Playlist rebuilt: %d videos in %s", len(mp4_files), VIDEOS_TXT)


# ═══════════════════════════════════════════════════════════════
#  Core pipeline – process one article
# ═══════════════════════════════════════════════════════════════

def process_article(article: dict) -> bool:
    """
    Full pipeline: summarize → TTS → video → playlist update.
    Returns True if a new video was produced.
    """
    title   = article["title"]
    link    = article["link"]
    uid     = unique_id(link)

    audio_path = os.path.join(AUDIO_DIR, f"{uid}.mp3")
    video_path = os.path.join(VIDEOS_DIR, f"{uid}.mp4")

    log.info("▶ Processing: %s", title[:80])

    # 1. Summarize
    raw_text = article.get('summary', '')
    source   = article.get('source', '')
    country  = article.get('country', '')
    summary  = summarize(title, raw_text, source, country)

    # 2. Image: Fetch specific news background (using feed URL if available)
    image_path = os.path.join(AUDIO_DIR, f"{uid}.jpg") 
    feed_img   = article.get('image_url', '')
    fetch_news_image(title + " " + summary, image_path, feed_img)

    # 3. TTS
    if not text_to_speech(summary, audio_path):
        return False

    # 4. Target Duration (45 seconds)
    duration = 45.0

    # 5. Generate video
    if not generate_video(title, summary, audio_path, image_path, video_path, duration):
        return False

    # 5. Mark as used and update playlist
    mark_link_used(link)
    rebuild_playlist()
    return True


# ═══════════════════════════════════════════════════════════════
#  Main loop
# ═══════════════════════════════════════════════════════════════

def run_once():
    """Fetch news and generate ONE new video (the first unseen article)."""
    ensure_dirs()
    used_links = load_used_links()
    articles   = fetch_articles(used_links)

    if not articles:
        log.info("No new articles found.")
        return

    processed_this_cycle = 0
    for article in articles:
        if processed_this_cycle >= 3:
            break
        success = process_article(article)
        if success:
            log.info("✅ Video created successfully.")
            processed_this_cycle += 1
    
    if processed_this_cycle == 0:
        log.info("No articles could be processed this cycle.")


def run_loop():
    """
    Continuous loop mode: run_once() every LOOP_INTERVAL seconds.
    Use this instead of cron if you prefer a long-running process.
    """
    log.info("Generator started in loop mode (interval=%ds).", LOOP_INTERVAL)
    while True:
        try:
            run_once()
        except Exception as exc:
            log.error("Unexpected error in run_once: %s", exc)
        log.info("Sleeping %d seconds until next run…", LOOP_INTERVAL)
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    import sys
    if "--loop" in sys.argv:
        run_loop()
    else:
        run_once()
