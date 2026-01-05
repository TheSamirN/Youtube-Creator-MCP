"""
YouTube Creator Web UI - FastAPI Backend with Gemini Integration

This server provides:
- Chat endpoint that uses Google Gemini with tool calling
- Direct tool execution endpoints for manual use
- Video file serving for preview
- Static file serving for the frontend
"""

import os
import sys
import json
import re
from typing import Any
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from google import genai
from google.genai import types

# Import tools from existing server.py
from server import (
    get_youtube_transcript,
    create_video_script,
    transcribe_with_word_timestamps,
    download_audio_for_whisper,
    download_videos_from_youtube,
    cut_youtube_video_into_segments,
    create_new_video,
    list_downloads,
    WORKFLOW_SYSTEM_PROMPT,
    TRANSCRIPT_CACHE,
    save_transcript_cache,
)

# Load environment variables
load_dotenv()

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


if not GEMINI_API_KEY:
    print("⚠️  WARNING: GEMINI_API_KEY not set in .env file")
    print("   Get a free API key at: https://aistudio.google.com/app/apikey")

# Initialize FastAPI app
app = FastAPI(title="YouTube Creator Web UI")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Downloads directory
DOWNLOADS_DIR = Path("./downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Static files directory
STATIC_DIR = Path("./static")
STATIC_DIR.mkdir(exist_ok=True)

# ============================================================================
# Tool Definitions for Gemini (new google.genai format)
# ============================================================================

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="get_youtube_transcript",
        description="Fetches a transcript for a YouTube video. Returns video_id, full_text, duration, and segment count.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "video_id_or_url": types.Schema(
                    type=types.Type.STRING,
                    description="YouTube video ID or full URL"
                )
            },
            required=["video_id_or_url"]
        )
    ),
    types.FunctionDeclaration(
        name="create_video_script",
        description="Validates a video script plan with enforced rules (max clip duration, rotation). Call before downloading.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "segments": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "video_id": types.Schema(type=types.Type.STRING),
                            "text": types.Schema(type=types.Type.STRING),
                            "start_time": types.Schema(type=types.Type.NUMBER),
                            "end_time": types.Schema(type=types.Type.NUMBER)
                        }
                    ),
                    description="List of segments with video_id, text, start_time, end_time"
                ),
                "topic": types.Schema(
                    type=types.Type.STRING,
                    description="Topic of the video"
                ),
                "max_clip_duration": types.Schema(
                    type=types.Type.INTEGER,
                    description="Maximum duration per clip in seconds (default: 10)"
                ),
                "min_rotation_gap": types.Schema(
                    type=types.Type.INTEGER,
                    description="Minimum clips before reusing same source (default: 2)"
                )
            },
            required=["segments", "topic"]
        )
    ),
    types.FunctionDeclaration(
        name="download_videos_from_youtube",
        description="Downloads a video clip from YouTube. Only downloads the specified time range.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "urls": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                    description="List of YouTube URLs"
                ),
                "start_time": types.Schema(
                    type=types.Type.NUMBER,
                    description="Start time in seconds (required)"
                ),
                "end_time": types.Schema(
                    type=types.Type.NUMBER,
                    description="End time in seconds (required)"
                ),
                "output_path": types.Schema(
                    type=types.Type.STRING,
                    description="Output directory (default: ./downloads)"
                )
            },
            required=["urls", "start_time", "end_time"]
        )
    ),
    types.FunctionDeclaration(
        name="cut_youtube_video_into_segments",
        description="Cuts a local video file into a segment with text overlay.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "file_name": types.Schema(
                    type=types.Type.STRING,
                    description="Video file name or path"
                ),
                "start_time": types.Schema(
                    type=types.Type.NUMBER,
                    description="Start time in seconds"
                ),
                "end_time": types.Schema(
                    type=types.Type.NUMBER,
                    description="End time in seconds"
                ),
                "center_text": types.Schema(
                    type=types.Type.STRING,
                    description="Text to overlay (optional)"
                ),
                "path": types.Schema(
                    type=types.Type.STRING,
                    description="Directory path (default: ./downloads)"
                )
            },
            required=["file_name", "start_time", "end_time"]
        )
    ),
    types.FunctionDeclaration(
        name="create_new_video",
        description="Stitches multiple video files together in order.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "file_paths": types.Schema(
                    type=types.Type.ARRAY,
                    items=types.Schema(type=types.Type.STRING),
                    description="List of video file paths to stitch"
                ),
                "output_filename": types.Schema(
                    type=types.Type.STRING,
                    description="Output filename (default: stitched_video.mp4)"
                ),
                "file_path": types.Schema(
                    type=types.Type.STRING,
                    description="Output directory (default: ./downloads)"
                )
            },
            required=["file_paths"]
        )
    ),
    types.FunctionDeclaration(
        name="list_downloads",
        description="Lists all files in the downloads directory.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "directory": types.Schema(
                    type=types.Type.STRING,
                    description="Directory to list (default: ./downloads)"
                )
            }
        )
    ),
    types.FunctionDeclaration(
        name="download_audio_for_whisper",
        description="Extracts audio from YouTube URL or local video file as MP3.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "source": types.Schema(
                    type=types.Type.STRING,
                    description="YouTube URL or local video file path"
                ),
                "output_path": types.Schema(
                    type=types.Type.STRING,
                    description="Output directory (default: ./downloads)"
                )
            },
            required=["source"]
        )
    ),
    types.FunctionDeclaration(
        name="transcribe_with_word_timestamps",
        description="Transcribes audio using Whisper with word-level timestamps.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "audio_path": types.Schema(
                    type=types.Type.STRING,
                    description="Path to audio file"
                ),
                "model_size": types.Schema(
                    type=types.Type.STRING,
                    description="Whisper model size (tiny, base, small, medium, large)"
                ),
                "language": types.Schema(
                    type=types.Type.STRING,
                    description="Language code (e.g., 'en') or null for auto-detect"
                )
            },
            required=["audio_path"]
        )
    ),
    types.FunctionDeclaration(
        name="list_cached_transcripts",
        description="Lists all transcripts that have been fetched and cached. Use this to see what transcripts are available before creating a video script.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={}
        )
    ),
    types.FunctionDeclaration(
        name="get_cached_transcript",
        description="Gets the full transcript data (with segments and timestamps) for a previously fetched video. Use after calling list_cached_transcripts.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "video_id": types.Schema(
                    type=types.Type.STRING,
                    description="The YouTube video ID to get the cached transcript for"
                )
            },
            required=["video_id"]
        )
    )
]

