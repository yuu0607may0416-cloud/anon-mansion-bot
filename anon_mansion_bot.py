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

# データ読み込み（エラーが起きても初期値で起動する）
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"next_room_index": 1, "category_id": None}
    return {"next_room_index": 1, "category_id": None}

data = load_data()

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ★自己修復機能1: Discordに実在するチャンネルを数えて次の部屋番号を出す
async def get_next_room_name(guild):
    category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    max_idx = 0
    if category:
        for channel in category.text_channels:
            # Discordのチャンネル名(小文字)から数字だけを抽出
            name = channel.name.replace("-", "").lower()
            if name.startswith("room"):
                num_str = name.replace("room", "")
                if num_str.isdigit() and len(num_str) >= 3:
                    floor = int(num_str[:-2])
                    subroom = int(num_str[-2:])
                    # 番号をインデックスに逆算して最大値を探す
                    idx = (floor - 1) * 9 + subroom
                    if idx > max_idx:
                        max_idx = idx
                        
    next_idx = max_idx + 1
    
    # JSONの記録が生きている場合は大きい方を優先してバグを防ぐ
    json_idx = data.get("next_room_index", 1)
    if json_idx > next_idx:
        next_idx = json_idx
        
    floor = ((next_idx - 1) // 9) + 1
    subroom = ((next_idx - 1) % 9) + 1
    
    data["next_room_index"] = next_idx + 1
    save_data()
    
    return f"Room{floor}{subroom:02d}"

@bot.event
async def on_ready():
    print(f"✅ 個人チャンネルBot起動！ {bot.user}")
    global PUBLIC_WEBHOOK_URL
    
    # ★自己修復機能3: Webhook設定が消えていたらDiscordから探し出して復元
    if "public_webhook_url" in data:
        PUBLIC_WEBHOOK_URL = data["public_webhook_url"]
        print(f"   Webhook URLをファイルから復元完了")
    elif PUBLIC_CHANNEL_ID:
        public_channel = bot.get_channel(PUBLIC_CHANNEL_ID)
        if public_channel:
            webhooks = await public_channel.webhooks()
            webhook = discord.utils.get(webhooks, name="個人チャンネル投稿")
            if webhook:
                PUBLIC_WEBHOOK_URL = webhook.url
                data["public_webhook_url"] = PUBLIC_WEBHOOK_URL
                save_data()
                print(f"   ⚠️ ファイル消失を検知。DiscordからWebhookを自動復旧しました")

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
        hash_val = hashlib.md5(user_id.encode()).hexdigest()
        letter = chr(65 + int(hash_val, 16) % 26)
        num = (int(hash_val[4:8], 16) % 99) + 1
        anon_name = f"匿名{letter}#{num:02d}"
        
        # 修正：実在する最大の部屋の「次」を計算して作成する
        room_name = await get_next_room_name(guild)
        
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

    # ★自己修復機能2: 過去のユーザーデータが消失していても、自分の部屋で発言した瞬間に復元
    if user_id not in data and isinstance(message.channel, discord.TextChannel):
        if message.channel.category and message.channel.category.name == CATEGORY_NAME:
            hash_val = hashlib.md5(user_id.encode()).hexdigest()
            letter = chr(65 + int(hash_val, 16) % 26)
            num = (int(hash_val[4:8], 16) % 99) + 1
            anon_name = f"匿名{letter}#{num:02d}"
            
            # チャンネル名（room101）から表示名（Room101）を復元
            raw_name = message.channel.name.replace("-", "")
            room_name = raw_name.capitalize() if raw_name.startswith("room") else raw_name

            data[user_id] = {
                "anon_name": anon_name,
                "room_name": room_name,
                "channel_id": message.channel.id
            }
            save_data()
            print(f"🔄 ユーザーデータを自動復旧しました: {room_name}")

    if user_id in data and message.channel.id == data[user_id].get("channel_id"):
        user_data = data[user_id]
        room_name = user_data["room_name"]
        anon_name = user_data["anon_name"]
        avatar_url = f"https://robohash.org/{message.author.id}.png?set=set4"

        content = message.content

        # 添付ファイルのダウンロード処理
        files_to_send = []
        if message.attachments:
            async with aiohttp.ClientSession() as session:
                for att in message.attachments:
                    try:
                        async with session.get(att.url) as resp:
                            if resp.status == 200:
                                file_data = await resp.read()
                                files_to_send.append(
                                    discord.File(io.BytesIO(file_data), filename=att.filename)
                                )
                    except Exception as e:
                        print(f"⚠️ ファイルのダウンロード失敗: {e}")

        try:
            await message.delete()
        except:
            pass

        if PUBLIC_CHANNEL_ID and PUBLIC_WEBHOOK_URL:
            try:
                async with aiohttp.ClientSession() as session:
                    webhook = Webhook.from_url(PUBLIC_WEBHOOK_URL, session=session)
                    display_name = f"{room_name}_user"
                    
                    send_kwargs = {
                        "username": display_name,
                        "avatar_url": avatar_url
                    }
                    
                    send_content = content if content else None
                    
                    if files_to_send:
                        await webhook.send(
                            content=send_content,
                            username=display_name,
                            avatar_url=avatar_url,
                            files=files_to_send
                        )
                    elif send_content:
                        await webhook.send(
                            content=send_content,
                            username=display_name,
                            avatar_url=avatar_url
                        )
                        
                print(f"✅ 転送成功: {room_name}")
            except Exception as e:
                print(f"❌ 転送エラー: {e}")

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
