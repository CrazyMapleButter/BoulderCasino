import os
import json
import time
import requests
from flask import Flask, request
from twitchio.ext import commands
import threading
import random
from urllib.parse import quote

CLIENT_ID = "cdj1pz1si3fdvslio16357do6shwzb"
CLIENT_SECRET = "zr6apemk5gui5xvooxvl0p5idssa42"
BOT_USERNAME = "boonga_prime"
CHANNEL_NAME = "theswainbob"
REDIRECT_URI = "http://localhost:5050/auth/callback"
TOKEN_FILE = "tokens.json"

BANNED_WORDS = [
    "nigger",
    "nigga",
    "viewers"
]

# Economy settings for BoulderCoin
# Use /tmp on serverless platforms (e.g., Vercel) where the repo FS is read-only.
ECON_FILE = os.environ.get("ECON_FILE") or ("/tmp/bouldercoin.json" if os.environ.get("VERCEL") else "bouldercoin.json")
START_BALANCE = 100
HOURLY_REWARD = 25

# Optional Redis (Upstash) persistence via REST API (best for Vercel)
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
USE_REDIS = bool(REDIS_URL and REDIS_TOKEN)
REDIS_PREFIX = os.environ.get("BC_REDIS_PREFIX", "bc:")

# Simple JSON-backed store (local dev) or Redis (prod)

