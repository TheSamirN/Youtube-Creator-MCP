import sys
import yt_dlp
import os
import contextlib
import time
import uuid
import torch  # For GPU detection in Whisper
import whisper_timestamped as whisper
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, concatenate_videoclips, clips_array

# This is the new, highly specific system prompt for your workflow
WORKFLOW_SYSTEM_PROMPT = """
**Your Role:** You are a professional video editor and content creator.

**Your Goal:** Create an informative video (approx 1 min) based on the user's request and provided YouTube URLs.

**CRITICAL: TOOL USAGE**
- You MUST use ONLY the tools provided by this MCP server (YouTubeToolServer)
- Do NOT use bash_tool, terminal, or any other external tools
- All file operations happen through the MCP tools which have access to /downloads
- File paths will always start with /downloads/ - use these paths exactly as returned

**STRICT RULES (MUST FOLLOW):**
1. Each clip MUST be ≤10 seconds
2. ROTATION: After using a video, you MUST use at least 2 DIFFERENT videos before using it again
   - Example GOOD: Video A → Video B → Video C → Video A
   - Example BAD: Video A → Video B → Video A (not enough rotation!)

**VIDEO STRUCTURE (REQUIRED):**
- **INTRO:** First clip must introduce the topic (find a clip where the creator introduces the subject)
- **BODY:** Main content clips covering the key points
- **CONCLUSION:** Last clip must provide a summary or closing thought

**Mandatory Workflow:**

1.  **Get Transcripts:**
    *   Use `get_youtube_transcript` for ALL provided URLs.
    *   Read the full_text to understand the content and note the video_id.

2.  **Create Your Segment Plan:**
    *   Based on the transcripts, select clips that support your narrative.
    *   MUST include intro clip, body clips, and conclusion clip.
    *   For EACH segment, specify:
        - video_id: The source video ID
        - start_time: Start time in seconds (REQUIRED)
        - end_time: End time in seconds (REQUIRED)
        - text: The quote/content being used

3.  **Validate Your Plan:**
    *   Call `create_video_script` with your planned segments.
    *   Fix any validation errors (clip too long, rotation violation).

4.  **Download Clips (NOT full videos!):**
    *   For EACH segment, call `download_videos_from_youtube` with:
        - urls: [the YouTube URL]
        - start_time: segment start time (REQUIRED!)
        - end_time: segment end time (REQUIRED!)
    *   This downloads ONLY the clip portion, not the entire video.
    *   SAVE the file paths returned - you'll need them for stitching!

5.  **Verify Downloads (if needed):**
    *   Call `list_downloads` to see all available files and their exact paths.

6.  **Stitch:**
    *   Use `create_new_video` with the file_paths list (paths starting with /downloads/).
    *   Do NOT use bash or terminal commands - use the create_new_video tool!

**OUTPUT FORMAT for segments:**
```
{
  "video_id": "abc123",
  "start_time": 45,
  "end_time": 52,
  "text": "The battery life is incredible..."
}
```
"""

mcp = FastMCP(name="YouTubeToolServer", instructions=WORKFLOW_SYSTEM_PROMPT)

# Server-side transcript cache - stores full transcript data by video_id
# This allows create_video_script to access transcripts without Claude passing large payloads
TRANSCRIPT_CACHE: dict[str, dict] = {}

# Cache persistence file
CACHE_FILE = os.path.join(os.path.dirname(__file__), "downloads", "transcript_cache.json")

def save_transcript_cache():
    """Save the transcript cache to a JSON file for persistence across restarts."""
    import json
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(TRANSCRIPT_CACHE, f, indent=2, ensure_ascii=False)
        print(f"[Cache] Saved {len(TRANSCRIPT_CACHE)} transcripts to {CACHE_FILE}", file=sys.stderr)
    except Exception as e:
        print(f"[Cache] Failed to save cache: {e}", file=sys.stderr)

def load_transcript_cache():
    """Load the transcript cache from disk if it exists."""
    import json
    global TRANSCRIPT_CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                TRANSCRIPT_CACHE = json.load(f)
            print(f"[Cache] Loaded {len(TRANSCRIPT_CACHE)} transcripts from disk", file=sys.stderr)
        except Exception as e:
            print(f"[Cache] Failed to load cache: {e}", file=sys.stderr)
            TRANSCRIPT_CACHE = {}

