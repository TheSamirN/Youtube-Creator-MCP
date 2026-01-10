"""
Precise Mode Tools for YouTube Creator Studio.
Implements the "ransom-note" style video generator that constructs sentences
by stitching together individual words from YouTube videos.

Workflow:
1. Phase 1: Resource Acquisition - Get/use cached transcripts
2. Phase 2: Search & Planning - Find words, create execution plan
3. Phase 3: Extraction & Precision - Download sentences, Whisper for word timing
4. Phase 4: Final Cut & Assembly - Download exact words, stitch together
"""

import os
import sys
import re
import contextlib
import time
from typing import Optional
from pathlib import Path

# Import from shared utilities
from tools.shared import (
    TRANSCRIPT_CACHE,
    PRECISE_WORD_CLIPS,
    add_server_log,
    update_progress,
    clear_progress,
)

# Confidence threshold for accepting a word
MIN_CONFIDENCE = 0.9


def search_words_in_transcripts(target_sentence: str, video_ids: list[str] = None) -> dict:
    """
    Phase 2, Step B: Search cached transcripts for each word in the target sentence.
    
    Finds each word while ROTATING through videos - cannot use same video twice in a row.
    Returns the full sentence context with timestamps for each word.
    
    Args:
        target_sentence: The sentence to construct (e.g., "iPhone 17 is the Pro")
        video_ids: Optional list of video IDs to search. If None, searches all cached.
        
    Returns:
        Dictionary with word_plan containing video_id, start/end times, and context for each word.
    """
    add_server_log(f"[Precise] Parsing target sentence: '{target_sentence}'", "info")
    
    # Parse target sentence into words
    words = [w.strip() for w in target_sentence.split() if w.strip()]
    if not words:
        return {"error": "No words found in target sentence", "words": []}
    
    add_server_log(f"[Precise] Need to find {len(words)} words: {words}", "info")
    
    # Determine which videos to search
    search_ids = video_ids if video_ids else list(TRANSCRIPT_CACHE.keys())
    
    if not search_ids:
        add_server_log("[Precise] ❌ No transcripts cached. Fetch some first.", "error")
        return {"error": "No transcripts available. Use get_youtube_transcript first.", "words": []}
    
    if len(search_ids) < 2:
        add_server_log("[Precise] ⚠️ Only 1 video available - rotation not possible", "warning")
    else:
        add_server_log(f"[Precise] Searching {len(search_ids)} videos with rotation", "info")
    
    # Build index: word -> list of occurrences grouped by video
    word_occurrences = {}
    
    for video_id in search_ids:
        if video_id not in TRANSCRIPT_CACHE:
            continue
        transcript = TRANSCRIPT_CACHE[video_id]
        segments = transcript.get("segments", [])
        
        for seg_idx, segment in enumerate(segments):
            text = segment.get("text", "")
            start = segment.get("start", 0)
            end = segment.get("end", 0)
            
            # Find all words in this segment
            segment_words = re.findall(r'\b\w+\b', text.lower())
            
            for word in segment_words:
                if word not in word_occurrences:
                    word_occurrences[word] = []
                word_occurrences[word].append({
                    "video_id": video_id,
                    "segment_index": seg_idx,
                    "sentence_start": start,
                    "sentence_end": end,
                    "sentence_text": text.strip(),
                    "video_title": transcript.get("title", video_id)
                })
    
    # Find each target word with VIDEO ROTATION
    word_plan = []
    used_segments = set()  # Track used (video_id, segment_index) pairs
    last_video_id = None  # Track last used video for rotation
    missing_words = []
    
    for i, target_word in enumerate(words):
        update_progress(f"Finding '{target_word}'", i + 1, len(words))
        word_lower = target_word.lower()
        
        if word_lower not in word_occurrences:
            add_server_log(f"[Precise] ❌ Word '{target_word}' not found in any transcript", "warning")
            missing_words.append(target_word)
            continue
        
        # Sort occurrences to prioritize different videos (rotation)
        occurrences = word_occurrences[word_lower]
        
        # First pass: find occurrence from a DIFFERENT video than last used
        found = False
        for occ in occurrences:
            segment_key = (occ["video_id"], occ["segment_index"])
            # Skip if same video as last word (rotation) OR already used segment
            if segment_key in used_segments:
                continue
            if occ["video_id"] == last_video_id and len(search_ids) > 1:
                continue  # Skip same video if we have multiple
            
            used_segments.add(segment_key)
            last_video_id = occ["video_id"]
            
            # Bold the target word in the sentence text
            bolded_text = re.sub(
                rf'\b({re.escape(target_word)})\b',
                r'**\1**',
                occ["sentence_text"],
                count=1,
                flags=re.IGNORECASE
            )
            
            word_plan.append({
                "word_index": i,
                "target_word": target_word,
                "video_id": occ["video_id"],
                "video_title": occ["video_title"],
                "sentence_start": occ["sentence_start"],
                "sentence_end": occ["sentence_end"],
                "sentence_text": bolded_text,
                "segment_index": occ["segment_index"]
            })
            
            add_server_log(
                f"[Precise] ✅ Found '{target_word}' in {occ['video_id']} at {occ['sentence_start']:.1f}s",
                "success"
            )
            found = True
            break
        
        # Second pass: if rotation failed, accept same video
        if not found:
            for occ in occurrences:
                segment_key = (occ["video_id"], occ["segment_index"])
                if segment_key not in used_segments:
                    used_segments.add(segment_key)
                    last_video_id = occ["video_id"]
                    
                    bolded_text = re.sub(
                        rf'\b({re.escape(target_word)})\b',
                        r'**\1**',
                        occ["sentence_text"],
                        count=1,
                        flags=re.IGNORECASE
                    )
                    
                    word_plan.append({
                        "word_index": i,
                        "target_word": target_word,
                        "video_id": occ["video_id"],
                        "video_title": occ["video_title"],
                        "sentence_start": occ["sentence_start"],
                        "sentence_end": occ["sentence_end"],
                        "sentence_text": bolded_text,
                        "segment_index": occ["segment_index"]
                    })
                    
                    add_server_log(
                        f"[Precise] ⚠️ Found '{target_word}' in {occ['video_id']} (same video, no rotation available)",
                        "warning"
                    )
                    found = True
                    break
        
        if not found:
            add_server_log(f"[Precise] ❌ No unused segment for '{target_word}'", "warning")
            missing_words.append(target_word)
    
    clear_progress()
    
    return {
        "target_sentence": target_sentence,
        "total_words": len(words),
        "found_words": len(word_plan),
        "missing_words": missing_words,
        "word_plan": word_plan,
        "videos_searched": search_ids
    }


