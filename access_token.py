import requests

CLIENT_ID = "cdj1pz1si3fdvslio16357do6shwzb"
CLIENT_SECRET = "uiz6vubfppg17lc2j9d4rxi2a2ru02"
CODE = "oecv2v9ngulblaxc340ia0dmefpbpm"
REDIRECT_URI = "http://localhost:3000"

url = "https://id.twitch.tv/oauth2/token"

data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code": CODE,
    "grant_type": "authorization_code",
    "redirect_uri": REDIRECT_URI
}

response = requests.post(url, data=data)
response.raise_for_status()
tokens = response.json()

print("✅ Access token:", tokens.get("access_token"))
print("🔁 Refresh token:", tokens.get("refresh_token"))
print("🕓 Expires in:", tokens.get("expires_in"), "seconds")
print("📜 Scopes:", tokens.get("scope"))