# Load cache on module import
load_transcript_cache()

@mcp.tool()
def list_downloads(directory: str = "/downloads") -> dict:
    """
    Lists all files in the downloads directory.
    Use this to verify downloaded files exist and get their correct paths.
    
    Args:
        directory: The directory to list. Defaults to /downloads (the mounted volume).
    
    Returns:
        Dictionary with:
        - files: List of file paths that can be used with other tools
        - count: Number of files found
    """
    try:
        if not os.path.exists(directory):
            return {"error": f"Directory {directory} does not exist", "files": [], "count": 0}
        
        files = []
        for f in os.listdir(directory):
            full_path = os.path.join(directory, f)
            if os.path.isfile(full_path):
                size_mb = os.path.getsize(full_path) / (1024 * 1024)
                files.append({
                    "path": full_path,
                    "name": f,
                    "size_mb": round(size_mb, 2)
                })
        
        return {
            "directory": directory,
            "files": files,
            "count": len(files),
            "note": "Use the 'path' values when calling create_new_video or other tools"
        }
    except Exception as e:
        return {"error": str(e), "files": [], "count": 0}

@mcp.prompt()
def youtube_workflow() -> str:
    """Returns the system prompt for the YouTube Creator workflow."""
    return WORKFLOW_SYSTEM_PROMPT
#mcp = McpServer()
# 1. Initialize your MCP server
# This is the main server app, similar to FastAPI
# mcp = FastMCP(
#     "YouTubeToolServer",
# )

@mcp.tool()
def get_youtube_transcript(video_id_or_url: str) -> dict:
    """
    Fetches a transcript for a YouTube video and caches it server-side.
    Returns a lightweight summary - full data is stored in cache for create_video_script.
    
    Args:
        video_id_or_url: Either the 11-character YouTube video ID (e.g., 'dQw4w9WgXcQ')
                         OR a full YouTube URL (e.g., 'https://www.youtube.com/watch?v=dQw4w9WgXcQ').
        
    Returns:
        A lightweight summary containing:
        - video_id: The video ID (use this when creating video script)
        - full_text: Complete transcript text for reading
        - total_duration: Duration in seconds
        - segment_count: Number of timestamped segments available
        - cached: Confirms data is cached for use with create_video_script
    """
    # Extract video ID from URL if a full URL was provided
    video_id = video_id_or_url
    if "youtube.com" in video_id_or_url or "youtu.be" in video_id_or_url:
        import re
        # Handle youtube.com/watch?v=ID format
        match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', video_id_or_url)
        if match:
            video_id = match.group(1)
        else:
            raise ToolError(f"Could not extract video ID from URL: {video_id_or_url}")
    
    with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id)
            
            # Fetch video metadata (title, channel) using yt-dlp
            video_title = f"Video {video_id}"  # Default fallback
            channel_name = "Unknown Channel"
            try:
                ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                    video_title = info.get('title', video_title)
                    channel_name = info.get('channel', info.get('uploader', channel_name))
            except Exception as meta_err:
                print(f"[get_youtube_transcript] Could not fetch metadata: {meta_err}", file=sys.stderr)
            
            # Build structured segments with precise timestamps
            segments = []
            for item in transcript:
                segments.append({
                    "text": item.text,
                    "start": round(item.start, 2),
                    "end": round(item.start + item.duration, 2),
                    "duration": round(item.duration, 2)
                })
            
            # Build full text for easy reading
            full_text = " ".join([seg["text"] for seg in segments])
            
            # Calculate total duration
            total_duration = segments[-1]["end"] if segments else 0
            
            # Store FULL data in cache (server-side) including metadata
            TRANSCRIPT_CACHE[video_id] = {
                "video_id": video_id,
                "title": video_title,
                "channel": channel_name,
                "segments": segments,
                "full_text": full_text,
                "total_duration": round(total_duration, 2),
                "segment_count": len(segments)
            }
            
            print(f"[get_youtube_transcript] Cached transcript for {video_id}: {len(segments)} segments, {total_duration:.1f}s", file=sys.stderr)
            
            # Save cache to disk for persistence
            save_transcript_cache()
            
            # Return LIGHTWEIGHT response to Claude (no segments - those stay in cache)
            return {
                "video_id": video_id,
                "full_text": full_text,
                "total_duration": round(total_duration, 2),
                "segment_count": len(segments),
                "cached": True,
                "note": "Full segment data cached server-side. Use video_id with create_video_script."
            }
            
        except (TranscriptsDisabled, NoTranscriptFound):
            print(f"[Tool Call] FAILED: Transcripts disabled for {video_id}.")
            raise ToolError(f"No transcripts found for video ID '{video_id}'. They may be disabled or the video is invalid.")
        except Exception as e:
            print(f"[Tool Call] FAILED: Unknown error for {video_id}: {e}")
            raise ToolError(f"An unexpected error occurred: {str(e)}")