# Create Tool object
TOOLS = [types.Tool(function_declarations=TOOL_DECLARATIONS)]

# Tool definitions for the API (JSON format for frontend)
TOOL_DEFINITIONS_JSON = [
    {
        "name": "get_youtube_transcript",
        "description": "Fetches a transcript for a YouTube video. Returns video_id, full_text, duration, and segment count.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_id_or_url": {"type": "string", "description": "YouTube video ID or full URL"}
            },
            "required": ["video_id_or_url"]
        }
    },
    {
        "name": "create_video_script",
        "description": "Validates a video script plan with enforced rules (max clip duration, rotation). Call before downloading.",
        "parameters": {
            "type": "object",
            "properties": {
                "segments": {"type": "array", "description": "List of segments with video_id, text, start_time, end_time"},
                "topic": {"type": "string", "description": "Topic of the video"},
                "max_clip_duration": {"type": "integer", "description": "Maximum duration per clip in seconds (default: 10)"},
                "min_rotation_gap": {"type": "integer", "description": "Minimum clips before reusing same source (default: 2)"}
            },
            "required": ["segments", "topic"]
        }
    },
    {
        "name": "download_videos_from_youtube",
        "description": "Downloads a video clip from YouTube. Only downloads the specified time range.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "description": "List of YouTube URLs"},
                "start_time": {"type": "number", "description": "Start time in seconds (required)"},
                "end_time": {"type": "number", "description": "End time in seconds (required)"},
                "output_path": {"type": "string", "description": "Output directory (default: ./downloads)"}
            },
            "required": ["urls", "start_time", "end_time"]
        }
    },
    {
        "name": "cut_youtube_video_into_segments",
        "description": "Cuts a local video file into a segment with text overlay.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {"type": "string", "description": "Video file name or path"},
                "start_time": {"type": "number", "description": "Start time in seconds"},
                "end_time": {"type": "number", "description": "End time in seconds"},
                "center_text": {"type": "string", "description": "Text to overlay (optional)"},
                "path": {"type": "string", "description": "Directory path (default: ./downloads)"}
            },
            "required": ["file_name", "start_time", "end_time"]
        }
    },
    {
        "name": "create_new_video",
        "description": "Stitches multiple video files together in order.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_paths": {"type": "array", "description": "List of video file paths to stitch"},
                "output_filename": {"type": "string", "description": "Output filename (default: stitched_video.mp4)"},
                "file_path": {"type": "string", "description": "Output directory (default: ./downloads)"}
            },
            "required": ["file_paths"]
        }
    },
    {
        "name": "list_downloads",
        "description": "Lists all files in the downloads directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Directory to list (default: ./downloads)"}
            }
        }
    },
    {
        "name": "download_audio_for_whisper",
        "description": "Extracts audio from YouTube URL or local video file as MP3.",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "YouTube URL or local video file path"},
                "output_path": {"type": "string", "description": "Output directory (default: ./downloads)"}
            },
            "required": ["source"]
        }
    },
    {
        "name": "transcribe_with_word_timestamps",
        "description": "Transcribes audio using Whisper with word-level timestamps.",
        "parameters": {
            "type": "object",
            "properties": {
                "audio_path": {"type": "string", "description": "Path to audio file"},
                "model_size": {"type": "string", "description": "Whisper model size (tiny, base, small, medium, large)"},
                "language": {"type": "string", "description": "Language code (e.g., 'en') or null for auto-detect"}
            },
            "required": ["audio_path"]
        }
    },
    {
        "name": "list_cached_transcripts",
        "description": "Lists all transcripts that have been fetched and cached. Use this to see what transcripts are available.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_cached_transcript",
        "description": "Gets the full transcript data for a previously fetched video.",
        "parameters": {
            "type": "object",
            "properties": {
                "video_id": {"type": "string", "description": "The YouTube video ID"}
            },
            "required": ["video_id"]
        }
    }
]

