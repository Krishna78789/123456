import os
import asyncio
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import Message

# पर्यावरण चरों (Environment Variables) से क्रेडेंशियल्स प्राप्त करें
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

app = Client("txt_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def download_video(url, output_path):
    ydl_opts = {
        'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        return filename

@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    await message.reply_text(
        "नमस्ते! मुझे वीडियो लिंक्स वाली .txt फ़ाइल भेजें।\n"
        "फ़ाइल में हर पंक्ति (line) पर एक लिंक होना चाहिए।"
    )

@app.on_message(filters.document)
async def handle_document(client: Client, message: Message):
    doc = message.document
    if not doc.file_name.endswith(".txt"):
        await message.reply_text("कृपया केवल .txt फ़ाइल ही भेजें।")
        return

    status_msg = await message.reply_text("फ़ाइल प्राप्त हुई, लिंक्स लोड हो रहे हैं...")
    download_dir = f"downloads/{message.from_user.id}"
    os.makedirs(download_dir, exist_ok=True)

    file_path = await message.download(file_name=f"{download_dir}/links.txt")

    with open(file_path, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip() and line.strip().startswith("http")]

    total_links = len(links)
    if total_links == 0:
        await status_msg.edit_text("फ़ाइल में कोई मान्य लिंक नहीं मिली।")
        if os.path.exists(file_path):
            os.remove(file_path)
        return

    await status_msg.edit_text(f"कुल {total_links} लिंक्स मिली हैं। डाउनलोडिंग शुरू की जा रही है...")

    for index, url in enumerate(links, start=1):
        try:
            await status_msg.edit_text(f"[{index}/{total_links}] डाउनलोड हो रहा है:\n{url}")
            
            loop = asyncio.get_event_loop()
            video_file = await loop.run_in_executor(None, download_video, url, download_dir)

            await status_msg.edit_text(f"[{index}/{total_links}] अपलोड हो रहा है...")
            await client.send_document(
                chat_id=message.chat.id,
                document=video_file,
                caption=f"डाउनलोड पूर्ण ({index}/{total_links})"
            )

            if os.path.exists(video_file):
                os.remove(video_file)

        except Exception as e:
            await message.reply_text(f"[{index}/{total_links}] त्रुटि: {url}\nविवरण: {str(e)[:150]}")

    await status_msg.edit_text("सभी लिंक्स की प्रोसेसिंग पूरी हो गई!")
    if os.path.exists(file_path):
        os.remove(file_path)

if __name__ == "__main__":
    app.run()
