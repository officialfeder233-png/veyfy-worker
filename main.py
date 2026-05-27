import os
import re
import json
import tempfile
import subprocess
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
WORKER_SECRET = os.environ.get("WORKER_SECRET", "")

def check_auth(req):
    return req.headers.get("X-Worker-Secret") == WORKER_SECRET

def upload_to_catbox(filepath: str) -> str:
    """Upload a file to catbox.moe and return the URL."""
    with open(filepath, "rb") as f:
        response = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=120,
        )
    response.raise_for_status()
    url = response.text.strip()
    if not url.startswith("https://"):
        raise Exception(f"Catbox returned unexpected response: {url}")
    return url

def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name).strip()[:80]

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/download", methods=["POST"])
def download():
    if not check_auth(request):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    youtube_id = data.get("youtubeId")
    title = data.get("title", "Unknown Title")
    artist = data.get("artist", "Unknown Artist")
    cover_url = data.get("coverUrl")

    if not youtube_id:
        return jsonify({"error": "youtubeId is required"}), 400

    url = f"https://www.youtube.com/watch?v={youtube_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = os.path.join(tmpdir, "%(title)s.%(ext)s")

        # Step 1: Download audio as mp3 via yt-dlp
        # --match-filter to avoid age-restricted or premium content
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",          # best quality
            "--embed-thumbnail",              # embed cover if available
            "--add-metadata",
            "--output", out_template,
            "--no-warnings",
            "--quiet",
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            print("yt-dlp stderr:", result.stderr)
            return jsonify({"error": f"yt-dlp failed: {result.stderr[:300]}"}), 500

        # Find the downloaded mp3
        mp3_files = [f for f in os.listdir(tmpdir) if f.endswith(".mp3")]
        if not mp3_files:
            return jsonify({"error": "No mp3 file found after download"}), 500

        mp3_path = os.path.join(tmpdir, mp3_files[0])

        # Step 2: Try to read metadata from the file to get accurate title/artist
        detected_title = title
        detected_artist = artist
        duration = None

        try:
            probe_cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", mp3_path
            ]
            probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
            if probe.returncode == 0:
                info = json.loads(probe.stdout)
                tags = info.get("format", {}).get("tags", {})
                detected_title = tags.get("title") or tags.get("TITLE") or title
                detected_artist = tags.get("artist") or tags.get("ARTIST") or artist
                duration_str = info.get("format", {}).get("duration")
                if duration_str:
                    duration = int(float(duration_str))
        except Exception as e:
            print(f"ffprobe warning: {e}")

        # Step 3: Upload to catbox.moe
        try:
            audio_url = upload_to_catbox(mp3_path)
        except Exception as e:
            return jsonify({"error": f"Catbox upload failed: {str(e)}"}), 500

    return jsonify({
        "success": True,
        "audioUrl": audio_url,
        "detectedTitle": detected_title,
        "detectedArtist": detected_artist,
        "duration": duration,
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