# Map tool names to functions
# Note: The @mcp.tool() decorator wraps functions in FunctionTool objects.
# We need to access the .fn attribute to get the actual callable function.
TOOL_FUNCTIONS = {
    "get_youtube_transcript": get_youtube_transcript.fn,
    "create_video_script": create_video_script.fn,
    "download_videos_from_youtube": lambda **kwargs: download_videos_from_youtube.fn(
        # Ensure urls is always a list - Gemini sometimes passes a single string
        urls=[kwargs.get("urls")] if isinstance(kwargs.get("urls"), str) else kwargs.get("urls", []),
        start_time=kwargs.get("start_time"),
        end_time=kwargs.get("end_time"),
        output_path=kwargs.get("output_path", "./downloads")
    ),
    "cut_youtube_video_into_segments": lambda **kwargs: cut_youtube_video_into_segments.fn(
        file_name=kwargs.get("file_name"),
        start_time=kwargs.get("start_time"),
        end_time=kwargs.get("end_time"),
        center_text=kwargs.get("center_text", ""),
        path=kwargs.get("path", "./downloads")
    ),
    "create_new_video": lambda **kwargs: create_new_video.fn(
        file_paths=kwargs.get("file_paths", []),
        output_filename=kwargs.get("output_filename", "stitched_video.mp4"),
        file_path=kwargs.get("file_path", "./downloads")
    ),
    "list_downloads": lambda **kwargs: list_downloads.fn(
        directory=kwargs.get("directory", "./downloads")
    ),
    "download_audio_for_whisper": lambda **kwargs: download_audio_for_whisper.fn(
        source=kwargs.get("source"),
        output_path=kwargs.get("output_path", "./downloads")
    ),
    "transcribe_with_word_timestamps": lambda **kwargs: transcribe_with_word_timestamps.fn(
        audio_path=kwargs.get("audio_path"),
        model_size=kwargs.get("model_size", "base"),
        language=kwargs.get("language")
    ),
    "list_cached_transcripts": lambda **kwargs: {
        "cached_videos": [
            {
                "video_id": vid,
                "duration": data.get("total_duration", 0),
                "segment_count": data.get("segment_count", len(data.get("segments", []))),
                "summary": data.get("full_text", "")[:200] + "..." if len(data.get("full_text", "")) > 200 else data.get("full_text", "")
            }
            for vid, data in TRANSCRIPT_CACHE.items()
        ],
        "total_cached": len(TRANSCRIPT_CACHE)
    },
    "get_cached_transcript": lambda **kwargs: TRANSCRIPT_CACHE.get(
        kwargs.get("video_id"),
        {"error": f"Transcript for {kwargs.get('video_id')} not found in cache"}
    ),
}

