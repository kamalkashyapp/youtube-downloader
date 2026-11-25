FROM python:3.11-slim

# Install system dependencies (FFmpeg and Node.js for yt-dlp JavaScript challenge solving)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Set default port
ENV PORT=10000
ENV PYTHONUNBUFFERED=1

EXPOSE 10000

CMD ["python", "app.py"]