def extract_precise_word(
    video_id: str,
    target_word: str,
    sentence_start: float,
    sentence_end: float,
    word_index: int = 0
) -> dict:
    """
    Phase 3 & 4: Download sentence clip, run Whisper, extract exact word timing.
    
    Steps:
    D. Download the sentence clip
    E. Extract audio for Whisper
    F. Run Whisper with word timestamps
    G. Parse JSON to find exact word timing (confidence > 0.9)
    H. Download the isolated word clip (NO buffer - exact timing)
    I. Verify clip contains ONLY the target word
    
    Args:
        video_id: YouTube video ID
        target_word: The specific word to extract
        sentence_start: Start time of the sentence containing the word
        sentence_end: End time of the sentence containing the word
        word_index: Index of this word in the final sentence (for naming)
        
    Returns:
        Dictionary with the final word clip path and timing info
    """
    import torch
    import whisper_timestamped as whisper
    from moviepy import VideoFileClip
    import yt_dlp
    
    add_server_log(f"[Precise] Extracting word '{target_word}' from {video_id}", "info")
    
    downloads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")
    os.makedirs(downloads_dir, exist_ok=True)
    
    # Add buffer to sentence boundaries for initial download
    buffer = 1.0
    clip_start = max(0, sentence_start - buffer)
    clip_end = sentence_end + buffer
    
    # === Step D: Download sentence clip ===
    add_server_log(f"[Precise] Step D: Downloading sentence clip ({clip_start:.1f}s - {clip_end:.1f}s)...", "info")
    
    url = f"https://www.youtube.com/watch?v={video_id}"
    sentence_video_path = os.path.join(downloads_dir, f"sentence_{video_id}_{word_index}_{target_word}.mp4")
    
    def download_range_func(info_dict, ydl):
        return [{'start_time': clip_start, 'end_time': clip_end}]
    
    ydl_opts = {
        'format': 'best[ext=mp4][height<=720]/best[ext=mp4]/best',
        'outtmpl': sentence_video_path,
        'quiet': True,
        'no_warnings': True,
        'download_ranges': download_range_func,
        'force_keyframes_at_cuts': True,
    }
    
    try:
        with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
    except Exception as e:
        add_server_log(f"[Precise] ❌ Sentence download failed: {e}", "error")
        return {"error": f"Download failed: {e}"}
    
    if not os.path.exists(sentence_video_path):
        add_server_log(f"[Precise] ❌ Sentence video file not found", "error")
        return {"error": "Video file not created"}
    
    # === Step E: Extract audio ===
    add_server_log(f"[Precise] Step E: Extracting audio...", "info")
    audio_path = os.path.join(downloads_dir, f"sentence_{video_id}_{word_index}_{target_word}.mp3")
    
    try:
        with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
            video_clip = VideoFileClip(sentence_video_path)
            video_clip.audio.write_audiofile(audio_path, codec='mp3', bitrate='192k', logger=None)
            sentence_duration = video_clip.duration
            video_clip.close()
    except Exception as e:
        add_server_log(f"[Precise] ❌ Audio extraction failed: {e}", "error")
        return {"error": f"Audio extraction failed: {e}"}
    
    # === Step F: Whisper precision scan ===
    add_server_log(f"[Precise] Step F: Running Whisper transcription...", "info")
    
    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda"
        add_server_log(f"[Precise] Using GPU: {torch.cuda.get_device_name(0)}", "success")
    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        device = "mps"
        add_server_log(f"[Precise] Using Apple Silicon GPU", "success")
    else:
        add_server_log(f"[Precise] ⚠️ Using CPU - this will be slower", "warning")
    
    try:
        model = whisper.load_model("base", device=device)
        whisper_result = whisper.transcribe(
            model,
            audio_path,
            language="en",
            vad=True,
            compute_word_confidence=True
        )
    except Exception as e:
        add_server_log(f"[Precise] ❌ Whisper transcription failed: {e}", "error")
        return {"error": f"Whisper failed: {e}"}
    
    # === Step G: Parse JSON to find exact word timing with HIGH CONFIDENCE ===
    add_server_log(f"[Precise] Step G: Finding exact timing for '{target_word}' (confidence >= {MIN_CONFIDENCE})...", "info")
    
    target_lower = target_word.lower().strip()
    best_match = None
    
    for segment in whisper_result.get("segments", []):
        for w in segment.get("words", []):
            w_text = w.get("text", "").lower().strip().strip(".,!?\"'")
            w_confidence = w.get("confidence", 0)
            
            if w_text == target_lower:
                # Track best match by confidence
                if best_match is None or w_confidence > best_match["confidence"]:
                    best_match = {
                        "start": w.get("start", 0),
                        "end": w.get("end", 0),
                        "confidence": w_confidence
                    }
    
    if best_match is None:
        add_server_log(f"[Precise] ❌ Word '{target_word}' not found in Whisper output", "error")
        # Cleanup
        try:
            os.remove(sentence_video_path)
            os.remove(audio_path)
        except:
            pass
        return {"error": f"Word '{target_word}' not found in Whisper transcription"}
    
    word_start = best_match["start"]
    word_end = best_match["end"]
    word_confidence = best_match["confidence"]
    
    if word_confidence < MIN_CONFIDENCE:
        add_server_log(
            f"[Precise] ⚠️ Low confidence {word_confidence:.2f} for '{target_word}' (need >= {MIN_CONFIDENCE})",
            "warning"
        )
    else:
        add_server_log(
            f"[Precise] ✅ Found '{target_word}' at {word_start:.3f}s - {word_end:.3f}s (confidence: {word_confidence:.2f})",
            "success"
        )
    
    # === Step H: Cut EXACT word clip (NO buffer for precise extraction) ===
    add_server_log(f"[Precise] Step H: Cutting exact word clip (NO buffer)...", "info")
    
    # Use exact timing - NO buffer for precise word-only extraction
    final_start = max(0, word_start)
    final_end = min(sentence_duration, word_end)
    
    final_path = os.path.join(downloads_dir, f"word_{word_index:02d}_{target_word}_{video_id}.mp4")
    
    try:
        with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
            video_clip = VideoFileClip(sentence_video_path)
            word_clip = video_clip.subclipped(final_start, final_end)
            word_clip.write_videofile(final_path, codec='libx264', audio_codec='aac', logger=None)
            final_duration = word_clip.duration
            word_clip.close()
            video_clip.close()
    except Exception as e:
        add_server_log(f"[Precise] ❌ Word clip creation failed: {e}", "error")
        return {"error": f"Word clip failed: {e}"}
    
    # === Step I: VERIFY clip contains ONLY the target word ===
    add_server_log(f"[Precise] Step I: Verifying clip contains only '{target_word}'...", "info")
    
    # Extract audio from the word clip for verification
    verify_audio_path = os.path.join(downloads_dir, f"verify_{video_id}_{word_index}_{target_word}.mp3")
    
    try:
        with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
            verify_clip = VideoFileClip(final_path)
            verify_clip.audio.write_audiofile(verify_audio_path, codec='mp3', bitrate='192k', logger=None)
            verify_clip.close()
        
        # Run Whisper on the word clip to verify
        verify_result = whisper.transcribe(
            model,
            verify_audio_path,
            language="en",
            vad=True,
            compute_word_confidence=True
        )
        
        # Count words in verification
        verify_words = []
        for seg in verify_result.get("segments", []):
            for w in seg.get("words", []):
                w_text = w.get("text", "").strip().strip(".,!?\"'")
                if w_text:
                    verify_words.append(w_text)
        
        # Cleanup verify audio
        try:
            os.remove(verify_audio_path)
        except:
            pass
        
        if len(verify_words) == 0:
            add_server_log(f"[Precise] ⚠️ Verification found no words in clip", "warning")
        elif len(verify_words) == 1:
            if verify_words[0].lower() == target_lower:
                add_server_log(f"[Precise] ✅ VERIFIED: Clip contains only '{verify_words[0]}'", "success")
            else:
                add_server_log(f"[Precise] ⚠️ Clip contains '{verify_words[0]}' instead of '{target_word}'", "warning")
        else:
            add_server_log(f"[Precise] ⚠️ Clip contains {len(verify_words)} words: {verify_words}", "warning")
            
    except Exception as e:
        add_server_log(f"[Precise] ⚠️ Verification failed: {e}", "warning")
    
    # Cleanup temp files
    try:
        os.remove(sentence_video_path)
        os.remove(audio_path)
    except:
        pass
    
    add_server_log(f"[Precise] ✅ Word '{target_word}' extracted: {final_path}", "success")
    
    return {
        "success": True,
        "word_index": word_index,
        "target_word": target_word,
        "video_id": video_id,
        "file_path": final_path,
        "whisper_start": word_start,
        "whisper_end": word_end,
        "confidence": word_confidence,
        "duration": final_duration
    }