# ============================================================================
# Pydantic Models
# ============================================================================

class ChatMessage(BaseModel):
    message: str
    history: list[dict] = []

class ToolCallRequest(BaseModel):
    tool_name: str
    args: dict = {}

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML page"""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Static files not found. Create static/index.html</h1>")


@app.post("/api/chat")
async def chat(request: ChatMessage):
    """
    Chat endpoint that sends messages to Gemini with tool calling.
    Handles the full conversation loop including tool execution.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured. Create a .env file with your API key.")
    
    # Create Gemini client
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Build conversation history for Gemini
    contents = []
    for msg in request.history:
        role = "user" if msg.get("role") == "user" else "model"
        contents.append(types.Content(
            role=role,
            parts=[types.Part.from_text(text=msg.get("content", ""))]
        ))
    
    # Add current user message
    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=request.message)]
    ))
    
    # Collect all parts of the response
    result = {
        "response": "",
        "tool_calls": [],
        "tool_results": [],
        "transcript_data": None,
        "suggested_clips": []
    }
    
    # Process response - handle tool calls in a loop
    max_iterations = 10
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        try:
            # Extended system instruction for interactive workflow with confirmations
            extended_system_prompt = WORKFLOW_SYSTEM_PROMPT + """

VIDEO SCRIPT GUIDELINES - NATURAL CONVERSATION FLOW:

When creating a video script, ensure it flows like a NATURAL CONVERSATION between the speaker and the viewer:

1. **INTRODUCTION (REQUIRED)**:
   - Start with a hook that grabs attention
   - Clearly state what the video is about
   - Set expectations for what the viewer will learn
   - Example: Find a clip where the creator introduces the topic

2. **BODY - CONVERSATIONAL FLOW**:
   - Organize clips to tell a coherent story
   - Use transitional language between points
   - Mix different perspectives naturally
   - Avoid abrupt jumps between topics
   - Each clip should connect logically to the next

3. **CONCLUSION (REQUIRED)**:
   - Summarize the key points covered
   - End with a clear takeaway or call to action
   - Find a clip where the creator wraps up or concludes
   - Leave the viewer with something to think about

CLIP SELECTION GUIDELINES:
- Choose clips that sound natural when played back-to-back
- Prefer clips where the speaker finishes their thought
- Avoid cutting in the middle of sentences when possible
- Ensure consistent energy/tone between adjacent clips

INTERACTIVE WORKFLOW - ASK FOR APPROVAL BEFORE EACH MAJOR STEP:

1. **STEP 1 - TRANSCRIPTS**: 
   - First, check what transcripts are available with list_cached_transcripts
   - Use get_cached_transcript to retrieve the full transcript data for each video
   - After getting transcripts, STOP and present a summary to the user
   - Say: "I've retrieved the transcripts. Here's what I found: [summary]. Should I proceed to create the video script?"

2. **STEP 2 - SCRIPT CREATION (MUST USE TOOL)**:
   - Only proceed after user confirms
   - CRITICAL: You MUST call the create_video_script tool. Do NOT just generate text.
   - The tool validates your script and ensures rules are followed
   - Format your segments as: {"video_id": "xxx", "start_time": 0.0, "end_time": 10.0, "text": "clip text"}
   - Pass ALL segments to create_video_script with the topic
   - Present the validated script to the user with timestamps
   - Explain how the flow works (Intro → Body → Conclusion)
   - Say: "Here's the proposed video script with [X] clips validated by the system. Please review and let me know if you'd like any changes, or say 'proceed' to download the clips."

3. **STEP 3 - DOWNLOAD CLIPS**:
   - Only proceed after user approves the script
   - Download each clip one by one using download_videos_from_youtube with start_time and end_time
   - Report progress after each download
   - After all downloads, say: "All clips downloaded successfully. Ready to stitch them together?"

4. **STEP 4 - STITCH VIDEO**:
   - Only proceed after user confirms
   - Call create_new_video with the list of downloaded file paths
   - Report the final video path

CRITICAL RULES:
- ALWAYS use tools, never just generate text when a tool exists for that purpose
- create_video_script MUST be called for any script creation
- download_videos_from_youtube MUST be called for downloading clips (not just suggesting URLs)
- create_new_video MUST be called for stitching
- Be verbose and explain what you're doing at each step
- Show progress updates after each tool call
- ALWAYS wait for user confirmation before moving to the next major phase
- If something fails, explain the error and suggest solutions
"""
            
            # Generate response
            response = client.models.generate_content(
                model="models/gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=extended_system_prompt,
                    tools=TOOLS,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                )
            )
        except Exception as e:
            return {"error": f"Gemini API error: {str(e)}", "response": "", "tool_calls": [], "tool_results": []}
        
        has_function_call = False
        
        # Process the response parts (with null safety checks)
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                # Check for text response
                if part.text:
                    result["response"] += part.text
                    
                    # Parse for suggested clips
                    clips = parse_suggested_clips(part.text)
                    if clips:
                        result["suggested_clips"].extend(clips)
                
                # Check for function call
                if part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}
                    
                    result["tool_calls"].append({
                        "name": tool_name,
                        "args": tool_args
                    })
                    
                    # Execute the tool
                    try:
                        tool_result = execute_tool(tool_name, tool_args)
                        result["tool_results"].append({
                            "name": tool_name,
                            "success": True,
                            "result": tool_result
                        })
                        
                        # If this was a transcript call, store for the UI
                        if tool_name == "get_youtube_transcript" and isinstance(tool_result, dict):
                            result["transcript_data"] = tool_result
                        
                        # Add the assistant's response and function response to contents
                        contents.append(response.candidates[0].content)
                        contents.append(types.Content(
                            role="user",
                            parts=[types.Part.from_function_response(
                                name=tool_name,
                                response={"result": json.loads(json.dumps(tool_result, default=str))}
                            )]
                        ))
                        
                    except Exception as e:
                        error_msg = str(e)
                        result["tool_results"].append({
                            "name": tool_name,
                            "success": False,
                            "error": error_msg
                        })
                        
                        # Add error response
                        contents.append(response.candidates[0].content)
                        contents.append(types.Content(
                            role="user",
                            parts=[types.Part.from_function_response(
                                name=tool_name,
                                response={"error": error_msg}
                            )]
                        ))
        
        # If no function calls in this iteration, we're done
        if not has_function_call:
            break
    
    return result


