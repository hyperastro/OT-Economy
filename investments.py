import json
import time
from pathlib import Path
from API import api

INVESTMENTS_PATH = Path("investments.json")
DB_PATH = Path("database.json")

# === CONSTANTS ===
TIERS = [10, 20, 30, 40, 50]

TIER_PCT = {
    10: 0.03,
    20: 0.07,
    30: 0.12,
    40: 0.25,
    50: 0.50,
}

# Full-reward window in hours per tier.
# Chosen time_limit ≤ base        -> ×1.0 reward
# base < time_limit ≤ 2×base     -> ×0.5 reward
# 2×base < time_limit ≤ 3×base   -> ×0.25 reward
# time_limit > 3×base             -> invalid (command fails)
TIER_BASE_HOURS = {
    10: 12,
    20: 24,
    30: 48,
    40: 72,
    50: 168,
}


# === DB HELPERS ===
def load_db():
    if DB_PATH.exists():
        with open(DB_PATH, "r") as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=4)


# === INVESTMENT STORAGE ===
def load_investments():
    if INVESTMENTS_PATH.exists():
        with open(INVESTMENTS_PATH, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_investments(investments):
    with open(INVESTMENTS_PATH, "w") as f:
        json.dump(investments, f, indent=4)


# === TIER UTILITIES ===
def resolve_tier(raw_tier):
    """
    Round DOWN to the nearest valid tier.
    Returns None if raw_tier < 10 or raw_tier > 50.

    Examples:
        19 -> 10
        20 -> 20
        49 -> 40
        51 -> None
    """
    if raw_tier < 10 or raw_tier > 50:
        return None
    for t in reversed(TIERS):
        if raw_tier >= t:
            return t
    return None

def get_reward_multiplier(tier, time_limit_hours):
    """
    Returns 1.0, 0.5, or 0.25 depending on how the chosen time limit
    compares to the tier's base duration. Returns None if the time limit
    exceeds the maximum allowed (3× base).
    """
    base = TIER_BASE_HOURS[tier]
    if time_limit_hours <= base:
        return 1.0
    elif time_limit_hours <= 2 * base:
        return 0.5
    elif time_limit_hours <= 3 * base:
        return 0.25
    return None   # exceeds max; command should fail


# === OSSAPI POST HELPERS ===
def _extract_user_id(post):
    """Safely pull user_id from an ossapi ForumPost object as a string."""
    uid = getattr(post, "user_id", None)
    if uid is None and hasattr(post, "user"):
        uid = getattr(post.user, "id", None)
    return str(uid) if uid is not None else None

def get_all_topic_poster_ids(topic_id):
    """
    Paginate through ALL posts in a topic and return the complete set of
    unique poster user IDs (strings). Used to snapshot the baseline at
    investment creation time so nobody already in the thread gets counted.
    """
    poster_ids = set()
    cursor_string = None

    while True:
        try:
            kwargs = {"topic_id": int(topic_id), "sort": "id_asc"}
            if cursor_string:
                kwargs["cursor_string"] = cursor_string

            topic_data = api.forum_topic(**kwargs)

            if not topic_data.posts:
                break

            for post in topic_data.posts:
                uid = _extract_user_id(post)
                if uid:
                    poster_ids.add(uid)

            cursor_string = getattr(topic_data, "cursor_string", None)
            if not cursor_string:
                break

        except Exception as e:
            print(f"Error paginating topic {topic_id} for baseline: {e}")
            break

    return poster_ids

def get_recent_unique_posters(topic_id):
    """
    Fetch the 20 most recent posts from a topic and return a deduplicated
    list of poster user ID strings. Called every tick per active investment.
    """
    try:
        topic_data = api.forum_topic(topic_id=int(topic_id), sort="id_desc")
        seen = set()
        result = []
        for post in topic_data.posts[:20]:
            uid = _extract_user_id(post)
            if uid and uid not in seen:
                seen.add(uid)
                result.append(uid)
        return result
    except Exception as e:
        print(f"Error fetching recent posters for topic {topic_id}: {e}")
        return []


# === INVESTMENT CREATION ===
def create_investment(user_id, username, topic_id, invest_amount, tier, time_limit_hours, reward_multiplier):
    """
    Validates the user's balance, snapshots the current poster baseline,
    deducts the stake, and persists the new active investment.

    Returns (True, investment_dict) on success, (False, error_string) on failure.
    """
    db = load_db()
    user = db.get(str(user_id))
    if not user:
        return False, "You are not registered."
    if user["balance"] < invest_amount:
        return False, f"Not enough OT Bucks (have {user['balance']}, need {invest_amount})."

    print(f"Snapshotting poster baseline for topic {topic_id}...")
    baseline = get_all_topic_poster_ids(topic_id)
    baseline.add(str(user_id))   # investor's own future posts never count

    investment = {
        "id": f"{user_id}_{topic_id}_{int(time.time())}",
        "user_id": str(user_id),
        "username": username,
        "topic_id": str(topic_id),
        "invest_amount": invest_amount,
        "tier": tier,
        "tier_pct": TIER_PCT[tier],
        "time_limit_hours": time_limit_hours,
        "reward_multiplier": reward_multiplier,
        "created_at": time.time(),
        "deadline": time.time() + time_limit_hours * 3600,
        "baseline_posters": list(baseline),
        "new_unique_posters": [],   # filled incrementally each tick
        "status": "active",
    }

    user["balance"] -= invest_amount
    save_db(db)

    investments = load_investments()
    investments.append(investment)
    save_investments(investments)

    return True, investment


# === RESOLUTION HELPERS ===
def _resolve(inv, db):
    """
    Resolve a single investment in-place, crediting the user's balance.
    Mutates both inv (sets status/payout/resolved_at) and db (updates balance).
    """
    user = db.get(inv["user_id"])
    if not user:
        print(f"Cannot resolve investment {inv['id']}: user not found in DB.")
        inv["status"] = "error"
        return

    new_count = len(inv["new_unique_posters"])
    tier      = inv["tier"]
    amount    = inv["invest_amount"]

    if new_count >= tier:
        # Success: return stake + scaled reward
        reward = round(amount * inv["tier_pct"] * inv["reward_multiplier"])
        payout = amount + reward
        user["balance"] += payout
        inv["status"] = "success"
        inv["payout"] = payout
        print(
            f"Investment success - {inv['username']}: "
            f"+{reward} OT Bucks reward "
            f"(tier {tier}, ×{inv['reward_multiplier']} multiplier, "
            f"{new_count}/{tier} new posters)"
        )
    else:
        # Failure: partial refund proportional to progress
        refund = round(amount * new_count / tier)
        user["balance"] += refund
        inv["status"] = "failed"
        inv["payout"] = refund
        print(
            f"Investment failed - {inv['username']}: "
            f"refunded {refund} OT Bucks "
            f"({new_count}/{tier} new posters reached)"
        )

    inv["resolved_at"] = time.time()


def _update_posters(inv):
    """
    Fetch the most recent posts from the investment's topic and add any
    new unique posters (not in baseline, not already tracked) to the list.
    Called every tick for each active investment.
    """
    baseline = set(inv["baseline_posters"])
    tracked  = set(inv["new_unique_posters"])

    for uid in get_recent_unique_posters(inv["topic_id"]):
        if uid not in baseline and uid not in tracked:
            inv["new_unique_posters"].append(uid)
            tracked.add(uid)


# === MAIN TICK FUNCTION ===
def check_investments():
    """
    Called every tick. For each active investment:
      - Updates new unique poster counts from recent posts.
      - Resolves early if the tier target has already been met.
      - Resolves at deadline if the tier was not met in time.

    Returns True if at least one investment was resolved and the DB was updated.
    """
    investments = load_investments()
    active = [inv for inv in investments if inv["status"] == "active"]
    if not active:
        return False

    now     = time.time()
    db      = load_db()
    changed = False

    for inv in investments:
        if inv["status"] != "active":
            continue

        _update_posters(inv)

        if len(inv["new_unique_posters"]) >= inv["tier"]:
            _resolve(inv, db)
            changed = True
        elif now >= inv["deadline"]:
            _resolve(inv, db)
            changed = True

    save_investments(investments)
    if changed:
        save_db(db)

    return changed
