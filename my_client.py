import asyncio
from fastmcp import Client

client = Client("http://localhost:8000/mcp")

async def call_tool_get_youtube_transcript(video_id: str):
    async with client:
        result = await client.call_tool("get_youtube_transcript", {"video_id": video_id})
        print(result)

async def call_download_videos_from_youtube(urls: list[str], output_path: str = "/downloads"):
    async with client:
        result = await client.call_tool("download_videos_from_youtube", {"urls": urls, "output_path": output_path})
        print(result)
        
async def call_cut_youtube_video_into_segments(file_name: str, start_time: int, end_time: int, path: str = "."):
    async with client:

        
        # Pass the tool name and its parameters
        result = await client.call_tool(
            "cut_youtube_video_into_segments", 
            {
                "file_name": file_name,
                "start_time": start_time,
                "end_time": end_time,
                "path": path
            }  # Pass the path, which defaults to "." if not provided
        )
        print(result)

async def call_create_new_video(file_paths: list, output_filename: str = "stitched_video.mp4"):
    async with client:
        result = await client.call_tool("create_new_video", {"file_paths": file_paths})
        print(result)

async def call_download_audio_for_whisper(url: str, output_path: str):
    async with client:
        result = await client.call_tool("download_audio_for_whisper", {"url": url, "output_path": output_path})
        print(result)

async def call_transcribe_with_word_timestamps(audio_path: str):
    async with client:
        result = await client.call_tool("transcribe_with_word_timestamps", {"audio_path": audio_path})
        print(result)




# Update the asyncio.run call to pass the arguments
#asyncio.run(call_transcribe_with_word_timestamps(r"C:\Users\samir\Desktop\Youtube Creator MCP\Build an MCP Server in 7 Minutes (Fast MCP Tutorial) 🚀 - qVrvtqfgPwc.mp3"))

#asyncio.run(call_tool_get_youtube_transcript("qVrvtqfgPwc"))
#asyncio.run(call_download_audio_for_whisper("qVrvtqfgPwc", "."))

asyncio.run(call_download_videos_from_youtube(["https://www.youtube.com/watch?v=9fvETktnaRw"], "."))

# asyncio.run(call_cut_youtube_video_into_segments(
#     file_name="An old mans advice. - 9fvETktnaRw.mp4",
#     start_time=30,
#     end_time=35
#     # The 'path' argument is omitted, so it will use the default "."
# ))

#asyncio.run(call_create_new_video(["An old mans advice. - 9fvETktnaRw_trimmed_10_15.mp4", "An old mans advice. - 9fvETktnaRw_trimmed_30_35.mp4"]))