def load_economy():
    if USE_REDIS:
        # Not used in Redis mode (we fetch per-user), return empty map
        return {}
    try:
        if os.path.exists(ECON_FILE):
            with open(ECON_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ load_economy failed: {e}")
    return {}


def save_economy(data: dict):
    if USE_REDIS:
        # Not used in Redis mode
        return
    try:
        # Ensure directory exists if a nested path is used
        os.makedirs(os.path.dirname(ECON_FILE) or ".", exist_ok=True)
        with open(ECON_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        # On read-only FS, avoid crashing the request
        print(f"⚠️ save_economy failed (non-persistent env?): {e}")


def _redis_headers():
    return {"Authorization": f"Bearer {REDIS_TOKEN}"}


def _redis_get(key: str):
    try:
        r = requests.get(f"{REDIS_URL}/get/{quote(key)}", headers=_redis_headers(), timeout=5)
        js = r.json()
        return js.get("result")
    except Exception as e:
        print(f"⚠️ redis get failed: {e}")
        return None


def _redis_set(key: str, value: str):
    try:
        requests.post(f"{REDIS_URL}/set/{quote(key)}/{quote(value)}", headers=_redis_headers(), timeout=5)
    except Exception as e:
        print(f"⚠️ redis set failed: {e}")


def _user_key(name: str) -> str:
    return (name or "").lower()


def ensure_user(name: str) -> dict:
    key = _user_key(name)
    now = time.time()
    if USE_REDIS:
        rkey = f"{REDIS_PREFIX}{key}"
        raw = _redis_get(rkey)
        info = None
        if raw:
            try:
                info = json.loads(raw)
            except Exception:
                info = None
        if not info:
            info = {"balance": START_BALANCE, "last_award": now}
            _redis_set(rkey, json.dumps(info))
        return info
    # file mode
    data = load_economy()
    info = data.get(key)
    if not info:
        info = {"balance": START_BALANCE, "last_award": now}
        data[key] = info
        save_economy(data)
    return info


def award_watchtime(name: str) -> dict:
    """Award HOURLY_REWARD per full hour since last_award when the user chats."""
    key = _user_key(name)
    now = time.time()
    if USE_REDIS:
        rkey = f"{REDIS_PREFIX}{key}"
        raw = _redis_get(rkey)
        info = None
        if raw:
            try:
                info = json.loads(raw)
            except Exception:
                info = None
        if not info:
            info = {"balance": START_BALANCE, "last_award": now}
            _redis_set(rkey, json.dumps(info))
            return info
        last = info.get("last_award", now)
        elapsed = now - last
        if elapsed >= 3600:
            hours = int(elapsed // 3600)
            info["balance"] = int(info.get("balance", START_BALANCE)) + (HOURLY_REWARD * hours)
            info["last_award"] = last + (3600 * hours)
            _redis_set(rkey, json.dumps(info))
        return info
    # file mode
    data = load_economy()
    info = data.get(key)
    if not info:
        info = {"balance": START_BALANCE, "last_award": now}
        data[key] = info
        save_economy(data)
        return info
    last = info.get("last_award", now)
    elapsed = now - last
    if elapsed >= 3600:
        hours = int(elapsed // 3600)
        info["balance"] = int(info.get("balance", START_BALANCE)) + (HOURLY_REWARD * hours)
        info["last_award"] = last + (3600 * hours)
        data[key] = info
        save_economy(data)
    return info


def get_balance(name: str) -> int:
    if USE_REDIS:
        info = ensure_user(name)
        return int(info.get("balance", START_BALANCE))
    return int(ensure_user(name).get("balance", START_BALANCE))


def set_balance(name: str, new_balance: int) -> dict:
    key = _user_key(name)
    now = time.time()
    if USE_REDIS:
        rkey = f"{REDIS_PREFIX}{key}"
        info = ensure_user(name)
        info["balance"] = int(new_balance)
        if not info.get("last_award"):
            info["last_award"] = now
        _redis_set(rkey, json.dumps(info))
        return info
    data = load_economy()
    info = data.get(key, {"balance": START_BALANCE, "last_award": now})
    info["balance"] = int(new_balance)
    data[key] = info
    save_economy(data)
    return info

def save_tokens(data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)


def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None


def get_token_from_code(code):
    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    tokens = response.json()
    tokens["timestamp"] = time.time()
    save_tokens(tokens)
    return tokens


def refresh_token(refresh_token):
    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    tokens = response.json()
    tokens["timestamp"] = time.time()
    save_tokens(tokens)
    print("🔁 Token refreshed at", time.strftime("%H:%M:%S"))
    return tokens


def ensure_valid_token():
    tokens = load_tokens()
    if not tokens:
        print("🌐 No tokens found. Starting local web server for authorization...")

        app = Flask(__name__)
        code_holder = {}
        shutdown_flag = threading.Event()

        @app.route("/")
        def callback():
            code = request.args.get("code")
            if code:
                code_holder["code"] = code
                shutdown_flag.set()
                return "✅ Authorization complete! You can close this tab."
            return "❌ No code found."

        def run_server():
            app.run(host='127.0.0.1', port=3000, debug=False, use_reloader=False)

        server_thread = threading.Thread(target=run_server)
        server_thread.daemon = True
        server_thread.start()

        print("👉 Open this URL in your browser:")
        print(f"https://id.twitch.tv/oauth2/authorize"
              f"?response_type=code"
              f"&client_id={CLIENT_ID}"
              f"&redirect_uri={REDIRECT_URI}"
              f"&scope=chat:read+chat:edit+moderator:manage:chat_messages+moderator:manage:banned_users")

        shutdown_flag.wait()

        tokens = get_token_from_code(code_holder["code"])
        print("✅ Access and refresh tokens saved!")
        print("🚀 Proceeding to start bot...")

    elif time.time() - tokens.get("timestamp", 0) > 3600:
        tokens = refresh_token(tokens["refresh_token"])

    return tokens

def start_bot(tokens):
    print("🚀 Starting Twitch bot...")
    access_token = tokens["access_token"]
    print(f"🔑 Using access token: {access_token[:20]}...")
    print(f"📺 Trying to connect to channel: {CHANNEL_NAME}")

    bot = commands.Bot(
        token=access_token,
        prefix="!",
        initial_channels=[CHANNEL_NAME],
    )
    bot.access_token = access_token
    print("🤖 Bot object created, attempting connection...")

    def auto_refresh():
        while True:
            time.sleep(1800)
            current = load_tokens()
            age = time.time() - current.get("timestamp", 0)
            if age > 3.5 * 3600:
                new_tokens = refresh_token(current["refresh_token"])
                bot._http.token = new_tokens["access_token"]
                print("✅ Updated bot token in memory.")

    threading.Thread(target=auto_refresh, daemon=True).start()

    @bot.event
    async def event_ready():
        print(f"✅ Logged in as {bot.nick}")
        print(f"🔗 Connected to channels: {bot.connected_channels}")
        print(f"📺 Looking for channel: {CHANNEL_NAME}")
        
        channel = bot.get_channel(CHANNEL_NAME)
        if channel:
            print(f"✅ Found channel: {channel.name}")
        else:
            print(f"❌ Could not find channel: {CHANNEL_NAME}")
    
    @bot.event
    async def event_join(channel, user):
        print(f"👋 {user.name} joined {channel.name}")
    
    @bot.event
    async def event_part(user):
        print(f"👋 {user.name} left the channel")

    async def check_message_for_banned_words(message):
        """Check message for banned words and handle moderation"""
        if message.author.name.lower() == bot.nick.lower():
            return False
        
        message_lower = message.content.lower()
        
        for banned_word in BANNED_WORDS:
            if banned_word.lower() in message_lower:
                
                try:
                    headers = {
                        "Client-ID": CLIENT_ID,
                        "Authorization": f"Bearer {bot.access_token}",
                        "Content-Type": "application/json"
                    }
                    
                    broadcaster_response = requests.get(f"https://api.twitch.tv/helix/users?login={CHANNEL_NAME}", headers=headers)
                    moderator_response = requests.get(f"https://api.twitch.tv/helix/users?login={BOT_USERNAME}", headers=headers)
                    user_response = requests.get(f"https://api.twitch.tv/helix/users?login={message.author.name}", headers=headers)
                    
                    if (broadcaster_response.status_code == 200 and 
                        moderator_response.status_code == 200 and 
                        user_response.status_code == 200):
                        
                        broadcaster_id = broadcaster_response.json()["data"][0]["id"]
                        moderator_id = moderator_response.json()["data"][0]["id"]
                        user_id = user_response.json()["data"][0]["id"]
                        
                        timeout_url = "https://api.twitch.tv/helix/moderation/bans"
                        timeout_data = {
                            "data": {
                                "user_id": user_id,
                                "duration": 10,
                                "reason": f"Used banned word: {banned_word}"
                            }
                        }
                        
                        params = {
                            "broadcaster_id": broadcaster_id,
                            "moderator_id": moderator_id
                        }
                        
                        timeout_response = requests.post(timeout_url, headers=headers, json=timeout_data, params=params)
                        
                        if timeout_response.status_code == 200:
                            print(f"🚫 Timed out {message.author.name} for using banned word: '{banned_word}'")
                        else:
                            print(f"❌ Failed to timeout {message.author.name}: {timeout_response.text}")
                            
                        channel = bot.get_channel(CHANNEL_NAME)
                        if channel:
                            await channel.send(f"@{message.author.name} Please keep chat appropriate and follow the rules!")
                    else:
                        print(f"❌ Failed to get user IDs for timeout")
                        
                    return True
                except Exception as e:
                    print(f"❌ Failed to timeout {message.author.name}: {e}")
                    import traceback
                    traceback.print_exc()
        return False
    
    original_handle_commands = bot.handle_commands
    
    async def custom_handle_commands(message):
        was_moderated = await check_message_for_banned_words(message)
        if was_moderated:
            return
        
        await original_handle_commands(message)
    
    bot.handle_commands = custom_handle_commands
    
    @bot.event
    async def event_message(message):
        # Ignore the bot's own messages
        if message.author and message.author.name and message.author.name.lower() == bot.nick.lower():
            return
        # Award watchtime on any chat message
        try:
            award_watchtime(message.author.name)
        except Exception as e:
            print(f"⚠️ Failed awarding watchtime: {e}")
        await bot.handle_commands(message)

    @bot.command()
    async def discord(ctx):
        await ctx.send("Join our Official Discord Server!!! https://discord.gg/RjCRcnRAce")

    @bot.command()
    async def youtube(ctx):
        await ctx.send("Check out my YouTube Channel!!! https://www.youtube.com/@theswainbob")
    
    @bot.command(name="gamble")
    async def gamble(ctx, amount: str = None):
        user = ctx.author.name
        # Ensure user exists and award any pending hourly coins
        award_watchtime(user)
        balance = get_balance(user)

        if amount is None:
            await ctx.send(f"@{user} usage: !gamble <amount|all>")
            return

        amt_lower = str(amount).lower()
        if amt_lower in ("all", "max"):
            bet = balance
        else:
            try:
                bet = int(amount)
            except Exception:
                await ctx.send(f"@{user} usage: !gamble <amount|all>")
                return

        if bet <= 0:
            await ctx.send(f"@{user} bet must be a positive number.")
            return
        if bet > balance:
            await ctx.send(f"@{user} insufficient BoulderCoin. Balance: {balance}.")
            return
        
        # 50/50 chance: lose the bet or double it
        if random.random() < 0.5:
            new_balance = balance - bet
            set_balance(user, new_balance)
            await ctx.send(f"@{user} lost {bet} BoulderCoin. New balance: {new_balance}.")
        else:
            winnings = bet
            new_balance = balance + winnings
            set_balance(user, new_balance)
            await ctx.send(f"@{user} won {winnings} BoulderCoin! New balance: {new_balance}.")

    @bot.command()
    async def balance(ctx, user = None):
        username = ctx.author.name
        if user == None:
            balance = get_balance(username)
            user = ctx.author.name
            await ctx.send(f"You're current balance is {balance} BoudlerCoin")
        else:
            user = user.replace("@", "")
            balance = get_balance(user)
            await ctx.send(f"{user}'s current balance is {balance}")

    @bot.command()
    async def ihatebranson(ctx):
        branson = "brandaddy4231"
        user = ctx.author.name
        balance = get_balance(user)
        bransonbalance = get_balance(branson)
        newbalance = balance + 10
        newbalanceforbranson = bransonbalance - 10
        set_balance(user, newbalance)
        set_balance(branson, newbalanceforbranson)
        await ctx.send("Yeah I do too. He's a bitch. Y'know what I'm gonna take 10 BoulderCoins out of his pocket and give it to you. HA imagine being named Branson. Must suck.")

    @bot.event
    async def event_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            pass
        else:
            print(f"❌ Command error: {error}")
    
    @bot.command()
    async def test(ctx):
        await ctx.send(f"Hello {ctx.author.name}! Bot is working and can see your messages.")

    print(f"🚀 Connecting to Twitch as {BOT_USERNAME}...")
    
    try:
        bot.run()
    except KeyboardInterrupt:
        print("⏹️ Bot stopped by user")
    except Exception as e:
        print(f"❌ Connection error: {e}")

if __name__ == "__main__":
    print("🎯 Getting tokens...")
    tokens = ensure_valid_token()
    print("🎯 Tokens obtained, starting bot...")
    start_bot(tokens)