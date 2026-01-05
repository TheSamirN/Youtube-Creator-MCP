from fastmcp import FastMCP
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, concatenate_videoclips
from pytube import YouTube
from pytube.exceptions import PytubeError, VideoUnavailable
import yt_dlp
import os
import uvicorn

mcp = FastMCP("My MCP Server")

# 1. Initialize your MCP server
# This is the main server app, similar to FastAPI
mcp = FastMCP(
    "YouTubeToolServer",

)

# 2. Define your tool(s) using the @mcp.tool() decorator
@mcp.tool()
def get_youtube_transcript(video_id: str) -> str:
    """
    Fetches the full, concatenated text transcript for a given YouTube video ID.
    The AI will read this docstring to understand what the tool does.
    
    Args:
        video_id: The 11-character YouTube video ID (e.g., 'dQw4w9WgXcQ').
        
    Returns:
        The full transcript as a single string.
    """
    try:
        # Use the youtube-transcript-api library to do the work
        #transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id)

        # Format the output into a single, clean string for the AI
        #full_transcript = " ".join([segment['text'] for segment in transcript])
        
        # print(f"[Tool Call] Successfully fetched transcript for {video_id}.")
        return transcript
        
    except (TranscriptsDisabled, NoTranscriptFound):
        # This is a common, expected error.
        print(f"[Tool Call] FAILED: Transcripts disabled for {video_id}.")
        # 'ToolError' is the correct way to send a user-facing error back to the AI
        raise ToolError(f"No transcripts found for video ID '{video_id}'. They may be disabled or the video is invalid.")
    except Exception as e:
        # This handles all other unexpected errors
        print(f"[Tool Call] FAILED: Unknown error for {video_id}: {e}")
        raise ToolError(f"An unexpected error occurred: {str(e)}")

@mcp.tool()
def download_video_robust(url: str, output_path: str = ".") -> str | None:
    """
    Downloads the best available video (muxed) using yt-dlp.
    Ensures the output is a standard .mp4 file.

    Args:
        url: The URL of the YouTube video.
        output_path: The directory to save the video to.

    Returns:
        The full file path of the downloaded video, or None if it failed.
    """
    print(f"Attempting to download video from: {url}")
    try:
        # Define filename template
        # We'll get the final path after extraction
        output_template = os.path.join(output_path, '%(title)s - %(id)s.%(ext)s')

        # yt-dlp options
        ydl_opts = {
            'format': 'best[ext=mp4][height<=1080]/best[ext=mp4]/best',
            'outtmpl': output_template,
            # 'merge_output_format': 'mp4', # You can comment this out, it won't be used
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info (this doesn't download yet)
            info_dict = ydl.extract_info(url, download=False)
            
            # Manually trigger the download
            print(f"Downloading '{info_dict.get('title', 'video')}'...")
            ydl.download([url])
            
            # Get the final downloaded file path
            final_filename = ydl.prepare_filename(info_dict)
            
            # yt-dlp might add an extra .mp4 if it muxes, let's fix
            if not final_filename.endswith('.mp4') and os.path.exists(final_filename + '.mp4'):
                 final_filename = final_filename + '.mp4'
            elif not os.path.exists(final_filename):
                 # Handle cases where the template was already perfect
                 # Re-run prepare_filename with the actual extension
                 info_dict['ext'] = 'mp4'
                 final_filename = ydl.prepare_filename(info_dict)


        print(f"Successfully downloaded to: {final_filename}")

        return final_filename

    except yt_dlp.utils.DownloadError as e:
        print(f"yt-dlp Download Error: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

@mcp.tool()
def cut_youtube_video_into_segments(file_name: str, start_time: int, end_time: int, path: str = "."):
    """
    Cuts a video file into a segment.

    Args:
        file_name (str): The name of the video file (e.g., "video.mp4").
        start_time (int): The start time of the segment in seconds.
        end_time (int): The end time of the segment in seconds.
        path (str, optional): The directory path where the file is located.
                               Defaults to "." (current directory).
    """
    # Construct the full input file path
    input_path = os.path.join(path, file_name)

    # Process the video clip
    clip = (
        VideoFileClip(input_path)
        .subclipped(start_time, end_time)
        .with_volume_scaled(0.8)
    )

    # Create a sensible output filename
    # This splits "video.mp4" into "video" and ".mp4"
    base_name, extension = os.path.splitext(file_name)
    output_filename = f"{base_name}_trimmed_{start_time}_{end_time}{extension}"
    
    # Construct the full output file path
    output_path = os.path.join(path, output_filename)

    # Overlay the text clip on the first video clip
    final_video = CompositeVideoClip([clip])
    final_video.write_videofile(output_path)
    
    print(f"Segment saved to: {output_path}")
    return output_path

@mcp.tool
def create_new_video():
    # 1. Load your video clips
    clip1 = VideoFileClip("An old mans advice. - 9fvETktnaRw_trimmed_20_25.mp4")
    clip2 = VideoFileClip("An old mans advice. - 9fvETktnaRw_trimmed_70_75.mp4")
    # You can add as many as you want
    # clip3 = VideoFileClip("video3.mp4")

    # 2. Put the clips into a list in the order you want
    clips_list = [clip1, clip2] 

    # 3. Concatenate (stitch) the clips
    final_clip = concatenate_videoclips(clips_list)

    # 4. Write the new video file
    final_clip.write_videofile("stitched_video.mp4")

    # Optional: Close the clips to free up resources
    clip1.close()
    clip2.close()
    final_clip.close()

    print("Videos stitched successfully!")

if __name__ == "__main__":
    mcp.run(transport="http", port=8000)


