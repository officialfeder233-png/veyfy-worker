FROM python:3.11-slim

# Install ffmpeg (needed for audio conversion) and yt-dlp dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Update yt-dlp to latest version at build time
RUN yt-dlp --update-to stable || true

COPY . .

ENV PORT=8000
EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "360", "--workers", "2", "main:app"]
