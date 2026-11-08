"""YouTube search and MP3 stream for the TV box; runs on a residential IP that YouTube does not block."""
import json
import re
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8788


def search(query):
    lines = subprocess.run(
        ["yt-dlp", "--no-warnings", "--no-cache-dir", "--flat-playlist", "--print", "%(id)s|%(title)s", f"ytsearch1:{query}"],
        capture_output=True, text=True, timeout=30,
    ).stdout.strip().splitlines()
    if not lines or "|" not in lines[0]:
        return None
    video_id, title = lines[0].split("|", 1)
    return {"id": video_id, "title": title}


def probe_audio(video_id):
    result = subprocess.run(
        ["yt-dlp", "--no-warnings", "--no-cache-dir", "--get-url",
         "-f", "bestaudio[ext=m4a]/bestaudio", f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("audio source unavailable")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/health":
            return self.send_json(200, {"ok": True})
        if url.path == "/search":
            query = urllib.parse.parse_qs(url.query).get("q", [""])[0].strip()
            if not query:
                return self.send_json(400, {"error": "missing q"})
            result = search(query)
            if not result:
                return self.send_json(404, {"error": "not found"})
            try:
                probe_audio(result["id"])
            except Exception as error:
                return self.send_json(503, {"error": str(error)})
            return self.send_json(200, result)
        if url.path.startswith("/stream/"):
            return self.stream(url.path.split("/")[2])
        self.send_json(404, {"error": "not found"})

    def stream(self, video_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
            return self.send_json(400, {"error": "bad id"})
        downloader = subprocess.Popen(
            ["yt-dlp", "--no-warnings", "--no-cache-dir", "-q", "-f", "bestaudio[ext=m4a]/bestaudio", "-o", "-",
             f"https://www.youtube.com/watch?v={video_id}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        encoder = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-vn", "-f", "mp3", "-b:a", "128k", "pipe:1"],
            stdin=downloader.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        downloader.stdout.close()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.end_headers()
        try:
            while chunk := encoder.stdout.read(16384):
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            for process in (encoder, downloader):
                process.kill()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
