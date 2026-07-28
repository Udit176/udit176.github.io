#!/usr/bin/env python3
"""
Review and approve/reject guestbook submissions from Formspree.

Usage:
    1. Create a Formspree form at https://formspree.io
    2. Copy your Form ID (e.g. xrgbkwyz) and API key from Settings > API
    3. Run: python scripts/manage_guestbook.py --form-id YOUR_FORM_ID --api-key YOUR_API_KEY
    4. Review each submission: approve (a), reject (r), or skip (s)
    5. Approved entries are added to data/guestbook.json
    6. Rejected entries are deleted from Formspree
    7. Pass --commit to auto-commit and push
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request


GUESTBOOK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "guestbook.json"
)
API_BASE = "https://formspree.io/api/0/forms"


def api_request(url, api_key, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "Bearer " + api_key)
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 204:
                return None
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  API error: {e.code} {e.reason}")
        try:
            print(f"  {e.read().decode()}")
        except Exception:
            pass
        return None


def fetch_submissions(form_id, api_key):
    url = f"{API_BASE}/{form_id}/submissions"
    result = api_request(url, api_key)
    if result and "submissions" in result:
        return result["submissions"]
    return []


def delete_submission(form_id, api_key, submission_id):
    url = f"{API_BASE}/{form_id}/submissions/{submission_id}"
    api_request(url, api_key, method="DELETE")


def load_guestbook(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"entries": []}


def save_guestbook(data, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved to {path}")


def git_commit_and_push(path):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    rel_path = os.path.relpath(path, repo_root)
    subprocess.run(["git", "add", rel_path], cwd=repo_root, check=True)
    guestbook = json.loads(open(path).read())
    count = len(guestbook["entries"])
    subprocess.run(
        ["git", "commit", "-m", f"Update guestbook ({count} entries)"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(["git", "push"], cwd=repo_root, check=True)
    print("  Committed and pushed.")


def main():
    parser = argparse.ArgumentParser(description="Review guestbook submissions.")
    parser.add_argument("--form-id", required=True, help="Formspree form ID")
    parser.add_argument("--api-key", required=True, help="Formspree API key")
    parser.add_argument("--output", default=GUESTBOOK_PATH, help="Guestbook JSON path")
    parser.add_argument(
        "--commit", action="store_true", help="Auto-commit and push after saving"
    )
    args = parser.parse_args()

    print("Fetching submissions from Formspree...")
    submissions = fetch_submissions(args.form_id, args.api_key)

    if not submissions:
        print("No pending submissions.")
        return

    print(f"Found {len(submissions)} submission(s).\n")

    guestbook = load_guestbook(args.output)
    approved_count = 0
    rejected_count = 0

    for i, sub in enumerate(submissions):
        sub_id = sub.get("_id", "unknown")
        name = sub.get("name", "(no name)")
        message = sub.get("message", "(no message)")
        date = sub.get("_date", "")
        if date:
            date = date.split("T")[0]

        print(f"--- Submission {i + 1}/{len(submissions)} ---")
        print(f"  Name:    {name}")
        print(f"  Message: {message}")
        print(f"  Date:    {date}")
        print()

        while True:
            choice = input("  [a]pprove / [r]eject / [s]kip: ").strip().lower()
            if choice in ("a", "r", "s"):
                break
            print("  Please enter a, r, or s.")

        if choice == "a":
            guestbook["entries"].insert(0, {
                "name": name,
                "message": message,
                "date": date,
            })
            delete_submission(args.form_id, args.api_key, sub_id)
            approved_count += 1
            print("  Approved.\n")
        elif choice == "r":
            delete_submission(args.form_id, args.api_key, sub_id)
            rejected_count += 1
            print("  Rejected and deleted.\n")
        else:
            print("  Skipped.\n")

    if approved_count > 0:
        save_guestbook(guestbook, args.output)

    print(f"Done! Approved: {approved_count}, Rejected: {rejected_count}")

    if args.commit and approved_count > 0:
        git_commit_and_push(args.output)


if __name__ == "__main__":
    main()
