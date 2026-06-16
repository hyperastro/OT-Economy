import json
import time
from pathlib import Path

DB_PATH = Path("database.json")
BLACKLISTED_ITEMS = []  # example blacklist


def load_db():
    """Load the JSON database into memory."""
    if DB_PATH.exists():
        with open(DB_PATH, "r") as f:
            return json.load(f)
    return {}


def save_db(db):
    """Write current DB state to disk."""
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=4)


def register_user(db, user_id, username):
    """Create a new user entry if not exists."""
    username = username.strip()
    if str(user_id) not in db:
        db[str(user_id)] = {
            "username": username,
            "balance": 0,
            "items": [],
            "time_since_last_post": time.time()
        }
        save_db(db)
        print(f"Registered {username} ({user_id})")
        return True
    print(f"{username} already registered.")
    return False


def find_user_by_name(db, username):
    """Find a user ID by username (case-insensitive)."""
    username = username.strip().lower()
    for uid, user in db.items():
        if user["username"].lower() == username:
            return uid
    return None


def next_stack_id(items, item_name):
    """Generate next stack ID for an item type."""
    same_items = [it for it in items if it["name"] == item_name]
    if not same_items:
        return "0001"
    max_id = max(int(it["stack_id"]) for it in same_items)
    return f"{max_id+1:04d}"