@mcp.tool()
def create_video_script(
    segments: list[dict],
    topic: str,
    max_clip_duration: int = 10,
    min_rotation_gap: int = 2
) -> dict:
    """
    Validates and structures a video script plan with ENFORCED rules.
    Call this BEFORE downloading clips to ensure your plan is valid.
    
    RULES ENFORCED:
    - Each clip must be ≤ max_clip_duration seconds (default: 10)
    - Must rotate sources: cannot use same video within min_rotation_gap clips (default: 2)
    
    Args:
        segments: List of planned segments, each with:
            - video_id: Source video ID
            - text: The quote/content to use
            - start_time: Start time in seconds
            - end_time: End time in seconds
        topic: Topic of the video (e.g., "iPhone 17 pros/cons")
        max_clip_duration: Maximum allowed duration per clip in seconds
        min_rotation_gap: Minimum number of different videos before reusing same source
    
    Returns:
        Dictionary with:
        - valid: Boolean indicating if plan passes all rules
        - errors: List of rule violations (empty if valid)
        - validated_segments: The segments with calculated durations
        - total_duration: Total video length in seconds
        - source_count: Number of unique source videos used
    """
    errors = []
    validated_segments = []
    recent_sources = []
    
    for i, seg in enumerate(segments):
        # Validate required fields
        if not all(key in seg for key in ["video_id", "start_time", "end_time"]):
            errors.append(f"Segment {i+1}: Missing required fields (video_id, start_time, end_time)")
            continue
        
        video_id = seg["video_id"]
        start = seg["start_time"]
        end = seg["end_time"]
        duration = end - start
        
        # Rule 1: Check clip duration
        if duration > max_clip_duration:
            errors.append(
                f"Segment {i+1}: Duration {duration:.1f}s exceeds max of {max_clip_duration}s "
                f"(video: {video_id}, {start}s-{end}s)"
            )
        
        # Rule 2: Check rotation
        if video_id in recent_sources:
            position = recent_sources.index(video_id)
            clips_since = len(recent_sources) - position
            errors.append(
                f"Segment {i+1}: Rotation violation! Video '{video_id}' was used {clips_since} clip(s) ago. "
                f"Must use at least {min_rotation_gap} different videos before reusing."
            )
        
        # Track recent sources (sliding window)
        recent_sources.append(video_id)
        if len(recent_sources) > min_rotation_gap:
            recent_sources.pop(0)
        
        # Build validated segment
        validated_segments.append({
            "index": i + 1,
            "video_id": video_id,
            "text": seg.get("text", ""),
            "start_time": start,
            "end_time": end,
            "duration": round(duration, 2)
        })
    
    # Calculate totals
    total_duration = sum(seg["duration"] for seg in validated_segments)
    unique_sources = len(set(seg["video_id"] for seg in validated_segments))
    
    script_id = None
    
    # Save to cache if valid
    if len(errors) == 0:
        script_id = f"script_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        
        # Convert segments to transcript format
        transcript_segments = []
        for seg in validated_segments:
            transcript_segments.append({
                "start": seg["start_time"],
                "end": seg["end_time"],
                "text": seg["text"],
                "video_id": seg["video_id"]  # Store source video ID
            })
            
        # Create cache entry
        TRANSCRIPT_CACHE[script_id] = {
            "video_id": script_id,
            "title": f"Script: {topic}",
            "channel": "AI Generated Study",
            "total_duration": total_duration,
            "segments": transcript_segments,
            "created_at": time.time(),
            "segment_count": len(transcript_segments)
        }
        
        save_transcript_cache()
    
    result = {
        "valid": len(errors) == 0,
        "script_id": script_id,
        "topic": topic,
        "errors": errors,
        "validated_segments": validated_segments,
        "total_duration": round(total_duration, 2),
        "segment_count": len(validated_segments),
        "source_count": unique_sources,
        "rules_applied": {
            "max_clip_duration": max_clip_duration,
            "min_rotation_gap": min_rotation_gap
        },
        "message": f"Script created and saved as {script_id}" if script_id else "Validation failed"
    }
    
    if errors:
        print(f"[create_video_script] Validation FAILED with {len(errors)} error(s)", file=sys.stderr)
    else:
        print(f"[create_video_script] Validation PASSED: {len(validated_segments)} segments, {total_duration:.1f}s total. Saved to cache: {script_id}", file=sys.stderr)
    
    return result