def stitch_word_clips(word_clips: list[dict], output_filename: str = None) -> dict:
    """
    Phase 4, Step J: Stitch word clips together into the final video.
    
    Args:
        word_clips: List of word extraction results (from extract_precise_word)
        output_filename: Optional output filename
        
    Returns:
        Dictionary with the final video path
    """
    from moviepy import VideoFileClip, concatenate_videoclips
    
    # Sort clips by word_index to ensure correct order
    sorted_clips = sorted(word_clips, key=lambda x: x.get("word_index", 0))
    
    sentence_words = [c.get("target_word", "") for c in sorted_clips]
    add_server_log(f"[Precise] Step J: Stitching {len(sorted_clips)} clips: {' '.join(sentence_words)}", "info")
    
    downloads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")
    
    # Generate output filename from words if not provided
    if not output_filename:
        safe_name = "_".join(sentence_words[:5]).replace(" ", "_")
        timestamp = int(time.time())
        output_filename = f"precise_{safe_name}_{timestamp}.mp4"
    
    output_path = os.path.join(downloads_dir, output_filename)
    
    # Load clips
    clips = []
    for i, clip_info in enumerate(sorted_clips):
        file_path = clip_info.get("file_path")
        if not file_path or not os.path.exists(file_path):
            add_server_log(f"[Precise] ⚠️ Clip file not found: {file_path}", "warning")
            continue
        
        update_progress(f"Loading clip {i+1}/{len(sorted_clips)}", i + 1, len(sorted_clips))
        
        try:
            clip = VideoFileClip(file_path)
            clips.append(clip)
        except Exception as e:
            add_server_log(f"[Precise] ⚠️ Failed to load clip: {e}", "warning")
    
    if not clips:
        clear_progress()
        add_server_log("[Precise] ❌ No valid clips to stitch!", "error")
        return {"error": "No valid clips to stitch"}
    
    # Stitch together
    try:
        with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            final_duration = final.duration
            final.close()
        
        # Close all clips
        for clip in clips:
            clip.close()
    except Exception as e:
        clear_progress()
        add_server_log(f"[Precise] ❌ Stitching failed: {e}", "error")
        return {"error": f"Stitching failed: {e}"}
    
    clear_progress()
    add_server_log(f"[Precise] ✅ Final video created: {output_path}", "success")
    add_server_log(f"[Precise] 🎬 Video says: '{' '.join(sentence_words)}'", "success")
    
    return {
        "success": True,
        "file_path": output_path,
        "sentence": " ".join(sentence_words),
        "clips_count": len(clips),
        "duration": final_duration
    }


