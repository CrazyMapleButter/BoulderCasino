from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from twitchmain import get_balance, set_balance, award_watchtime, CLIENT_ID as BOT_CLIENT_ID, CLIENT_SECRET as BOT_CLIENT_SECRET
import random
import os
import secrets
import requests

app = Flask(__name__, static_folder="web/static", template_folder="web/templates")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-change-me")
# Ensure OAuth cookies survive cross-site redirect on HTTPS (Vercel)
app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True,
    PREFERRED_URL_SCHEME="https",
)

# Prefer web-specific OAuth credentials from env; fallback to bot creds
WEB_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID") or os.environ.get("WEB_CLIENT_ID") or BOT_CLIENT_ID
WEB_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET") or os.environ.get("WEB_CLIENT_SECRET") or BOT_CLIENT_SECRET

WEB_REDIRECT_URI = os.environ.get("WEB_REDIRECT_URI", "http://localhost:5050/auth/callback")
TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"

@app.route("/")
def index():
    return render_template("home.html")

@app.get("/slots")
def page_slots():
    return render_template("slots.html")

@app.get("/double")
def page_double():
    return render_template("double.html")

@app.get("/blackjack")
def page_blackjack():
    return render_template("blackjack.html")

@app.get("/poker")
def page_poker():
    return render_template("poker.html")

