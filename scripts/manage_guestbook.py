#!/usr/bin/env python3
"""
Add an approved guestbook entry to data/guestbook.json.

When someone submits to your guestbook, you get an email from Formspree.
To approve, run:

    python scripts/manage_guestbook.py --name "John" --message "Great site!" --commit

To approve with a specific date (defaults to today):

    python scripts/manage_guestbook.py --name "John" --message "Great site!" --date 2026-07-28 --commit

The --commit flag auto-commits and pushes the updated JSON.
To reject a submission, simply ignore the email.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys


GUESTBOOK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "guestbook.json"
)


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
    parser = argparse.ArgumentParser(description="Add an approved guestbook entry.")
    parser.add_argument("--name", required=True, help="Name of the person")
    parser.add_argument("--message", required=True, help="Their message")
    parser.add_argument(
        "--date",
        default=datetime.date.today().isoformat(),
        help="Date (YYYY-MM-DD, defaults to today)",
    )
    parser.add_argument("--output", default=GUESTBOOK_PATH, help="Guestbook JSON path")
    parser.add_argument(
        "--commit", action="store_true", help="Auto-commit and push after saving"
    )
    args = parser.parse_args()

    guestbook = load_guestbook(args.output)

    guestbook["entries"].insert(0, {
        "name": args.name,
        "message": args.message,
        "date": args.date,
    })

    save_guestbook(guestbook, args.output)
    print(f'  Added entry from "{args.name}".')

    if args.commit:
        git_commit_and_push(args.output)

    print("Done!")


if __name__ == "__main__":
    main()