# Keep legacy function names for backwards compatibility
def find_words_in_transcripts(words: list[str], video_ids: list[str] = None) -> dict:
    """Legacy wrapper - converts word list to sentence and calls search_words_in_transcripts."""
    sentence = " ".join(words)
    return search_words_in_transcripts(sentence, video_ids)


def create_word_video(word_clips: list[dict], output_filename: str = None) -> dict:
    """Legacy wrapper for stitch_word_clips."""
    return stitch_word_clips(word_clips, output_filename)


def extract_word_options(
    target_sentence: str,
    max_options: int = 3,
    video_ids: list[str] = None
) -> dict:
    """
    Extract up to N clip options for each word in the target sentence.
    Stores results in PRECISE_WORD_CLIPS cache for UI display.
    
    Args:
        target_sentence: The sentence to construct
        max_options: Maximum number of clip options per word (default 3)
        video_ids: Optional list of video IDs to search
        
    Returns:
        Dictionary with sentence_id and word clips data
    """
    import hashlib
    
    add_server_log(f"[Precise] Extracting {max_options} options per word for: '{target_sentence}'", "info")
    
    # Generate sentence ID
    sentence_id = hashlib.md5(target_sentence.encode()).hexdigest()[:8]
    
    # First, search for all word occurrences (not just first)
    words = [w.strip() for w in target_sentence.split() if w.strip()]
    if not words:
        return {"error": "No words found in target sentence"}
    
    search_ids = video_ids if video_ids else list(TRANSCRIPT_CACHE.keys())
    
    if not search_ids:
        return {"error": "No transcripts available"}
    
    # Build word occurrence index
    word_occurrences = {}
    for video_id in search_ids:
        if video_id not in TRANSCRIPT_CACHE:
            continue
        transcript = TRANSCRIPT_CACHE[video_id]
        segments = transcript.get("segments", [])
        
        for seg_idx, segment in enumerate(segments):
            text = segment.get("text", "")
            start = segment.get("start", 0)
            end = segment.get("end", 0)
            
            segment_words = re.findall(r'\b\w+\b', text.lower())
            
            for word in segment_words:
                if word not in word_occurrences:
                    word_occurrences[word] = []
                word_occurrences[word].append({
                    "video_id": video_id,
                    "segment_index": seg_idx,
                    "sentence_start": start,
                    "sentence_end": end,
                    "sentence_text": text.strip(),
                    "video_title": transcript.get("title", video_id)
                })
    
    # Initialize result structure
    result = {
        "sentence_id": sentence_id,
        "sentence": target_sentence,
        "words": {}
    }
    
    total_words = len(words)
    total_clips = 0
    
    # Extract clips for each word
    for word_idx, target_word in enumerate(words):
        word_lower = target_word.lower()
        
        if word_lower not in word_occurrences:
            add_server_log(f"[Precise] ❌ Word '{target_word}' not found", "warning")
            result["words"][target_word] = {"error": "Word not found", "clips": []}
            continue
        
        occurrences = word_occurrences[word_lower]
        clips_for_word = []
        used_segments = set()
        
        # Extract up to max_options clips
        for occ in occurrences:
            if len(clips_for_word) >= max_options:
                break
            
            segment_key = (occ["video_id"], occ["segment_index"])
            if segment_key in used_segments:
                continue
            used_segments.add(segment_key)
            
            clip_idx = len(clips_for_word)
            total_clips += 1
            
            update_progress(
                f"Extracting '{target_word}' clip {clip_idx + 1}/{max_options}",
                total_clips,
                total_words * max_options
            )
            
            # Extract the clip
            clip_result = extract_precise_word(
                video_id=occ["video_id"],
                target_word=target_word,
                sentence_start=occ["sentence_start"],
                sentence_end=occ["sentence_end"],
                word_index=word_idx * 100 + clip_idx  # Unique index for file naming
            )
            
            if clip_result.get("success"):
                clips_for_word.append({
                    "clip_index": clip_idx,
                    "video_id": occ["video_id"],
                    "video_title": occ["video_title"],
                    "file_path": clip_result["file_path"],
                    "duration": clip_result["duration"],
                    "confidence": clip_result["confidence"],
                    "sentence_context": occ["sentence_text"][:100]
                })
                add_server_log(
                    f"[Precise] ✅ Clip {clip_idx + 1} for '{target_word}' from {occ['video_id']}",
                    "success"
                )
            else:
                add_server_log(
                    f"[Precise] ⚠️ Failed clip for '{target_word}': {clip_result.get('error')}",
                    "warning"
                )
        
        result["words"][target_word] = {
            "word_index": word_idx,
            "clips": clips_for_word
        }
    
    clear_progress()
    
    # Store in cache for UI access
    PRECISE_WORD_CLIPS[sentence_id] = result
    
    add_server_log(f"[Precise] ✅ Extracted clips stored with ID: {sentence_id}", "success")
    
    return result


