import json
import random
import math
from DatabaseLogic.db import Database
from Telemetry.telemetry import Telemetry
import config


def save_balance_snapshot(db):
    """Persist current balances as the weekly baseline for gains tracking in the leaderboard."""
    snapshot = {
        "saved_at": time.time(),
        "balances": {uid: user.get("balance", 0) for uid, user in db.items()},
    }
    with open(config.SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f, indent=4)
    print("Weekly balance snapshot saved.")


def load_state():
    if config.STATE_PATH.exists():
        with open(config.STATE_PATH, "r") as f:
            return json.load(f)
    return {"tick_count": 0}

def save_state(state):
    with open(config.STATE_PATH, "w") as f:
        json.dump(state, f, indent=4)

def apply_wealth_tax_tick_based(current_tick):
    """
    Applies a 3% wealth tax every 40,320 ticks (~once per week)
    to all users with >10,000 OT Bucks.
    """
    if current_tick % config.TICKS_PER_WEEK != 0:
        return  # Not a tax tick yet

    db = Database.load_db()
    taxed_users = []

    for uid, user in db.items():
        balance = user.get("balance", 0)
        if balance > config.TAX_THRESHOLD:
            tax_amount = round(balance * config.TAX_RATE)
            user["balance"] -= tax_amount
            taxed_users.append((user["username"], tax_amount))
            Telemetry.log_event("burn", tax_amount, "wealth_tax", meta={"user_id": uid})
            print(f"Wealth tax: {user['username']} paid {tax_amount} OT Bucks (3%)")

    if taxed_users:
        Database.save_db(db)
        print(f"Applied wealth tax to {len(taxed_users)} users this week.")
    else:
        print("No users eligible for wealth tax this week.")

    # Snapshot after tax so week-over-week gains comparisons are always fair
    save_balance_snapshot(db)
    Telemetry.record_weekly_snapshot(db)


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
    - Rapid posting is penalised via a rolling 10-minute window (β=0.75).
    """
    db = Database.load_db()
    user = db.get(str(user_id))
    if not user:
        print("User not found.")
        return None

    now = time.time()
    last_post_time = user.get("time_since_last_post", 0)
    time_diff = now - last_post_time

    # ===  Base reward probability (unchanged)
    base_probability = calculate_reward_probability(time_diff)

    items = user.get("items", [])

    # Sort by rarity (highest first)
    items_sorted = sorted(
        items,
        key=lambda x: config.rarity_order.index(x["rarity"]) if x["rarity"] in config.rarity_order else 0,
        reverse=True
    )

    # Consider up to 5 rarest items
    top_items = items_sorted[:5]

    # === Calculate reward amount boost
    total_reward_boost = sum(config.rarity_boosts.get(it["rarity"], 0.0) for it in top_items)
    total_reward_boost = min(total_reward_boost, 0.60)  # +60% cap

    # ===  Calculate Sacred-based chance boost
    sacred_count = sum(1 for it in top_items if it.get("rarity") == "sacred")
    sacred_chance_boost = min(sacred_count * 0.15, 0.75)  # +15% per Sacred, up to +75%
    final_probability = base_probability * (1 + sacred_chance_boost)

    # === Rolling window spam penalty (β = 0.75, 10-minute window)
    # The first SPAM_GRACE_POSTS posts within the window are free — sustained
    # but paced posting (e.g. 5/min) isn't punished just for having a high
    # count. Beyond the grace amount, each additional post reduces probability
    # by 1/over_grace^0.75, but never below SPAM_MIN_PENALTY — a floor stops
    # very active (but non-bursty) posters from being pushed to ~0% chance.
    recent_times = [t for t in user.get("recent_post_times", []) if now - t < config.SPAM_WINDOW]
    n = len(recent_times) + 1  # +1 counts the current post
    over_grace = max(0, n - config.SPAM_GRACE_POSTS)
    if over_grace == 0:
        spam_penalty = 1.0
    else:
        spam_penalty = max(1.0 / (over_grace ** config.SPAM_BETA), config.SPAM_MIN_PENALTY)

    # === Burst penalty — catches actual spam (sub-MIN_HUMAN_GAP posting),
    # independent of the 10-minute count. This is what lets us keep the count
    # penalty lenient above: a bot firing posts every 1-2s gets hit hard here
    # regardless of n, while a human posting every 10-15s never triggers it.
    burst_penalty = config.BURST_PENALTY if time_diff < config.MIN_HUMAN_GAP else 1.0

    final_probability *= spam_penalty * burst_penalty

    # ===  Reward roll
    recent_times.append(now)   # always record the post, win or lose
    if random.random() < final_probability:
        base_reward = random.randint(5, 25)
        boosted_reward = round(base_reward * (1 + total_reward_boost))
        user["balance"] += boosted_reward
        user["time_since_last_post"] = now
        user["recent_post_times"] = recent_times
        Database.save_db(db)
        Telemetry.log_event("mint", boosted_reward, "post_reward", meta={"user_id": user_id})
        print(
            f"{user['username']} received {boosted_reward} OT Bucks "
            f"(base={base_reward}, +{total_reward_boost*100:.1f}% reward boost, "
            f"chance +{sacred_chance_boost*100:.1f}% sacred, "
            f"spam ×{spam_penalty:.2f} [n={n} in window, grace={config.SPAM_GRACE_POSTS}], "
            f"burst ×{burst_penalty:.2f} [gap={time_diff:.1f}s])"
        )
        return boosted_reward
    else:
        user["time_since_last_post"] = now
        user["recent_post_times"] = recent_times
        Database.save_db(db)
        print(
            f"{user['username']} got no reward "
            f"(p={final_probability:.4f}, sacred +{sacred_chance_boost*100:.1f}%, "
            f"spam ×{spam_penalty:.2f} [n={n} in window, grace={config.SPAM_GRACE_POSTS}], "
            f"burst ×{burst_penalty:.2f} [gap={time_diff:.1f}s])"
        )
        return None





import time
from Commands.commands import (
    check_post_for_commands,
    process_command_queue,
    command_queue
)



from API.API import OsuApi 
from ForumUpdate import ForumUpdate  
from Investments.investments import Investment



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
            state_changed = False 

            # Check for new posts
            new_posts_per_topic = OsuApi.check_new_posts()

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
            if Investment.check_investments():
                state_changed = True

            # Apply wealth tax if this is a "weekly" tick
            prev_db = Database.load_db()
            apply_wealth_tax_tick_based(tick_count)
            new_db = Database.load_db()
            if new_db != prev_db:
                state_changed = True

            # Only update the forum if something changed
            if state_changed:
                print("Updating forum post (changes detected)...")
                ForumUpdate.update_post()
            else:
                print("No changes — skipping forum update.")

        except Exception as e:
            print(f"Error during tick: {e}")

        time.sleep(config.TICK_INTERVAL)


tick_loop()
