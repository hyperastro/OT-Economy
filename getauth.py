import http.server
import socketserver
import webbrowser
import threading
import requests
import json
import time

# === CONFIG ===
CLIENT_ID = 
CLIENT_SECRET = ""
REDIRECT_URI = "http://localhost:8727"
AUTH_URL = (
    f"https://osu.ppy.sh/oauth/authorize?"
    f"client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}"
    f"&response_type=code"
    f"&scope=public+forum.write"
)
TOKEN_URL = "https://osu.ppy.sh/oauth/token"
TOKEN_FILE = "osu_token_cache.json"

# === GLOBAL ===
auth_code = None


# === SIMPLE LOCAL SERVER TO CAPTURE REDIRECT ===
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        if "/?code=" in self.path:
            auth_code = self.path.split("code=")[1].split("&")[0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = (
                "<h2>Authorization successful!</h2>"
                "<p>You can close this tab and return to your console.</p>"
            )
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_local_server():
    with socketserver.TCPServer(("localhost", 8000), Handler) as httpd:
        httpd.timeout = 300  # 5 min timeout
        while auth_code is None:
            httpd.handle_request()


# === STEP 1: OPEN OSU AUTH PAGE ===
print("Opening osu! authorization page in your browser...")
webbrowser.open(AUTH_URL)

# === STEP 2: WAIT FOR AUTH CODE ===
print("Waiting for authorization (check your browser)...")
server_thread = threading.Thread(target=start_local_server)
server_thread.start()

while auth_code is None:
    time.sleep(1)

print(f"Got authorization code: {auth_code[:10]}...")

# === STEP 3: EXCHANGE CODE FOR TOKENS ===
data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "grant_type": "authorization_code",
    "redirect_uri": REDIRECT_URI,
    "code": auth_code,
}

print("Exchanging code for access token...")
resp = requests.post(TOKEN_URL, data=data)
if resp.status_code != 200:
    print("Token exchange failed:", resp.status_code, resp.text)
    exit(1)

token_data = resp.json()
token_data["expires_at"] = time.time() + token_data["expires_in"] - 30

# === SAVE TOKENS LOCALLY ===
with open(TOKEN_FILE, "w", encoding="utf-8") as f:
    json.dump(token_data, f, indent=4)

print("Token saved to osu_token_cache.json!")
print(json.dumps(token_data, indent=2))
print("\IT FUCKING WORKED")