@mcp.tool()
def transcribe_with_word_timestamps(audio_path: str, model_size: str = "base", language: str | None = None) -> dict | None:
    """
    Transcribes an audio file using whisper-timestamped to get
    word-level timestamps and confidence scores.

    Args:
        audio_path: The local file path to the audio file (e.g., /downloads/myaudio.mp3).
        model_size: The Whisper model to use (e.g., "tiny", "base", "small", "medium", "large").
                    "base" is a good balance. Larger models are more accurate but much slower.
        language: The language of the audio (e.g., "en", "es"). If None, it will be auto-detected.

    Returns:
        A dictionary containing the full transcription result, including
        segments and word-level timestamps, or None on failure.
    """
    print(f"Starting transcription for: {audio_path}", file=sys.stderr)
    
    # 1. Check if file exists
    if not os.path.exists(audio_path):
        print(f"Error: Audio file not found at {audio_path}", file=sys.stderr)
        return None

    # 2. Determine the best device to use (GPU is much faster)
    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available(): # For Apple Silicon
        device = "mps"
    
    if device == "cpu":
        print("Warning: No GPU detected. Transcription will be very slow.", file=sys.stderr)
    else:
        print(f"Using device: {device}", file=sys.stderr)

    # 3. Load the model
    model = None
    try:
        print(f"Loading Whisper model: {model_size}...", file=sys.stderr)
        # load_model is from whisper_timestamped
        model = whisper.load_model(model_size, device=device)
        print("Model loaded successfully.", file=sys.stderr)
    except Exception as e:
        print(f"Error loading model '{model_size}': {e}", file=sys.stderr)
        return None

    # 4. Run the transcription
    with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
        result = None
        try:
            print("Transcribing audio... This may take a while.", file=sys.stderr)
            
            # Set options for whisper-timestamped
            # vad=True uses Voice Activity Detection, which is recommended
            # compute_word_confidence=True gives you the confidence score for each word
            transcribe_options = {
                "language": language,
                "vad": True,
                "compute_word_confidence": True,
            }
            
            # Remove language if it's None (to let auto-detect work)
            if language is None:
                transcribe_options.pop("language")

            # whisper.transcribe is the main function from the library
            result = whisper.transcribe(
                model,
                audio_path,
                **transcribe_options
            )
            
            print("Transcription complete.", file=sys.stderr)
        
        except Exception as e:
            print(f"An error occurred during transcription: {e}", file=sys.stderr)
            return None

    # 5. Return the full result object
    return result

