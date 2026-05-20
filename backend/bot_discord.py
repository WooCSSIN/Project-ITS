import discord
from discord.ext import commands
import requests
import logging
import os
from io import BytesIO
from dotenv import load_dotenv

load_dotenv(override=False)

# ── Cấu hình ──────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
CHATBOT_API_URL = f"{API_BASE_URL}/api/v1/chatbot/chat_no_auth"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True  # Cần bật "Message Content Intent" trên Discord Developer Portal

bot = commands.Bot(command_prefix="!", intents=intents)


# ── Events ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    logger.info("Discord bot đã sẵn sàng: %s (ID: %s)", bot.user, bot.user.id)
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="🚦 Giao thông Hà Nội"
        )
    )


async def handle_chatbot_interaction(message: discord.Message, user_text: str):
    if not user_text:
        await message.reply("👋 Xin chào! Hãy hỏi tôi về tình hình giao thông.\n"
                            "Ví dụ: *\"Đường Láng đang thế nào?\"* hoặc *\"Cho tôi xem camera Văn Quán\"*")
        return

    # Hiển thị trạng thái đang gõ
    async with message.channel.typing():
        try:
            logger.info("Nhận câu hỏi từ %s: %s", message.author, user_text)

            # Gọi API backend
            res = requests.post(
                CHATBOT_API_URL,
                json={"message": user_text},
                timeout=60
            )
            res.raise_for_status()
            data = res.json()

            logger.info("API trả về: %s", str(data)[:200])

            # ── Gửi phản hồi văn bản ──────────────────────────────────────────
            reply_text = data.get("message", "")
            if reply_text:
                # Discord hỗ trợ Markdown trực tiếp (bold, bullet, v.v.)
                # Chia nhỏ nếu > 2000 ký tự (giới hạn Discord)
                chunks = [reply_text[i:i+1900] for i in range(0, len(reply_text), 1900)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await message.reply(chunk)
                    else:
                        await message.channel.send(chunk)

            # ── Gửi ảnh camera (nếu có) ───────────────────────────────────────
            images = data.get("image", [])
            if isinstance(images, list) and images:
                for img_url in images:
                    try:
                        if isinstance(img_url, str) and img_url.startswith(("http://", "https://")):
                            img_response = requests.get(img_url, timeout=15)
                            if img_response.status_code == 200:
                                img_bytes = BytesIO(img_response.content)
                                img_bytes.seek(0)
                                await message.channel.send(
                                    file=discord.File(img_bytes, filename="camera.jpg")
                                )
                            else:
                                await message.channel.send(f"❌ Không thể tải ảnh: `{img_url}`")
                        else:
                            await message.channel.send("❌ Định dạng ảnh không hợp lệ.")
                    except Exception:
                        logger.exception("Lỗi khi gửi ảnh Discord")
                        await message.channel.send("❌ Lỗi khi xử lý ảnh camera.")

            # Nếu không có gì trả về
            if not reply_text and not images:
                await message.reply("⚠️ Không nhận được phản hồi từ hệ thống. Vui lòng thử lại.")

        except requests.exceptions.Timeout:
            await message.reply("⏱️ API phản hồi quá lâu, vui lòng thử lại sau!")
        except requests.exceptions.RequestException as e:
            logger.exception("Lỗi kết nối API chatbot")
            await message.reply(f"❌ Lỗi kết nối hệ thống: `{e}`")
        except Exception:
            logger.exception("Lỗi không mong đợi trong Discord bot")
            await message.reply("❌ Có lỗi xảy ra, vui lòng thử lại!")


@bot.event
async def on_message(message: discord.Message):
    logger.info("Nhận tin nhắn từ %s trong kênh %s: '%s'", message.author, message.channel, message.content)
    # Bỏ qua tin nhắn từ chính bot
    if message.author.bot:
        return

    # Chỉ phản hồi khi bot được @mention hoặc nhắn trong DM hoặc mention bằng role
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user in message.mentions
    
    # Kiểm tra nếu bot được ping qua role tích hợp của nó
    is_role_mentioned = False
    if message.guild:
        bot_member = message.guild.get_member(bot.user.id)
        if bot_member:
            is_role_mentioned = any(role in message.role_mentions for role in bot_member.roles)

    if not is_dm and not is_mentioned and not is_role_mentioned:
        await bot.process_commands(message)
        return

    # Lấy nội dung tin nhắn (bỏ phần @mention hoặc role mention)
    user_text = message.content
    user_text = user_text.replace(f"<@{bot.user.id}>", "")
    user_text = user_text.replace(f"<@!{bot.user.id}>", "")
    
    if message.guild and bot_member:
        for role in bot_member.roles:
            user_text = user_text.replace(f"<@&{role.id}>", "")
            
    user_text = user_text.strip()

    await handle_chatbot_interaction(message, user_text)


# ── Slash Commands ────────────────────────────────────────────────────────────
@bot.command(name="giaothong", help="Hỏi về tình trạng giao thông")
async def traffic_status(ctx: commands.Context, *, question: str = ""):
    """!giaothong <câu hỏi> - Hỏi AI về tình hình giao thông"""
    if not question:
        await ctx.reply("📝 Cú pháp: `!giaothong <câu hỏi>`\n"
                        "Ví dụ: `!giaothong Đường Láng đang kẹt không?`")
        return
    await handle_chatbot_interaction(ctx.message, question)


@bot.command(name="help_its", help="Hướng dẫn sử dụng bot")
async def help_its(ctx: commands.Context):
    embed = discord.Embed(
        title="🚦 ITS Vietnam Bot - Hướng dẫn sử dụng",
        description="Bot giám sát giao thông thông minh tích hợp AI",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="💬 Cách dùng",
        value="• **@mention** bot + câu hỏi trong bất kỳ kênh nào\n"
              "• Nhắn tin **trực tiếp (DM)** với bot\n"
              "• Dùng lệnh **`!giaothong <câu hỏi>`**",
        inline=False
    )
    embed.add_field(
        name="📋 Câu hỏi ví dụ",
        value="• *\"Đường Láng đang thế nào?\"*\n"
              "• *\"Tuyến nào đang tắc nghẽn?\"*\n"
              "• *\"Cho tôi xem camera Văn Quán\"*\n"
              "• *\"Tốc độ xe trung bình Nguyễn Trãi?\"*",
        inline=False
    )
    embed.set_footer(text="Dữ liệu cập nhật theo thời gian thực từ hệ thống camera AI")
    await ctx.reply(embed=embed)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not DISCORD_BOT_TOKEN:
        logger.warning("DISCORD_BOT_TOKEN chưa được cấu hình. Discord bot sẽ không khởi động.")
        return

    logger.info("Khởi động Discord bot...")
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