@app.post("/api/tools/{tool_name}")
async def execute_tool_endpoint(tool_name: str, request: ToolCallRequest):
    """
    Direct tool execution endpoint for manual use.
    Allows calling any tool without going through the LLM.
    """
    if tool_name not in TOOL_FUNCTIONS:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    
    try:
        result = execute_tool(tool_name, request.args)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/tools")
async def list_tools():
    """List all available tools and their parameters"""
    return {"tools": TOOL_DEFINITIONS_JSON}


@app.get("/api/videos")
async def list_videos():
    """List all video files in the downloads directory"""
    videos = []
    for f in DOWNLOADS_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in ['.mp4', '.webm', '.mkv', '.avi', '.mov']:
            videos.append({
                "name": f.name,
                "path": f"/videos/{f.name}",
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2)
            })
    return {"videos": videos}


@app.get("/api/transcripts")
async def get_cached_transcripts():
    """Get all cached transcripts"""
    return {"transcripts": TRANSCRIPT_CACHE}


@app.get("/api/transcripts/{video_id}")
async def get_transcript_by_id(video_id: str):
    """Get a specific cached transcript by video ID"""
    if video_id in TRANSCRIPT_CACHE:
        return TRANSCRIPT_CACHE[video_id]
    raise HTTPException(status_code=404, detail=f"Transcript for '{video_id}' not found in cache")


