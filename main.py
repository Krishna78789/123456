import os
import asyncio
import yt_dlp
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import Message

API_ID_RAW = os.environ.get("API_ID", "").strip()
API_HASH = os.environ.get("API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", 8000))

print("--- BOT INITIALIZING ---", flush=True)
print(f"API_ID loaded: {bool(API_ID_RAW)}", flush=True)
print(f"API_HASH loaded: {bool(API_HASH)}", flush=True)
print(f"BOT_TOKEN loaded: {bool(BOT_TOKEN)}", flush=True)

try:
    API_ID = int(API_ID_RAW)
except Exception as e:
    print(f"ERROR: API_ID galat hai (sirf numbers hone chahiye): {e}", flush=True)
    API_ID = 0

app = Client("txt_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Dummy Web Server (Koyeb Health Check)
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    server = web.Application()
    server.router.add_get("/", handle_ping)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Health-check server running on port {PORT}", flush=True)

def download_video(url, output_path):
    ydl_opts = {
        'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    print(f"Received /start from user: {message.from_user.id}", flush=True)
    await message.reply_text(
        "Namaste! Mujhe video links wali .txt file bhejein.\n"
        "File mein har line par ek link honi chahiye."
    )

@app.on_message(filters.document)
async def handle_document(client: Client, message: Message):
    doc = message.document
    if not doc.file_name.endswith(".txt"):
        await message.reply_text("Kripya keval .txt file hi bhejein.")
        return

    status_msg = await message.reply_text("File mili, links load ho rahe hain...")
    download_dir = f"downloads/{message.from_user.id}"
    os.makedirs(download_dir, exist_ok=True)

    file_path = await message.download(file_name=f"{download_dir}/links.txt")

    with open(file_path, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip() and line.strip().startswith("http")]

    total_links = len(links)
    if total_links == 0:
        await status_msg.edit_text("File mein koi valid link nahi mili.")
        if os.path.exists(file_path):
            os.remove(file_path)
        return

    await status_msg.edit_text(f"Total {total_links} links mili hain. Downloading shuru...")

    for index, url in enumerate(links, start=1):
        try:
            await status_msg.edit_text(f"[{index}/{total_links}] Download ho raha hai:\n{url}")
            loop = asyncio.get_event_loop()
            video_file = await loop.run_in_executor(None, download_video, url, download_dir)

            await status_msg.edit_text(f"[{index}/{total_links}] Upload ho raha hai...")
            await client.send_document(
                chat_id=message.chat.id,
                document=video_file,
                caption=f"Download complete ({index}/{total_links})"
            )

            if os.path.exists(video_file):
                os.remove(video_file)

        except Exception as e:
            await message.reply_text(f"[{index}/{total_links}] Error: {url}\nReason: {str(e)[:150]}")

    await status_msg.edit_text("Sabhi links process ho gayi!")
    if os.path.exists(file_path):
        os.remove(file_path)

async def main():
    await start_web_server()
    print("Telegram client start kiya ja raha hai...", flush=True)
    await app.start()
    me = await app.get_me()
    print(f"BOT SUCCESSFULLY STARTED AS: @{me.username}", flush=True)
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