@mcp.tool()
def download_audio_for_whisper(source: str, output_path: str = "/downloads") -> dict | None:
    """
    Extracts audio from a YouTube URL OR a local video file, converts it to MP3,
    and saves it to the specified output directory.

    Args:
        source: Either a YouTube URL OR the local file path to a video clip.
        output_path: The directory to save the audio to.

    Returns:
        A dictionary with the file path, or None on failure.
    """
    print(f"Processing audio source: {source}", file=sys.stderr)
    
    try:
        os.makedirs(output_path, exist_ok=True)
        print(f"Saving to directory: {output_path}", file=sys.stderr)
        
        # Check if source is a local file or a URL
        is_local_file = os.path.exists(source)
        
        if is_local_file:
            # --- LOCAL FILE PATH: Extract audio using MoviePy ---
            print(f"Detected local file: {source}", file=sys.stderr)
            
            with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
                # Load the video file
                video_clip = VideoFileClip(source)
                
                # Generate output filename based on input filename
                base_name = os.path.splitext(os.path.basename(source))[0]
                final_filename = os.path.join(output_path, f"{base_name}.mp3")
                
                # Extract and write audio
                print(f"Extracting audio from video...", file=sys.stderr)
                video_clip.audio.write_audiofile(final_filename, codec='mp3', bitrate='192k')
                
                # Clean up
                video_clip.close()
            
            print(f"Successfully extracted audio to: {final_filename}", file=sys.stderr)
            return {"file_path": final_filename}
        
        else:
            # --- URL: Download audio using yt-dlp ---
            print(f"Detected URL: {source}", file=sys.stderr)
            
            # Define filename template
            output_template = os.path.join(output_path, '%(title)s - %(id)s.%(ext)s')

            # yt-dlp options for AUDIO ONLY
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': output_template,
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'noprogress': True,
                'no_color': True,
                'logger': None,
            }

            info_dict = None
            final_filename = None

            with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    print(f"Extracting info and downloading audio...", file=sys.stderr)
                    info_dict = ydl.extract_info(source, download=True)
            
            if info_dict:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    final_filename = ydl.prepare_filename(info_dict)
            else:
                print("yt-dlp failed to return info_dict.", file=sys.stderr)
                return None

            if not final_filename or not os.path.exists(final_filename):
                print(f"File not found at expected path: {final_filename}", file=sys.stderr)
                return None

            print(f"Successfully downloaded audio to: {final_filename}", file=sys.stderr)
            return {"file_path": final_filename}

    except yt_dlp.utils.DownloadError as e:
        print(f"yt-dlp Download Error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        return None

@mcp.tool()
def download_videos_from_youtube(urls: list[str], start_time: float, end_time: float, output_path: str = "/downloads") -> list[dict]:
    """
    Downloads video clips from YouTube using yt-dlp.
    Only downloads the specified time range - NOT the full video.
    
    Args:
        urls: A LIST of YouTube video URLs (e.g., ["url1"])
        start_time: REQUIRED - Start time in seconds for the clip (supports decimals like 5.56).
        end_time: REQUIRED - End time in seconds for the clip (supports decimals like 10.74).
        output_path: The directory to save the videos to.

    Returns:
        A list of dictionaries, one for each *successful* download,
        each containing the 'file_path'.
    """
    
    # Validate that start_time and end_time are provided
    if start_time is None or end_time is None:
        raise ToolError("start_time and end_time are REQUIRED. Do not download full videos!")
    
    # Ensure they are floats for consistent handling
    start_time = float(start_time)
    end_time = float(end_time)
    
    if end_time <= start_time:
        raise ToolError(f"end_time ({end_time}) must be greater than start_time ({start_time})")
    
    # Validate minimum clip duration (ffmpeg struggles with very short clips)
    min_duration = 2.0  # seconds
    clip_duration = end_time - start_time
    if clip_duration < min_duration:
        raise ToolError(
            f"Clip duration ({clip_duration:.2f}s) is too short. "
            f"Minimum duration is {min_duration}s to avoid ffmpeg encoding errors. "
            f"Requested: {start_time}s to {end_time}s"
        )
    
    # Ensure the output directory exists (do this once)
    try:
        os.makedirs(output_path, exist_ok=True)
        print(f"Saving to directory: {output_path}", file=sys.stderr)
    except Exception as e:
        print(f"Failed to create output directory: {e}", file=sys.stderr)
        return [] # Can't continue if we can't create the dir

    # Define filename template
    output_template = os.path.join(output_path, '%(title)s - %(id)s.%(ext)s')

    # yt-dlp options
    ydl_opts = {
        'format': 'best[ext=mp4][height<=1080]/best[ext=m4a]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'noprogress': True,
        'no_color': True,
        'logger': None,
    }

    # Configure partial download (start_time and end_time are now required)
    print(f"Configuring partial download from {start_time}s to {end_time}s", file=sys.stderr)
    
    def download_range_func(info_dict, ydl):
        return [{'start_time': start_time, 'end_time': end_time}]
        
    ydl_opts['download_ranges'] = download_range_func
    # Force keyframes at cuts ensures accurate timing but requires re-encoding
    ydl_opts['force_keyframes_at_cuts'] = True
    
    # Update filename template to include start and end times
    # Format floats for safe filenames: 5.56 -> 5-56 (avoid extra periods in filename)
    start_str = f"{start_time:.2f}".replace('.', '-')
    end_str = f"{end_time:.2f}".replace('.', '-')
    ydl_opts['outtmpl'] = os.path.join(output_path, f'%(title)s - %(id)s_{start_str}_{end_str}.%(ext)s')

    successful_downloads = []

    # Loop through each URL provided in the list
    for url in urls:
        print(f"Attempting to download video from: {url}", file=sys.stderr)
        try:
            info_dict = None
            final_filename = None

            with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    print(f"Extracting info and downloading: {url}", file=sys.stderr)
                    info_dict = ydl.extract_info(url, download=True)
            
            if info_dict:
                # Re-init ydl (this is cheap) just to use its helper method
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    final_filename = ydl.prepare_filename(info_dict)
            else:
                print(f"yt-dlp failed to return info_dict for {url}.", file=sys.stderr)
                continue # Skip to the next URL

            if not final_filename or not os.path.exists(final_filename):
                print(f"File not found at expected path for {url}: {final_filename}", file=sys.stderr)
                continue # Skip to the next URL

            print(f"Successfully downloaded {url} to: {final_filename}", file=sys.stderr)
            
            # Add the successful download to our results list
            successful_downloads.append({"file_path": final_filename})

        except yt_dlp.utils.DownloadError as e:
            print(f"yt-dlp Download Error for {url}: {e}", file=sys.stderr)
            # Continue to the next video
        except Exception as e:
            print(f"An unexpected error occurred for {url}: {e}", file=sys.stderr)
            # Continue to the next video

    # After the loop, return the list of all successful downloads
    return successful_downloads

def format_time(t):
    """Formats time in seconds to HH:MM:SS.ms string (supports floats)."""
    t = float(t)
    hours = int(t // 3600)
    minutes = int((t % 3600) // 60)
    seconds = int(t % 60)
    milliseconds = int((t % 1) * 1000)
    if milliseconds > 0:
        return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"
    return f"{hours:02}:{minutes:02}:{seconds:02}"

@mcp.tool()
def cut_youtube_video_into_segments(file_name: str, start_time: float, end_time: float, center_text: str = "", path: str = "/downloads"):
    """
    Cuts a video file into a segment with precise timestamp support.

    Args:
        file_name (str): The name of the video file (e.g., "video.mp4") or full file path.
        start_time (float): The start time of the segment in seconds (supports decimals like 5.56).
        end_time (float): The end time of the segment in seconds (supports decimals like 10.74).
        center_text (str, optional): Text to overlay in the center of the video.
        path (str, optional): The directory path where the file is located.
                               Defaults to "/downloads".
    """
    # Ensure floats for precise cutting
    start_time = float(start_time)
    end_time = float(end_time)
    with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
        # Construct the full input file path
        input_path = os.path.join(path, file_name)

        # Process the video clip
        clip = (
            VideoFileClip(input_path)
            .subclipped(start_time, end_time)
            .with_volume_scaled(0.8)
        )

        # Set background to 'black' if text exists, otherwise 'None'
        background = 'black' if center_text else None

        centertxt_clip = TextClip(
            font="JosefinSlab-Bold.ttf",
            text=center_text,
            method='caption',
            size=(600, 100),
            font_size=70,
            color='white',
            vertical_align='center', 
            bg_color=background  # Use the variable here
        ).with_duration((end_time - start_time)).with_position('center')

        # Generate a text clip.
        txt_clip = TextClip(
            text=file_name,
            method='caption',
            size=(400, 20),
            font_size=15,
            color='white',
            # Change 'bottom' to 'center'
            vertical_align='center', 
            horizontal_align='left'
        ).with_duration((end_time - start_time)).with_position(('left', 'bottom'))


        timestamp_clip = TextClip(
            text=f"{format_time(start_time)} - {format_time(end_time)}",
            method='caption',
            size=(400, 20),      # Match the width
            font_size=15,
            color='white',
            vertical_align='center', 
            horizontal_align='left'
        ).with_duration((end_time - start_time)).with_position(('left', 'bottom'))

        final_text_block = clips_array([
            [txt_clip],
            [timestamp_clip]
        ])

        # Create a sensible output filename
        # This splits "video.mp4" into "video" and ".mp4"
        base_name, extension = os.path.splitext(file_name)
        # Format floats for safe filenames: 5.56 -> 5-56
        start_str = f"{start_time:.2f}".replace('.', '-')
        end_str = f"{end_time:.2f}".replace('.', '-')
        output_filename = f"{base_name}_trimmed_{start_str}_{end_str}{extension}"
        
        # Construct the full output file path
        output_path = os.path.join(path, output_filename)

        # Overlay the text clip on the first video clip
        final_video = CompositeVideoClip([clip, final_text_block, centertxt_clip])
        final_video.write_videofile(output_path)
        
        print(f"Segment saved to: {output_path}")
        return output_path

@mcp.tool()
def create_new_video(file_paths: list[str], output_filename: str = "stitched_video.mp4", file_path: str = "/downloads") -> str:
    """
    Stitches multiple video files together in the order given.

    Args:
        file_paths: A list of strings, where each string is the
                    full path to a video file.
        output_filename: The name of the file to save the stitched
                    video as. Defaults to "stitched_video.mp4".
        file_path: Optional absolute path where the new video will be saved.
                   If provided, this takes precedence over output_filename.
    
    Returns:
        A string representing the path to the final stitched video.
    """
    
    print(f"Received {len(file_paths)} clips to stitch.")
    clips_list = []
    
    # Validate and construct final output path
    # If file_path is a directory (or default), append filename
    if not file_path or file_path == "/downloads" or file_path == "./downloads" or file_path.endswith(("/", "\\")):
        # Ensure we have a valid directory
        directory = file_path if file_path else "downloads"
        if directory.startswith("/"): directory = "." + directory # Fix for absolute path assumption in local execution
        
        final_output_path = os.path.join(directory, output_filename)
    else:
        # It seems to be a specific file path
        final_output_path = file_path
        
    # Ensure it ends with .mp4
    if not final_output_path.lower().endswith(".mp4"):
        final_output_path += ".mp4"
        
    # Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(final_output_path)), exist_ok=True)
    
    print(f"Stitching to output path: {final_output_path}")

    try:
        # 1. Load your video clips by looping through the list
        clips_list = [VideoFileClip(path) for path in file_paths]
        
        # 2. Normalize all clips to the same resolution to prevent scrolling
        # Find the most common resolution (or use the first clip's resolution)
        if clips_list:
            target_width = clips_list[0].w
            target_height = clips_list[0].h
            
            # Resize all clips to match the target resolution
            normalized_clips = []
            for clip in clips_list:
                if clip.w != target_width or clip.h != target_height:
                    # Resize to match, maintaining aspect ratio with padding
                    try:
                        # MoviePy v1.x
                        resized = clip.resize(height=target_height)
                    except AttributeError:
                        # MoviePy v2.x (uses .resized() or effects)
                        try:
                            resized = clip.resized(height=target_height)
                        except:
                            # Fallback if both fail, just use the clip
                            print(f"Warning: Could not resize clip {clip.filename}")
                            resized = clip

                    if resized.w != target_width:
                        try:
                            # MoviePy v1.x
                            resized = resized.resize(width=target_width)
                        except AttributeError:
                            # MoviePy v2.x
                            try:
                                resized = resized.resized(width=target_width)
                            except:
                                pass
                                
                    normalized_clips.append(resized)
                else:
                    normalized_clips.append(clip)
            
            # 3. Concatenate (stitch) the clips with method="compose" to handle any remaining differences
            final_clip = concatenate_videoclips(normalized_clips, method="compose")
        else:
            raise ValueError("No clips provided")

        # 3. Write the new video file with explicit codec
        final_clip.write_videofile(
            final_output_path,
            codec='libx264',
            audio_codec='aac'
        )

        print(f"Videos stitched successfully! Saved to {final_output_path}")
        return final_output_path

    except Exception as e:
        print(f"Error during video stitching: {e}")
        return f"Error: {e}"

    finally:
        # 4. Optional: Close all clips to free up resources
        for clip in clips_list:
            clip.close()
        
        # 'final_clip' might not exist if an error happened early
        if 'final_clip' in locals():
            final_clip.close()




# #3. Use mcp.run() to start the STDIN/STDOUT server
if __name__ == "__main__":
    mcp.run(transport="stdio")

# For Local Development
# if __name__ == "__main__":
#     mcp.run(transport="http", port=8000)
