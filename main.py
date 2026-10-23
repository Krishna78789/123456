import os
import time
import math
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message

API_ID_RAW = os.environ.get("API_ID", "").strip()
API_HASH = os.environ.get("API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", 8000))

API_ID = int(API_ID_RAW) if API_ID_RAW else 0

# 1. Koyeb Health Check Server (Background Thread)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

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

# Upload progress updater
async def progress_for_pyrogram(current, total, ud_type, message, start):
    now = time.time()
    diff = now - start
    if round(diff % 4.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        estimated_total_time = elapsed_time + time_to_completion

        elapsed_time = time_formatter(round(elapsed_time / 1000))
        estimated_total_time = time_formatter(round(estimated_total_time / 1000))

        progress = "[{0}{1}] \n".format(
            ''.join(["▰" for i in range(math.floor(percentage / 10))]),
            ''.join(["▱" for i in range(10 - math.floor(percentage / 10))])
        )

        tmp = progress + f"**{ud_type}**: {round(percentage, 2)}%\n" + \
            f"**Size**: {humanbytes(current)} / {humanbytes(total)}\n" + \
            f"**Speed**: {humanbytes(speed)}/s\n" + \
            f"**ETA**: {estimated_total_time if estimated_total_time else '0s'}\n"
        try:
            await message.edit_text(text=tmp)
        except Exception:
            pass

def download_video(url, output_path, status_msg, loop):
    last_update_time = [0]

    def ytdl_hook(d):
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_update_time[0] >= 3.0:  # Har 3 second mein update
                last_update_time[0] = now
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                speed = d.get('speed', 0) or 0
                eta = d.get('eta', 0) or 0

                percent = (downloaded / total * 100) if total else 0
                text = (
                    f"📥 **Downloading Video...**\n\n"
                    f"**Progress**: {percent:.2f}%\n"
                    f"**Size**: {humanbytes(downloaded)} / {humanbytes(total)}\n"
                    f"**Speed**: {humanbytes(speed)}/s\n"
                    f"**ETA**: {time_formatter(eta)}"
                )
                asyncio.run_coroutine_threadsafe(status_msg.edit_text(text), loop)

    ydl_opts = {
        'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [ytdl_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        # Agar extension mkv ya koi aur ho toh mp4 ensure karein
        duration = info.get('duration', 0)
        width = info.get('width', 0)
        height = info.get('height', 0)
        title = info.get('title', 'Video')
        return filename, duration, width, height, title

@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    await message.reply_text(
        "👋 **Namaste!**\n\n"
        "Mujhe video links wali `.txt` file bhejein.\n"
        "File mein har line par ek link honi chahiye.\n\n"
        "Mein real-time download/upload status ke saath video player format mein lectures bhej dunga."
    )

@app.on_message(filters.document)
async def handle_document(client: Client, message: Message):
    doc = message.document
    if not doc.file_name.endswith(".txt"):
        await message.reply_text("Kripya keval `.txt` file hi bhejein.")
        return

    status_msg = await message.reply_text("📄 Text file mili, links read kar raha hu...")
    download_dir = f"downloads/{message.from_user.id}"
    os.makedirs(download_dir, exist_ok=True)

    file_path = await message.download(file_name=f"{download_dir}/links.txt")

    with open(file_path, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip() and line.strip().startswith("http")]

    total_links = len(links)
    if total_links == 0:
        await status_msg.edit_text("❌ File mein koi valid link nahi mili.")
        if os.path.exists(file_path):
            os.remove(file_path)
        return

    await status_msg.edit_text(f"Total **{total_links}** links mili hain. Process shuru ho raha hai...")
    loop = asyncio.get_event_loop()

    for index, url in enumerate(links, start=1):
        try:
            await status_msg.edit_text(f"⏳ **[{index}/{total_links}]** Downloading shuru ho rahi hai:\n`{url}`")
            
            # Download with progress
            video_file, duration, width, height, title = await loop.run_in_executor(
                None, download_video, url, download_dir, status_msg, loop
            )

            await status_msg.edit_text(f"📤 **[{index}/{total_links}]** Telegram par video upload ho rahi hai...")
            start_time = time.time()

            # send_video use kiya hai taaki Telegram media player mein stream ho sake
            await client.send_video(
                chat_id=message.chat.id,
                video=video_file,
                caption=f"🎥 **{title}**\n\nPart: {index}/{total_links}",
                duration=int(duration) if duration else 0,
                width=int(width) if width else 0,
                height=int(height) if height else 0,
                supports_streaming=True,
                progress=progress_for_pyrogram,
                progress_args=("Uploading Video", status_msg, start_time)
            )

            if os.path.exists(video_file):
                os.remove(video_file)

        except Exception as e:
            await message.reply_text(f"⚠️ **[{index}/{total_links}] Error:**\nLink: `{url}`\nReason: `{str(e)[:200]}`")

    await status_msg.edit_text("✅ Sabhi videos process aur upload ho chuki hain!")
    if os.path.exists(file_path):
        os.remove(file_path)

if __name__ == "__main__":
    print("Telegram Bot Live & Running...", flush=True)
    app.run()
