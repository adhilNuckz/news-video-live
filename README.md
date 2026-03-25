# 📡 AI News Live – 24/7 Automated News Streamer

A professional, fully automated pipeline that transforms RSS news feeds into a 24/7 live news broadcast. Powered by **Gemini 2.0 Flash**, **gTTS**, and **FFmpeg**.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python: 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)
![AI: Gemini 2.0](https://img.shields.io/badge/AI-Gemini%202.0-red.svg)

---

## 🚀 Overview

This project automates the entire lifecycle of a news channel:
1.  **Fetch**: Monitors 20+ global and local RSS feeds (BBC, CNN, Al Jazeera, Reuters, etc.).
2.  **Summarize**: Uses Google Gemini AI to distill articles into punchy, 3-sentence summaries.
3.  **Voice**: Converts summaries into high-quality speech using Google Text-to-Speech.
4.  **Visualize**: Generates 1280x720 HD videos with dynamic backgrounds based on the news content.
5.  **Broadcast**: 
    - **Web TV Player**: A sleek, real-time browser-based player with an interactive playlist.
    - **YouTube Live**: A robust bash script for 24/7 RTMP streaming.

---

## 🛠️ System Architecture & Flows

### 1. The Generator Module (`generate.py`)
The heart of the system. It runs in a continuous loop to keep the news fresh.
- **RSS Parsing**: Extracts titles, summaries, and high-res images from feeds.
- **AI Synthesis**: Gemini identifies the region/country and writes a target 45-second script.
- **Video Assembly**: FFmpeg layers the audio, a dynamic background image, and overlay text (headlines, ticker, and "LIVE" badges).
- **Playlist Management**: Automatically rebuilds `videos.txt` for the streamers to consume.

### 2. The Web TV Player (`server.py`)
A premium Flask-based web application that serves the generated content.
- **Real-time Updates**: Uses **Server-Sent Events (SSE)** to push new videos to the browser instantly without a page refresh.
- **Interface**: A high-end dark-mode UI featuring a "Breaking News" ticker, auto-advancing playlist, and HD video playback.
- **API Driven**: Exposes endpoints for video storage, playlist status, and live event streams.

### 3. The Live Streamer (`streamer.sh`)
A Bash script designed for production-grade reliability.
- **Continuous Concat**: Uses FFmpeg's concat demuxer to stream the playlist seamlessly.
- **Fallback Slate**: Automatically displays a "Starting Soon" slate if the video queue is empty.
- **RTMP Broadcast**: Optimized for YouTube Live with custom bitrates and GOP settings for stability.

---

## 📦 Installation

### 1. Prerequisites
- **Python 3.9+**
- **FFmpeg**: Must be installed and available in your PATH (or placed in the project directory).
- **Git**

### 2. Setup Environment
```bash
# Clone the repository
git clone https://github.com/adhilNuckz/news-video-live.git
cd news-video-live

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_google_gemini_api_key_here
YOUTUBE_STREAM_KEY=your_youtube_rtmp_key_here
SERVER_PORT=8080
LOOP_INTERVAL_SECONDS=60
```

---

## 🚦 How to Run

To get the full 24/7 experience, run the following in separate terminals:

### Step 1: Start the Content Generator
This will start fetching news and generating videos every minute.
```bash
python generate.py --loop
```

### Step 2: Launch the Web TV Player
Open the URL shown in the terminal (usually `http://localhost:8080`) to watch your news channel.
```bash
python server.py
```

### Step 3: (Optional) Stream to YouTube
Ensure you have a bash environment (Linux, Mac, or WSL/Git Bash on Windows).
```bash
bash streamer.sh
```

---

## 📁 Project Structure
- `generate.py`: Main logic for fetching, AI summarization, and video generation.
- `server.py`: Flask web server and professional TV player UI.
- `streamer.sh`: RTMP streaming script for YouTube/Twitch.
- `audio/`: Temporary storage for TTS files and fetched images.
- `videos/`: Repository of generated MP4 segments.
- `videos.txt`: Dynamic playlist file for FFmpeg concatenation.
- `used_news.txt`: Database of processed article URLs to avoid duplicates.

---

## 🎨 Design Features
- **Dynamic Backgrounds**: Images are fetched based on keywords in the news story.
- **Glassmorphism UI**: The web player uses modern CSS with backdrop filters and sleek animations.
- **Zero Latency Update**: New videos appear in the sidebar the moment they are rendered.

---

*Developed with ❤️ by the AI News Live team.*
