import discord
from discord.ext import commands
import json
import os
import hashlib
import aiohttp
from discord import Webhook
import io

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "anon_data.json"
CATEGORY_NAME = "個人チャンネル"
PUBLIC_CHANNEL_ID = 1502648669772451861
PUBLIC_WEBHOOK_URL = None

# データ読み込み
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {"next_room_index": 1, "category_id": None}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_next_room_number():
    idx = data.get("next_room_index", 1)
    floor = ((idx - 1) // 9) + 1
    subroom = ((idx - 1) % 9) + 1
    room_num = f"{floor}{subroom:02d}"
    data["next_room_index"] = idx + 1
    return f"Room{room_num}"

@bot.event
async def on_ready():
    print(f"✅ 個人チャンネルBot起動！ {bot.user}")
    global PUBLIC_WEBHOOK_URL
    if "public_webhook_url" in data:
        PUBLIC_WEBHOOK_URL = data["public_webhook_url"]
        print(f"   Webhook URL復元完了")

@bot.event
async def on_member_join(member):
    if member.bot:
        return

    user_id = str(member.id)
    guild = member.guild

    if user_id in data and data[user_id].get("channel_id"):
        print(f"すでに部屋が存在: {user_id}")
        return

    category = discord.utils.get(guild.categories, id=data.get("category_id"))
    if not category:
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if not category:
            category = await guild.create_category(CATEGORY_NAME)
        data["category_id"] = category.id
        save_data()

    if user_id not in data:
        hash_val = hashlib.md5(str(member.id).encode()).hexdigest()
        letter = chr(65 + int(hash_val, 16) % 26)
        num = (int(hash_val[4:8], 16) % 99) + 1
        anon_name = f"匿名{letter}#{num:02d}"
        
        room_name = get_next_room_number()
        
        data[user_id] = {
            "anon_name": anon_name,
            "room_name": room_name,
            "channel_id": None
        }

    user_data = data[user_id]
    room_name = user_data["room_name"]
    anon_name = user_data["anon_name"]

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
    }

    channel = await category.create_text_channel(room_name, overwrites=overwrites)

    user_data["channel_id"] = channel.id
    save_data()

    await channel.send(
        f" **{room_name}** へようこそ、**{anon_name}**。\n"
        "ここで書いたことは **Botが匿名で広場に転送** されます。"
    )

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = str(message.author.id)

    if user_id in data and message.channel.id == data[user_id].get("channel_id"):
        user_data = data[user_id]
        room_name = user_data["room_name"]
        anon_name = user_data["anon_name"]
        avatar_url = f"https://robohash.org/{message.author.id}.png?set=set4"

        content = message.content
        if message.attachments:
            content = message.content

        files_to_send = []
        if message.attachments:
            for att in message.attachments:
                content += f"\n{att.url}"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(att.url) as resp:
                        if resp.status == 200:
                            file_data = await resp.read()
                            files_to_send.append(discord.File(io.BytesIO(file_data), filename=att.filename))

        try:
            await message.delete()
        except:
            pass

        if PUBLIC_CHANNEL_ID and PUBLIC_WEBHOOK_URL:
            try:
                async with aiohttp.ClientSession() as session:
                    webhook = Webhook.from_url(PUBLIC_WEBHOOK_URL, session=session)
                    display_name = f"{room_name}_user"
                    await webhook.send(
                        content=content,
                        username=display_name,
                        avatar_url=avatar_url,
                        files=files_to_send if files_to_send else None
                    )
                print(f"✅ 転送成功: {room_name}")
            except Exception as e:
                print(f"❌ 転送エラー: {e}")
    # ★★★ ここが超重要！コマンドを確実に処理する行 ★★★
    await bot.process_commands(message)

@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    global PUBLIC_WEBHOOK_URL
    if not PUBLIC_CHANNEL_ID:
        await ctx.send("❌ PUBLIC_CHANNEL_ID が設定されていません！")
        return

    public_channel = bot.get_channel(PUBLIC_CHANNEL_ID)
    if not public_channel:
        await ctx.send("❌ 公開チャンネルが見つかりません")
        return

    webhooks = await public_channel.webhooks()
    webhook = discord.utils.get(webhooks, name="個人チャンネル投稿")
    if not webhook:
        webhook = await public_channel.create_webhook(name="個人チャンネル投稿")

    PUBLIC_WEBHOOK_URL = webhook.url
    data["public_webhook_url"] = PUBLIC_WEBHOOK_URL
    save_data()

    await ctx.send(f"✅ セットアップ完了！\n公開広場でのBot名は `RoomXXX_user` になります！")

if __name__ == "__main__":
    import os
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        print("❌ TOKENが設定されていません！RailwayのVariablesでTOKENを設定してください")
        exit(1)
    bot.run(TOKEN)
