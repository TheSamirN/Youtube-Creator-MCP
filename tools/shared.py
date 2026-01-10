"""
Shared utilities for YouTube Creator Studio tools.
Contains caches, logging helpers, and common functions used by both Creative and Precise modes.
"""

import os
import sys
import json
from datetime import datetime
from collections import deque
import threading

# ============================================================================
# Transcript Caches
# ============================================================================

# Server-side transcript cache - stores full transcript data by video_id
TRANSCRIPT_CACHE: dict[str, dict] = {}

# Separate cache for AI-generated transcripts (from create_video_script)
GENERATED_TRANSCRIPT_CACHE: dict[str, dict] = {}

# Precise mode word clips cache - stores extracted clips for UI selection
# Structure: { "sentence_id": { "sentence": str, "words": { "word": [clip1, clip2, clip3] } } }
PRECISE_WORD_CLIPS: dict[str, dict] = {}

# Cache persistence files
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "downloads", "transcript_cache.json")
GENERATED_CACHE_FILE = os.path.join(BASE_DIR, "downloads", "generated_transcript_cache.json")


def save_transcript_cache():
    """Save the transcript cache to a JSON file for persistence across restarts."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(TRANSCRIPT_CACHE, f, indent=2, ensure_ascii=False)
        print(f"[Cache] Saved {len(TRANSCRIPT_CACHE)} transcripts to {CACHE_FILE}", file=sys.stderr)
    except Exception as e:
        print(f"[Cache] Failed to save cache: {e}", file=sys.stderr)


def save_generated_transcript_cache():
    """Save the generated transcript cache to a JSON file for persistence across restarts."""
    try:
        os.makedirs(os.path.dirname(GENERATED_CACHE_FILE), exist_ok=True)
        with open(GENERATED_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(GENERATED_TRANSCRIPT_CACHE, f, indent=2, ensure_ascii=False)
        print(f"[Cache] Saved {len(GENERATED_TRANSCRIPT_CACHE)} generated transcripts to {GENERATED_CACHE_FILE}", file=sys.stderr)
    except Exception as e:
        print(f"[Cache] Failed to save generated cache: {e}", file=sys.stderr)


def load_transcript_cache():
    """Load the transcript cache from disk if it exists."""
    global TRANSCRIPT_CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                TRANSCRIPT_CACHE = json.load(f)
            print(f"[Cache] Loaded {len(TRANSCRIPT_CACHE)} transcripts from disk", file=sys.stderr)
        except Exception as e:
            print(f"[Cache] Failed to load cache: {e}", file=sys.stderr)
            TRANSCRIPT_CACHE = {}


def load_generated_transcript_cache():
    """Load the generated transcript cache from disk if it exists."""
    global GENERATED_TRANSCRIPT_CACHE
    if os.path.exists(GENERATED_CACHE_FILE):
        try:
            with open(GENERATED_CACHE_FILE, 'r', encoding='utf-8') as f:
                GENERATED_TRANSCRIPT_CACHE = json.load(f)
            print(f"[Cache] Loaded {len(GENERATED_TRANSCRIPT_CACHE)} generated transcripts from disk", file=sys.stderr)
        except Exception as e:
            print(f"[Cache] Failed to load generated cache: {e}", file=sys.stderr)
            GENERATED_TRANSCRIPT_CACHE = {}


# ============================================================================
# Text Extraction Utility
# ============================================================================

def extract_text_for_timerange(segments: list[dict], start: float, end: float) -> str:
    """
    Extract all text from transcript segments that fall within or overlap with the given time range.
    
    Args:
        segments: List of transcript segments with 'start', 'end', and 'text' keys
        start: Start time in seconds
        end: End time in seconds
        
    Returns:
        Combined text from all overlapping segments
    """
    text_parts = []
    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", seg_start)
        # Include if segment overlaps with our range
        if seg_end > start and seg_start < end:
            text_parts.append(seg.get("text", ""))
    return " ".join(text_parts)


# ============================================================================
# Server Logs (for web UI display)
# ============================================================================

# Thread-safe log storage (last 200 entries)
SERVER_LOGS = deque(maxlen=200)
LOG_LOCK = threading.Lock()

# Progress tracking state
PROGRESS_STATE = {
    "active": False,
    "label": "",
    "current": 0,
    "total": 0,
    "percent": 0
}


def add_server_log(message: str, level: str = "info"):
    """Add a log entry to the server logs for frontend display."""
    with LOG_LOCK:
        timestamp = datetime.now().strftime("%H:%M:%S")
        SERVER_LOGS.append({
            "time": timestamp,
            "message": message,
            "level": level
        })
    # Also print to stderr for local debugging
    print(f"[{level.upper()}] {message}", file=sys.stderr)


def update_progress(label: str, current: int, total: int):
    """Update progress bar state for frontend display."""
    global PROGRESS_STATE
    percent = int((current / total) * 100) if total > 0 else 0
    PROGRESS_STATE = {
        "active": True,
        "label": label,
        "current": current,
        "total": total,
        "percent": percent
    }
    add_server_log(f"{label}: {current}/{total} ({percent}%)", "info")


def clear_progress():
    """Clear progress bar."""
    global PROGRESS_STATE
    PROGRESS_STATE = {"active": False, "label": "", "current": 0, "total": 0, "percent": 0}


def get_server_logs():
    """Get current server logs as a list."""
    with LOG_LOCK:
        return list(SERVER_LOGS)


def get_progress_state():
    """Get current progress state."""
    return PROGRESS_STATE


def clear_server_logs():
    """Clear all server logs."""
    with LOG_LOCK:
        SERVER_LOGS.clear()
    add_server_log("Logs cleared", "info")


# Load caches on module import
load_transcript_cache()
load_generated_transcript_cache()
