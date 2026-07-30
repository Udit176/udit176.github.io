#!/usr/bin/env python3
"""
Fetch Spotify liked songs and save as a static JSON file.

By default, performs an incremental update: loads the existing JSON,
fetches only songs added after the most recent entry, and prepends them.
Pass --full to re-fetch the entire library from scratch.

Usage:
    1. Create a Spotify app at https://developer.spotify.com/dashboard
    2. Set redirect URI to http://127.0.0.1:8888/callback
    3. Copy your Client ID
    4. Run: python scripts/fetch_spotify.py --client-id YOUR_CLIENT_ID
    5. A browser window opens — log in and authorize
    6. The script fetches new liked songs and updates data/spotify_likes.json
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
import time
import urllib.error
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


def parse_track(item):
    track = item["track"]
    artists = ", ".join(a["name"] for a in track["artists"])
    album_images = track["album"]["images"]
    art = album_images[2]["url"] if len(album_images) > 2 else (album_images[0]["url"] if album_images else "")
    return {
        "title": track["name"],
        "artist": artists,
        "album": track["album"]["name"],
        "url": track["external_urls"].get("spotify", ""),
        "art": art,
        "added_at": item["added_at"],
    }


def api_request(url, token, max_retries=5):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", 2 ** attempt))
                print(f"\n  Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Still rate-limited after {max_retries} retries")


def fetch_liked_songs(token, stop_at=None):
    """Fetch liked songs from Spotify. If stop_at is set, stop when we
    reach a song with that added_at timestamp (incremental mode)."""
    songs = []
    url = "https://api.spotify.com/v1/me/tracks?limit=50"
    stopped_early = False

    while url:
        data = api_request(url, token)

        for item in data["items"]:
            if stop_at and item["added_at"] <= stop_at:
                stopped_early = True
                break
            songs.append(parse_track(item))

        if stopped_early:
            break

        url = data.get("next")
        if url:
            sys.stdout.write(f"\r  Fetched {len(songs)} songs...")
            sys.stdout.flush()

    print(f"\r  Fetched {len(songs)} {'new ' if stop_at else ''}songs.")
    return songs


def load_existing(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_json(songs, path):
    from datetime import date
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"count": len(songs), "last_updated": date.today().isoformat(), "songs": songs}, f, indent=2)
    print(f"  Saved {len(songs)} songs to {path}")


def git_commit_and_push(path):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    rel_path = os.path.relpath(path, repo_root)
    subprocess.run(["git", "add", rel_path], cwd=repo_root, check=True)
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_root,
    )
    if result.returncode == 0:
        print("  No changes to commit.")
        return
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
    parser.add_argument("--full", action="store_true", help="Re-fetch entire library instead of incremental update")
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

    existing = load_existing(args.output)
    stop_at = None
    if not args.full and existing and existing.get("songs"):
        newest = max(s["added_at"] for s in existing["songs"] if s.get("added_at"))
        stop_at = newest
        print(f"Incremental mode: fetching songs added after {newest}")
    else:
        print("Full fetch: downloading entire library...")

    new_songs = fetch_liked_songs(token, stop_at=stop_at)

    if stop_at and existing:
        all_songs = new_songs + existing["songs"]
    else:
        all_songs = new_songs

    save_json(all_songs, args.output)

    if args.commit:
        git_commit_and_push(args.output)

    print("Done!")


if __name__ == "__main__":
    main()