@app.delete("/api/transcripts")
async def clear_all_transcripts():
    """Clear all cached transcripts"""
    count = len(TRANSCRIPT_CACHE)
    TRANSCRIPT_CACHE.clear()
    save_transcript_cache()
    return {"success": True, "message": f"Cleared {count} cached transcripts"}


@app.delete("/api/transcripts/{video_id}")
async def delete_transcript(video_id: str):
    """Delete a specific transcript from cache"""
    if video_id in TRANSCRIPT_CACHE:
        del TRANSCRIPT_CACHE[video_id]
        save_transcript_cache()
        return {"success": True, "message": f"Deleted transcript for {video_id}"}
    raise HTTPException(status_code=404, detail=f"Transcript for '{video_id}' not found")


# ============================================================================
# Helper Functions
# ============================================================================

def execute_tool(tool_name: str, args: dict) -> Any:
    """Execute a tool by name with given arguments"""
    if tool_name not in TOOL_FUNCTIONS:
        raise ValueError(f"Unknown tool: {tool_name}")
    
    func = TOOL_FUNCTIONS[tool_name]
    return func(**args)


def parse_suggested_clips(text: str) -> list[dict]:
    """
    Parse text for suggested video clips with timestamps.
    Looks for patterns like:
    - video_id: abc123, start: 15, end: 25
    - from 0:15 to 0:25
    - timestamps 15s-25s
    """
    clips = []
    
    # Pattern for video_id with times
    pattern1 = r'video_id[:\s]+([a-zA-Z0-9_-]{11})[,\s]+start[_time:\s]+(\d+(?:\.\d+)?)[,\s]+end[_time:\s]+(\d+(?:\.\d+)?)'
    for match in re.finditer(pattern1, text):
        clips.append({
            "video_id": match.group(1),
            "start_time": float(match.group(2)),
            "end_time": float(match.group(3))
        })
    
    return clips


# ============================================================================
# Static Files and Video Serving
# ============================================================================

# Mount static files AFTER API routes
app.mount("/static", StaticFiles(directory="static"), name="static")

# Video file serving
@app.get("/videos/{filename}")
async def serve_video(filename: str):
    """Serve video files from downloads directory"""
    video_path = DOWNLOADS_DIR / filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(video_path, media_type="video/mp4")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    print("🎬 YouTube Creator Web UI")
    print("=" * 50)
    print(f"📂 Downloads directory: {DOWNLOADS_DIR.absolute()}")
    print(f"🌐 Starting server at http://localhost:8080")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8080)