@app.get("/login")
def login():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    params = {
        "client_id": WEB_CLIENT_ID,
        "redirect_uri": WEB_REDIRECT_URI,
        "response_type": "code",
        "scope": "user:read:email",
        "state": state,
        "force_verify": "true",
    }
    from urllib.parse import urlencode
    return redirect(f"{TWITCH_AUTH_URL}?{urlencode(params)}")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.get("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state or state != session.get("oauth_state"):
        return "Invalid OAuth state", 400
    data = {
        "client_id": WEB_CLIENT_ID,
        "client_secret": WEB_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": WEB_REDIRECT_URI,
    }
    token_res = requests.post(TWITCH_TOKEN_URL, data=data)
    if token_res.status_code != 200:
        return f"Token exchange failed: {token_res.text}", 400
    tokens = token_res.json()
    access_token = tokens.get("access_token")
    headers = {"Client-ID": WEB_CLIENT_ID, "Authorization": f"Bearer {access_token}"}
    user_res = requests.get(TWITCH_USERS_URL, headers=headers)
    if user_res.status_code != 200:
        return f"Failed to fetch user: {user_res.text}", 400
    user_data = user_res.json().get("data", [])
    if not user_data:
        return "No user data returned", 400
    u = user_data[0]
    session["user"] = {
        "id": u.get("id"),
        "login": u.get("login"),
        "display_name": u.get("display_name"),
    }
    session["access_token"] = access_token
    session.pop("oauth_state", None)
    return redirect(url_for("index"))

@app.get("/api/me")
def api_me():
    try:
        user = session.get("user")
        if not user:
            return jsonify({"error": "unauthenticated"}), 401
        info = award_watchtime(user["login"])  # also ensures user record exists
        return jsonify({
            "user": user,
            "balance": int(info.get("balance", 0)),
            "debug": {"client_id_suffix": (WEB_CLIENT_ID or '')[-6:], "redirect_uri": WEB_REDIRECT_URI, "econ_file": os.path.abspath(ECON_FILE) if 'ECON_FILE' in globals() else None}
        })
    except Exception as e:
        return jsonify({"error": f"server error: {e}"}), 500

@app.post("/api/balance")
def api_balance():
    u = session.get("user")
    if not u:
        return jsonify({"error": "unauthenticated"}), 401
    info = award_watchtime(u["login"])
    return jsonify({
        "user": u,
        "balance": int(info.get("balance", 0)),
        "last_award": float(info.get("last_award", 0)),
    })

@app.post("/api/gamble")
def api_gamble():
    u = session.get("user")
    if not u:
        return jsonify({"error": "unauthenticated"}), 401
    data = request.get_json(force=True) or {}
    amount = data.get("amount")
    try:
        amount = int(amount)
    except Exception:
        return jsonify({"error": "amount must be an integer"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be > 0"}), 400

    # Award any pending hourly reward when they interact
    award_watchtime(u["login"])
    balance = get_balance(u["login"])
    if amount > balance:
        return jsonify({"error": f"insufficient balance", "balance": balance}), 400

    # 50/50 lose bet or double
    if random.random() < 0.5:
        new_balance = balance - amount
        outcome = "lose"
        delta = -amount
    else:
        new_balance = balance + amount
        outcome = "win"
        delta = amount

    set_balance(u["login"], new_balance)
    return jsonify({
        "user": u,
        "bet": amount,
        "outcome": outcome,
        "delta": delta,
        "balance": new_balance,
    })

# Slot machine settings
SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]
# Increase odds of matching triples by biasing the sampling toward a single symbol per spin
# Also slightly increase lower-tier payouts for more frequent wins
WEIGHTS = {"🍒": 8, "🍋": 7, "🔔": 5, "⭐": 3, "7️⃣": 2}
PAYOUTS = {  # multiplier on bet when 3 of a kind
    "🍒": 3,
    "🍋": 4,
    "🔔": 6,
    "⭐": 12,
    "7️⃣": 25,
}

@app.post("/api/slots/spin")
def api_slots_spin():
    u = session.get("user")
    if not u:
        return jsonify({"error": "unauthenticated"}), 401
    data = request.get_json(force=True) or {}
    bet = data.get("bet")
    try:
        bet = int(bet)
    except Exception:
        return jsonify({"error": "bet must be an integer"}), 400
    if bet <= 0:
        return jsonify({"error": "bet must be > 0"}), 400

    # Apply hourly award and check balance
    award_watchtime(u["login"])
    balance = get_balance(u["login"])
    if bet > balance:
        return jsonify({"error": "insufficient balance", "balance": balance}), 400

    # Deduct bet first
    balance -= bet

    # Spin three reels with a slight bias to all match: choose a target symbol, then sample reels with extra weight for it
    target = random.choices(SYMBOLS, weights=[WEIGHTS[s] for s in SYMBOLS], k=1)[0]
    biased_weights = {s: (WEIGHTS[s] * (3 if s == target else 1)) for s in SYMBOLS}
    reels = [
        random.choices(SYMBOLS, weights=[biased_weights[s] for s in SYMBOLS], k=1)[0]
        for _ in range(3)
    ]

    # Determine payout
    if reels[0] == reels[1] == reels[2]:
        multiplier = PAYOUTS.get(reels[0], 0)
    else:
        multiplier = 0

    payout = bet * multiplier
    balance += payout

    set_balance(u["login"], balance)

    return jsonify({
        "user": u,
        "reels": reels,
        "bet": bet,
        "multiplier": multiplier,
        "payout": payout,
        "balance": balance,
        "won": payout > 0,
    })

# -------------------- Blackjack API --------------------
import itertools

CARD_RANKS = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
CARD_VALUES = {**{r:int(r) for r in CARD_RANKS if r.isdigit()}, **{'J':10,'Q':10,'K':10,'A':11}}
SUITS = ['♠','♥','♦','♣']

def new_deck():
    deck = [f"{r}{s}" for r in CARD_RANKS for s in SUITS]
    random.shuffle(deck)
    return deck

def bj_value(hand):
    total = 0
    aces = 0
    for c in hand:
        r = c[:-1]  # rank without suit
        if r == 'A':
            aces += 1
            total += 11
        elif r in ('K','Q','J'):
            total += 10
        else:
            try:
                total += int(r)
            except Exception:
                # Fallback in case of malformed card strings
                return 0
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

@app.post("/api/blackjack/new")
def api_blackjack_new():
    u = session.get("user")
    if not u:
        return jsonify({"error": "unauthenticated"}), 401
    data = request.get_json(force=True) or {}
    bet = data.get("bet")
    try:
        bet = int(bet)
    except Exception:
        return jsonify({"error": "bet must be an integer"}), 400
    if bet <= 0:
        return jsonify({"error": "bet must be > 0"}), 400

    award_watchtime(u["login"])
    bal = get_balance(u["login"])

    # If a hand is already in progress, return it without charging another bet
    existing = session.get('bj')
    if existing and not existing.get('done'):
        masked = [existing['dealer'][0], "??"]
        return jsonify({"state": {"player": existing['player'], "dealer": masked, "bet": existing['bet'], "done": False}, "balance": bal, "hand_in_progress": True})

    if bet > bal:
        return jsonify({"error": "insufficient balance", "balance": bal}), 400

    bal -= bet
    set_balance(u["login"], bal)

    deck = new_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    state = {"deck": deck, "player": player, "dealer": dealer, "bet": bet, "done": False}

    # natural blackjack payout 3:2
    if bj_value(player) == 21:
        # dealer checks blackjack
        if bj_value(dealer) == 21:
            # push
            bal += bet
            outcome = "push"
        else:
            win = int(bet * 2.5)
            bal += win
            outcome = "blackjack"
        set_balance(u["login"], bal)
        state["done"] = True
        return jsonify({"state": {"player": player, "dealer": dealer, "bet": bet, "done": True}, "outcome": outcome, "balance": bal})

    session['bj'] = state
    return jsonify({"state": {"player": player, "dealer": [dealer[0], "??"], "bet": bet, "done": False}, "balance": bal})

@app.post("/api/blackjack/hit")
def api_blackjack_hit():
    try:
        u = session.get("user")
        if not u:
            return jsonify({"error": "unauthenticated"}), 401
        state = session.get('bj')
        if not state or state.get('done'):
            return jsonify({"error": "no active game"}), 400
        if not state.get('deck'):
            state['deck'] = new_deck()
        card = state['deck'].pop()
        state['player'].append(card)
        total = bj_value(state['player'])
        if total > 21:
            state['done'] = True
            session['bj'] = state
            # lost; bet already deducted
            bal = get_balance(u['login'])
            return jsonify({"state": {"player": state['player'], "dealer": state['dealer'], "bet": state['bet'], "done": True}, "outcome": "bust", "balance": bal})
        session['bj'] = state
        return jsonify({"state": {"player": state['player'], "dealer": [state['dealer'][0], "??"], "bet": state['bet'], "done": False}})
    except Exception as e:
        return jsonify({"error": f"server error: {e}"}), 500

@app.post("/api/blackjack/stand")
def api_blackjack_stand():
    try:
        u = session.get("user")
        if not u:
            return jsonify({"error": "unauthenticated"}), 401
        state = session.get('bj')
        if not state or state.get('done'):
            return jsonify({"error": "no active game"}), 400
        # dealer draws to 17
        if not state.get('deck'):
            state['deck'] = new_deck()
        while bj_value(state['dealer']) < 17 and state['deck']:
            state['dealer'].append(state['deck'].pop())
        player_total = bj_value(state['player'])
        dealer_total = bj_value(state['dealer'])
        bal = get_balance(u['login'])
        if dealer_total > 21 or player_total > dealer_total:
            bal += state['bet'] * 2
            outcome = "win"
        elif player_total == dealer_total:
            bal += state['bet']
            outcome = "push"
        else:
            outcome = "lose"
        set_balance(u['login'], bal)
        state['done'] = True
        session['bj'] = state
        return jsonify({"state": {"player": state['player'], "dealer": state['dealer'], "bet": state['bet'], "done": True}, "outcome": outcome, "balance": bal})
    except Exception as e:
        return jsonify({"error": f"server error: {e}"}), 500

# (Poker removed)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)
