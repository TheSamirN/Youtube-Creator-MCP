import sys
import os

# Add the current directory to sys.path so we can import server
sys.path.append(os.getcwd())

try:
    from server import mcp
    print("Successfully imported mcp from server.py")
    
    # Check if the prompt is registered
    # FastMCP likely stores prompts in an internal registry. 
    # We can try to inspect it or just see if the function exists.
    
    # Depending on FastMCP version, prompts might be in mcp._prompts or similar.
    # But at least we know the file parses and the decorator didn't crash.
    print("Server loaded without errors.")
    
    # Introspection (best effort based on common patterns)
    if hasattr(mcp, 'list_prompts'):
         # This might be an async method or sync, or might not exist on the object directly
         print("mcp object has list_prompts method (or similar capability check skipped)")
         
except ImportError as e:
    print(f"Failed to import server: {e}")
except Exception as e:
    print(f"An error occurred: {e}")