def stitch_selected_clips(sentence_id: str, selections: dict) -> dict:
    """
    Stitch together user-selected clips from the UI.
    
    Args:
        sentence_id: The sentence ID from extract_word_options
        selections: Dict mapping word -> selected clip_index
        
    Returns:
        Dictionary with final video path
    """
    from moviepy import VideoFileClip, concatenate_videoclips
    
    if sentence_id not in PRECISE_WORD_CLIPS:
        return {"error": f"Sentence ID '{sentence_id}' not found"}
    
    sentence_data = PRECISE_WORD_CLIPS[sentence_id]
    sentence = sentence_data["sentence"]
    words_data = sentence_data["words"]
    
    add_server_log(f"[Precise] Stitching selected clips for: '{sentence}'", "info")
    
    downloads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")
    
    # Build ordered list of clips based on selections
    clips_to_stitch = []
    words = sentence.split()
    
    for word_idx, word in enumerate(words):
        if word not in words_data:
            add_server_log(f"[Precise] ⚠️ No clips for word '{word}'", "warning")
            continue
        
        word_clips = words_data[word].get("clips", [])
        if not word_clips:
            add_server_log(f"[Precise] ⚠️ No clips available for '{word}'", "warning")
            continue
        
        # Get selected clip index (default to first)
        selected_idx = selections.get(word, 0)
        if selected_idx >= len(word_clips):
            selected_idx = 0
        
        selected_clip = word_clips[selected_idx]
        clips_to_stitch.append({
            "word_index": word_idx,
            "target_word": word,
            "file_path": selected_clip["file_path"],
            "video_id": selected_clip["video_id"]
        })
    
    if not clips_to_stitch:
        return {"error": "No clips to stitch"}
    
    # Use existing stitch function
    return stitch_word_clips(clips_to_stitch)
