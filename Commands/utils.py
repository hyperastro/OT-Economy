import re
import time
import config
from DatabaseLogic.db import Database

"""
Shared helpers used by both economy_commands.py and entity_commands.py:
item-name validation, user registration/lookup, and stack/rarity utilities.
"""

# === ITEM NAME VALIDATION ===
def validate_item_name(name):
    """
    Returns (True, None) if the name is acceptable.
    Returns (False, reason_string) if it contains disallowed BBcode.

    [img]...[/img] is the only permitted BBcode in item names.
    Everything else — including nested tags such as
    [box], [notice], [centre], [b], [url], [color], etc. — is rejected.

    Nesting is handled by stripping [img]...[/img] first and then checking
    whether any [tag] patterns survive. A name like
    [box][img]url[/img][/box] leaves [box][/box] after stripping, which
    is caught immediately.
    """
    # Remove every [img]...[/img] pair (non-greedy so multiple tags work)
    stripped = re.sub(r'\[img\].*?\[/img\]', '', name, flags=re.DOTALL | re.IGNORECASE)

    # Any remaining [tag] or [/tag] pattern means disallowed BBcode is present
    if re.search(r'\[/?[a-zA-Z][^\]]*\]', stripped):
        return False, "Item names may not contain BBcode tags (except [img]...[/img])."

    return True, None


# === USER UTILITIES ===
def register_user(db, user_id, username):
    username = "".join(username.split())  # ✅ Removes *all* whitespace
    if str(user_id) not in db:
        db[str(user_id)] = {
            "username": username,
            "balance": 100,
            "items": [],
            "time_since_last_post": time.time(),
            "recent_post_times": []
        }
        Database.save_db(db)
        print(f"Registered {username} ({user_id})")
        return True
    print(f" {username} already registered.")
    return False

def find_user_by_name(db, username):
    username = username.strip().lower()
    for uid, user in db.items():
        if user["username"].lower() == username:
            return uid
    return None


# === ITEM STACK / RARITY UTILITIES ===
def next_stack_id(items, item_name):
    same_items = [it for it in items if it["name"].lower() == item_name.lower()]
    if not same_items:
        return "0001"
    max_id = max(int(it["stack_id"]) for it in same_items)
    return f"{max_id+1:04d}"

def next_rarity(current):
    for i, (r, cost) in enumerate(config.RARITY_ORDER):
        if r == current:
            if i + 1 < len(config.RARITY_ORDER):
                # Return next rarity, but use the current rarity's upgrade cost
                next_rarity_name = config.RARITY_ORDER[i + 1][0]
                return next_rarity_name, cost
            else:
                return None
    return None
