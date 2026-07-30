#!/usr/bin/env python3
"""
Fetch all Spotify liked songs and save as a static JSON file.

Usage:
    1. Create a Spotify app at https://developer.spotify.com/dashboard
    2. Set redirect URI to http://127.0.0.1:8888/callback
    3. Copy your Client ID
    4. Run: python scripts/fetch_spotify.py --client-id YOUR_CLIENT_ID
    5. A browser window opens — log in and authorize
    6. The script fetches all liked songs and writes data/spotify_likes.json
    7. Optionally pass --commit to auto-commit and push the updated JSON
"""

import argparse
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "user-library-read"
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "spotify_likes.json")

auth_code = None
server_ready = threading.Event()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Authenticated! You can close this tab.</h2></body></html>")
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Authentication failed.</h2></body></html>")

    def log_message(self, format, *args):
        pass


def generate_pkce():
    verifier = secrets.token_urlsafe(96)
    digest = hashlib.sha256(verifier.encode()).digest()
    import base64
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def get_auth_url(client_id, challenge):
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    })
    return f"https://accounts.spotify.com/authorize?{params}"


def exchange_code(client_id, code, verifier):
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }).encode()

    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


def fetch_liked_songs(token):
    songs = []
    url = "https://api.spotify.com/v1/me/tracks?limit=50"

    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        for item in data["items"]:
            track = item["track"]
            artists = ", ".join(a["name"] for a in track["artists"])
            album_images = track["album"]["images"]
            art = album_images[2]["url"] if len(album_images) > 2 else (album_images[0]["url"] if album_images else "")

            songs.append({
                "title": track["name"],
                "artist": artists,
                "album": track["album"]["name"],
                "url": track["external_urls"].get("spotify", ""),
                "art": art,
                "added_at": item["added_at"],
            })

        url = data.get("next")
        if url:
            sys.stdout.write(f"\r  Fetched {len(songs)} songs...")
            sys.stdout.flush()

    print(f"\r  Fetched {len(songs)} songs total.")
    return songs


def save_json(songs, path):
    from datetime import date
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"count": len(songs), "last_updated": date.today().isoformat(), "songs": songs}, f, indent=2)
    print(f"  Saved to {path}")


def git_commit_and_push(path):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    rel_path = os.path.relpath(path, repo_root)
    subprocess.run(["git", "add", rel_path], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"Update Spotify liked songs ({json.loads(open(path).read())['count']} tracks)"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(["git", "push"], cwd=repo_root, check=True)
    print("  Committed and pushed.")


def main():
    parser = argparse.ArgumentParser(description="Fetch Spotify liked songs to static JSON.")
    parser.add_argument("--client-id", required=True, help="Spotify app Client ID")
    parser.add_argument("--output", default=OUTPUT_PATH, help="Output JSON path")
    parser.add_argument("--commit", action="store_true", help="Auto-commit and push after saving")
    args = parser.parse_args()

    verifier, challenge = generate_pkce()

    server = http.server.HTTPServer(("127.0.0.1", 8888), CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    auth_url = get_auth_url(args.client_id, challenge)
    print("Opening browser for Spotify login...")
    webbrowser.open(auth_url)

    thread.join(timeout=120)
    server.server_close()

    if not auth_code:
        print("Error: No authorization code received. Try again.")
        sys.exit(1)

    print("Exchanging code for access token...")
    token = exchange_code(args.client_id, auth_code, verifier)

    print("Fetching liked songs...")
    songs = fetch_liked_songs(token)

    save_json(songs, args.output)

    if args.commit:
        git_commit_and_push(args.output)

    print("Done!")


if __name__ == "__main__":
    main()
