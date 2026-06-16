import json
import random
import time
import math
from pathlib import Path

DB_PATH = Path("database.json")
INTRO_PATH = Path("post_intro.txt")
STATE_PATH = Path("bot_state.json")
TICKS_PER_WEEK = 40320
TAX_RATE = 0.03
TAX_THRESHOLD = 10000






def load_db():
    if DB_PATH.exists():
        with open(DB_PATH, "r") as f:
            return json.load(f)
    return {}


def save_db(db):
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=4)

def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"tick_count": 0}

def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=4)

def apply_wealth_tax_tick_based(current_tick):
    """
    Applies a 3% wealth tax every 40,320 ticks (~once per week)
    to all users with >10,000 OT Bucks.
    """
    if current_tick % TICKS_PER_WEEK != 0:
        return  # Not a tax tick yet

    db = load_db()
    taxed_users = []

    for uid, user in db.items():
        balance = user.get("balance", 0)
        if balance > TAX_THRESHOLD:
            tax_amount = round(balance * TAX_RATE)
            user["balance"] -= tax_amount
            taxed_users.append((user["username"], tax_amount))
            print(f" Wealth tax: {user['username']} paid {tax_amount} OT Bucks (3%)")

    if taxed_users:
        save_db(db)
        print(f"Applied wealth tax to {len(taxed_users)} users this week.")
    else:
        print("No users eligible for wealth tax this week.")


def calculate_reward_probability(seconds_since_last_post, tau=7200):
    """
    Exponential probability curve.
    τ (tau) ~ average interval before good chance of reward (in seconds).
    Returns probability between 0 and 1.
    """
    return 1 - math.exp(-seconds_since_last_post / tau)


def maybe_reward_user(user_id):
    """
    Rewards a user for posting.
    - Chance increases exponentially with inactivity.
    - Reward amount increases with rarity of up to 5 rarest items.
    - Sacred items also increase reward chance.
    """
    db = load_db()
    user = db.get(str(user_id))
    if not user:
        print("User not found.")
        return None

    now = time.time()
    last_post_time = user.get("time_since_last_post", 0)
    time_diff = now - last_post_time

    # === Base reward probability (unchanged)
    base_probability = calculate_reward_probability(time_diff)

    # === Rarity-based boosts
    rarity_boosts = {
        "rare": 0.015,       # +1.5% reward amount
        "exotic": 0.028,     # +2.8% reward amount
        "legendary": 0.05,   # +5% reward amount
        "sacred": 0.12       # +12% reward amount
    }

    rarity_order = ["common", "rare", "exotic", "legendary", "sacred"]
    items = user.get("items", [])

    # Sort by rarity (highest first)
    items_sorted = sorted(
        items,
        key=lambda x: rarity_order.index(x["rarity"]) if x["rarity"] in rarity_order else 0,
        reverse=True
    )

    # Consider up to 5 rarest items
    top_items = items_sorted[:5]

    # === Calculate reward amount boost
    total_reward_boost = sum(rarity_boosts.get(it["rarity"], 0.0) for it in top_items)
    total_reward_boost = min(total_reward_boost, 0.60)  # +60% cap

    # === Calculate Sacred-based chance boost
    sacred_count = sum(1 for it in top_items if it.get("rarity") == "sacred")
    sacred_chance_boost = min(sacred_count * 0.15, 0.75)  # +15% per Sacred, up to +75%
    final_probability = base_probability * (1 + sacred_chance_boost)

    # === Reward roll
    if random.random() < final_probability:
        base_reward = random.randint(5, 25)
        boosted_reward = round(base_reward * (1 + total_reward_boost))  #Proper rounding
        user["balance"] += boosted_reward
        user["time_since_last_post"] = now
        save_db(db)
        print(
            f"{user['username']} received {boosted_reward} OT Bucks "
            f"(base={base_reward}, +{total_reward_boost*100:.1f}% reward, "
            f"chance +{sacred_chance_boost*100:.1f}%)"
        )
        return boosted_reward
    else:
        user["time_since_last_post"] = now
        save_db(db)
        print(
            f"{user['username']} got no reward "
            f"(p={final_probability:.3f}, sacred bonus +{sacred_chance_boost*100:.1f}%)"
        )
        return None





import time
from commands import (
    check_post_for_commands,
    process_command_queue,
    command_queue
)



from API import check_new_posts   # your existing function
from ForumUpdate import update_post      # your update function
from investments import check_investments

TICK_INTERVAL = 15  # seconds between checks

def tick_loop():
    state = load_state()
    tick_count = state.get("tick_count", 0)

    print("Starting OT Economy Bot...")

    while True:
        tick_count += 1
        state["tick_count"] = tick_count
        save_state(state)

        print(f"\n=== Tick {tick_count} ===")

        try:
            state_changed = False  # <--- Track if anything changed this tick

            # Check for new posts
            new_posts_per_topic = check_new_posts()

            # Process rewards + commands as usual
            for topic_posts in new_posts_per_topic:
                for post in topic_posts:
                    reward = maybe_reward_user(post["user_id"])
                    if reward:
                        state_changed = True  # user balance changed

                commands_found = check_post_for_commands(topic_posts)
                if commands_found:
                    process_command_queue(command_queue)
                    # Any executed command (success or failure) updates the
                    # command history shown on the forum post
                    state_changed = True

            # Resolve any active investments
            if check_investments():
                state_changed = True

            # Apply wealth tax if this is a "weekly" tick
            prev_db = load_db()
            apply_wealth_tax_tick_based(tick_count)
            new_db = load_db()
            if new_db != prev_db:
                state_changed = True

            # Only update the forum if something changed
            if state_changed:
                print("Updating forum post (changes detected)...")
                update_post()
            else:
                print("No changes skipping forum update.")

        except Exception as e:
            print(f"Error during tick: {e}")

        time.sleep(TICK_INTERVAL)


tick_loop()
