# 🎬 YouTube Creator MCP

**Your AI-powered studio for remixing YouTube content.**  
Transform existing videos into new creations with the power of Google Gemini and Whisper.

---

## ✨ Features

- **📝 Smart Transcripts**: Fetch, cache, and search transcripts from any YouTube video.
- **🤖 AI Script Generation**: Create entirely new video scripts based on your chosen topic.
- **✂️ Precise Clip Extraction**: Find exact words or phrases across multiple videos.
- **🎞️ Automated Stitching**: Download, cut, and assemble clips into a final MP4 video.
- **🖥️ Web UI**: A beautiful, dark-mode interface to manage your workflow.

---

## 🎨 Creative Mode
**Best for: Summaries, remixes, and topic-based compilations.**

In Creative Mode, the AI acts as your video editor. It researches your cached transcripts to find relevant content and constructs a cohesive narrative.

### How it works:
1. **Fetch Transcripts**: Ask the AI to get transcripts from YouTube videos related to your topic.
2. **Generate Script**: Provide a prompt, and the AI will select the best segments to tell a story.
3. **Create Video**: The AI downloads the selected clips and stitches them together.

### 💡 Sample Prompt
> "Create a 30-second summary of the iPhone 17 rumors based on the videos I've loaded. Focus on the camera upgrades."

---

## 🎯 Precise Mode
**Best for: Ransom-note style videos, memes, and specific sentence construction.**

In Precise Mode, you have surgical control. The AI finds individual words across your video library to construct exact sentences, "ransom-note" style.

### How it works:
1. **Input Sentence**: Tell the AI exactly what you want the video to "say" (e.g., "iPhone 17 is the Pro").
2. **Search & Extract**: The AI hunts for each word in your transcripts and extracts audio/video clips.
3. **Select Your Clips**: Use the **Precise Words Tab** to audition up to 3 different versions of each word.
4. **Stitch**: Click "Create Video" to assemble your masterpiece.

### 💡 Sample Prompt
> "Switch to precise mode. Create a video that says 'Gemini is the future of coding'."

---

## � Getting Started

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *Note: You'll need `ffmpeg` installed on your system.*

2. **Run the App**:
   ```bash
   python web_app.py
   ```

3. **Open Browser**:
   Navigate to `http://localhost:8080`

---

## �️ Tech Stack
- **Backend**: FastAPI, Python
- **AI**: Google Gemini Pro (Reasoning & Code), OpenAI Whisper
- **Video Processing**: MoviePy, yt-dlp
- **Frontend**: Vanilla JS, CSS3, HTML5
