import os
import time
import math
import asyncio
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message

API_ID_RAW = os.environ.get("API_ID", "").strip()
API_HASH = os.environ.get("API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", 8000))

API_ID = int(API_ID_RAW) if API_ID_RAW else 0

# 1. Koyeb Health Check Web Server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is active!")

    def log_message(self, format, *args):
        return

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# 2. Telegram Bot Client
app = Client("txt_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def humanbytes(size):
    if not size:
        return "0 B"
    power = 1024
    t_n = 0
    power_dict = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        t_n += 1
    return "{:.2f} {}B".format(size, power_dict.get(t_n, ''))

def time_formatter(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
        ((str(hours) + "h, ") if hours else "") + \
        ((str(minutes) + "m, ") if minutes else "") + \
        ((str(seconds) + "s, ") if seconds else "")
    return tmp[:-2] if tmp else "0s"

async def progress_for_pyrogram(current, total, ud_type, message, start, custom_title):
    now = time.time()
    diff = now - start
    if round(diff % 4.00) == 0 or current == total:
        percentage = (current * 100 / total) if total else 0
        speed = (current / diff) if diff > 0 else 0
        time_to_completion = round((total - current) / speed) if speed > 0 else 0

        progress = "[{0}{1}] \n".format(
            ''.join(["▰" for _ in range(math.floor(percentage / 10))]),
            ''.join(["▱" for _ in range(10 - math.floor(percentage / 10))])
        )

        tmp = (
            f"🎬 **{custom_title}**\n\n"
            f"{progress}📤 **{ud_type}**: {round(percentage, 2)}%\n"
            f"**Size**: {humanbytes(current)} / {humanbytes(total)}\n"
            f"**Speed**: {humanbytes(speed)}/s\n"
            f"**ETA**: {time_formatter(time_to_completion)}\n"
        )
        try:
            await message.edit_text(text=tmp)
        except Exception:
            pass

async def safe_edit_text(msg, text):
    try:
        await msg.edit_text(text)
    except Exception:
        pass

def fix_video_faststart(input_file):
    """FFmpeg se moov atom ko video ke start me move karta hai taaki direct play ho sake"""
    output_file = input_file + ".fixed.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-c", "copy",
        "-movflags", "+faststart",
        output_file
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(output_file):
            os.remove(input_file)
            os.rename(output_file, input_file)
    except Exception:
        if os.path.exists(output_file):
            os.remove(output_file)

def get_video_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        return int(float(result.stdout.strip()))
    except Exception:
        return 0

def download_video(url, output_path, status_msg, loop, custom_title):
    last_update_time = [0]

    def ytdl_hook(d):
        if d.get('status') == 'downloading':
            now = time.time()
            if now - last_update_time[0] >= 3.0:
                last_update_time[0] = now
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                speed = d.get('speed', 0) or 0
                eta = d.get('eta', 0) or 0

                percent = (downloaded / total * 100) if total else 0
                text = (
                    f"🎬 **{custom_title}**\n\n"
                    f"📥 **Downloading Lecture...**\n"
                    f"**Progress**: {percent:.2f}%\n"
                    f"**Size**: {humanbytes(downloaded)} / {humanbytes(total)}\n"
                    f"**Speed**: {humanbytes(speed)}/s\n"
                    f"**ETA**: {time_formatter(eta)}"
                )
                asyncio.run_coroutine_threadsafe(safe_edit_text(status_msg, text), loop)

    ydl_opts = {
        'outtmpl': f'{output_path}/lecture_%(id)s.%(ext)s',
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        },
        'progress_hooks': [ytdl_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        
        # Video ko Telegram in-app playable banane ke liye faststart fix karein
        fix_video_faststart(filename)
        
        duration = get_video_duration(filename) or info.get('duration', 0)
        width = info.get('width', 1280)
        height = info.get('height', 720)
        detected_title = info.get('title') or custom_title
        return filename, duration, width, height, detected_title

@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    await message.reply_text(
        "👋 **Namaste!**\n\n"
        "Mujhe `.txt` file bhejein. Format:\n"
        "`Lecture Name : https://link.com/video.mp4`\n\n"
        "Videos direct playable player format me sahi duration ke saath upload honge."
    )

@app.on_message(filters.document)
async def handle_document(client: Client, message: Message):
    doc = message.document
    if not doc.file_name.endswith(".txt"):
        await message.reply_text("Kripya keval `.txt` file hi bhejein.")
        return

    status_msg = await message.reply_text("📄 File mili, links load ho rahi hain...")
    download_dir = f"downloads/{message.from_user.id}"
    os.makedirs(download_dir, exist_ok=True)

    file_path = await message.download(file_name=f"{download_dir}/links.txt")

    items = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            clean_line = line.strip()
            if not clean_line:
                continue
            
            if "http" in clean_line:
                if ":" in clean_line and not clean_line.startswith("http"):
                    parts = clean_line.split("http", 1)
                    title = parts[0].rstrip(":").strip()
                    url = "http" + parts[1].strip()
                else:
                    url = clean_line
                    title = ""
                items.append((title, url))

    total_links = len(items)
    if total_links == 0:
        await status_msg.edit_text("❌ File mein koi valid link nahi mili.")
        if os.path.exists(file_path):
            os.remove(file_path)
        return

    await status_msg.edit_text(f"Total **{total_links}** lectures mile. Process shuru ho raha hai...")
    loop = asyncio.get_event_loop()

    for index, (given_title, url) in enumerate(items, start=1):
        display_title = given_title if given_title else f"Lecture {index}"
        try:
            await status_msg.edit_text(f"⏳ **[{index}/{total_links}]** Download shuru:\n🎬 **{display_title}**")
            
            video_file, duration, width, height, detected_title = await loop.run_in_executor(
                None, download_video, url, download_dir, status_msg, loop, display_title
            )

            final_title = given_title if given_title else detected_title

            await status_msg.edit_text(f"📤 **[{index}/{total_links}]** Upload ho raha hai:\n🎬 **{final_title}**")
            start_time = time.time()

            caption_text = (
                f"🎬 **Title**: {final_title}\n\n"
                f"📌 **Part**: {index}/{total_links}\n"
                f"⏱ **Duration**: {time_formatter(int(duration)) if duration else 'N/A'}"
            )

            await client.send_video(
                chat_id=message.chat.id,
                video=video_file,
                caption=caption_text,
                duration=int(duration) if duration else 0,
                width=int(width) if width else 1280,
                height=int(height) if height else 720,
                supports_streaming=True,
                progress=progress_for_pyrogram,
                progress_args=("Uploading Video", status_msg, start_time, final_title)
            )

            if os.path.exists(video_file):
                os.remove(video_file)

        except Exception as e:
            await message.reply_text(f"⚠️ **[{index}/{total_links}] Error:**\nTitle: `{display_title}`\nReason: `{str(e)[:200]}`")

    await status_msg.edit_text("✅ Sabhi lectures properly upload ho chuke hain!")
    if os.path.exists(file_path):
        os.remove(file_path)

if __name__ == "__main__":
    print("Telegram Bot Live & Running...", flush=True)
    app.run()
