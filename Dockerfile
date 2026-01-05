# Use Python 3.11 slim image
FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg (required for video processing)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install heavy PyTorch dependencies first (CPU-only version is ~600MB smaller than GPU)
# These rarely change, so cache them in a separate layer
RUN pip install --no-cache-dir \
    torch torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

# Install other heavy dependencies in separate layer for caching
RUN pip install --no-cache-dir \
    whisper-timestamped \
    moviepy \
    silero-vad \
    onnxruntime \
    yt-dlp

# Copy and install remaining requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy font and app code
COPY JosefinSlab-Bold.ttf .
COPY server.py .

# Expose port (for HTTP transport if used)
EXPOSE 8000

CMD ["python", "server.py"]