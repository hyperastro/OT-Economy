import copy
import config
from DatabaseLogic.db import Database
from Entities.entities import Entity
from Investments.investments import Investment
from Commands.utils import (
    validate_item_name,
    register_user,
    find_user_by_name,
    next_stack_id,
    next_rarity,
    merge_or_append_item_stack,
)

"""
Core economy commands:
- !register
- !give [amount] {target}
- !item create {item_name} [quantity]
- !item give {item_name} {target} [stack_id]
- !item delete {item_name} {stack_id} [quantity]
- !item upgrade rarity {item_name} {stack_id} [quantity]
- !invest [amount] [tier] [hours]
"""

# === COMMAND EXECUTION ===
def cmd_register(args, user_id, username, topic_id=None):
    db = Database.load_db()
    return register_user(db, user_id, username)

def cmd_give(args, user_id, username, topic_id=None):
    """
    !give [amount] {target}
    Transfers OT Bucks from sender to target if valid.
    Returns True if transfer succeeded, False otherwise.
    """
    if len(args) < 2:
        print("Usage: !give [amount] {target}")
        return False

    amount_str, target_name = args

    try:
        amount = int(amount_str)
    except ValueError:
        print("Invalid amount format.")
        return False

    if amount <= 0:
        print("Invalid transfer amount.")
        return False

    db = Database.load_db()
    sender = db.get(str(user_id))
    if not sender:
        print("Sender not registered.")
        return False

    # Find target by username or ID
    target = None
    target_id = None
    for uid, data in db.items():
        if data["username"].lower() == target_name.lower() or uid == str(target_name):
            target = data
            target_id = uid
            break

    if not target:
        # Fall back to entity
        entities = Entity.load_entities()
        _, entity =  Entity.find_entity(entities, target_name)
        if entity:
            if sender["balance"] < amount:
                print("Not enough balance.")
                return False
            sender["balance"] -= amount
            entity["balance"] += amount
            Database.save_db(db)
            Entity.save_entities(entities)
            print(f"{sender['username']} gave {amount} OT Bucks to entity '{entity['name']}'")
            return True
        print("Target not found.")
        return False

    if sender["balance"] < amount:
        print("Not enough balance.")
        return False

    # Perform transfer safely
    sender["balance"] -= amount
    target["balance"] += amount

    Database.save_db(db)
    print(f"{sender['username']} gave {amount} OT Bucks to {target['username']}")
    return True



def cmd_item_create(args, user_id, username, topic_id=None):
    item_name = args[0].strip()
    qty = int(args[1]) if len(args) > 1 else 1
    db = Database.load_db()

    if item_name.lower() in [b.lower() for b in config.BLACKLISTED_ITEMS]:
        print("This item name is blacklisted.")
        return False

    ok, reason = validate_item_name(item_name)
    if not ok:
        print(f"{reason}")
        return False

    user = db.get(str(user_id))
    if not user:
        print("You are not registered.")
        return False
    cost = qty
    if user["balance"] < cost:
        print("Not enough OT bucks.")
        return False

    user["balance"] -= cost
    stack_id = next_stack_id(user["items"], item_name)
    user["items"].append({
        "name": item_name,
        "quantity": qty,
        "rarity": "common",
        "stack_id": stack_id,
        "history": [{"owner": username, "upgrades": []}]
    })
    Database.save_db(db)
    print(f"Created {qty}x {item_name} (stack {stack_id}) for {username}")
    return True


def cmd_item_give(args, user_id, username, topic_id=None):
    """
    !item give {item_name} {target} [stack_id [quantity]]

    Transfers an item to another user, updating ownership history.
    If quantity is less than the stack size the stack is split; the transferred
    portion keeps the same stack_id and inherits the full history up to this point.
    The recipient only merges it into a stack with the same name, stack_id,
    rarity, and ownership history. Incompatible local ID collisions receive a
    new stack_id.
    """
    if len(args) < 2:
        print("Usage: !item give {item_name} {target} [stack_id [quantity]]")
        return False

    item_name = args[0]
    target    = args[1]
    stack_id  = args[2] if len(args) > 2 else None

    try:
        quantity = int(args[3]) if len(args) > 3 else None
    except ValueError:
        print("Quantity must be a whole number.")
        return False

    if quantity is not None and quantity <= 0:
        print("Quantity must be at least 1.")
        return False

    db = Database.load_db()
    sender = db.get(str(user_id))
    if not sender:
        print("Sender not registered.")
        return False

    target_id = target if target.isdigit() else find_user_by_name(db, target)
    recipient_entity = None
    entities = None
    if not target_id or str(target_id) not in db:
        entities = Entity.load_entities()
        _, recipient_entity = Entity.find_entity(entities, target)
        if not recipient_entity:
            print("Target not found.")
            return False

    match = None
    for item in sender["items"]:
        if item["name"].lower() == item_name.lower() and (stack_id is None or item["stack_id"] == stack_id):
            match = item
            break
    if not match:
        print("Item not found in your inventory.")
        return False

    give_qty = quantity if quantity is not None else match["quantity"]
    if give_qty > match["quantity"]:
        print(f"You only have {match['quantity']}x {match['name']} in that stack.")
        return False

    recipient          = db[str(target_id)] if not recipient_entity else None
    recipient_username = recipient["username"] if recipient else recipient_entity["name"]

    # Ensure sender's item has a history (legacy support).
    # Prepend "Unknown origin" so the provenance isn't silently lost on first transfer.
    if not match.get("history"):
        match["history"] = [
            {"owner": "Unknown origin", "upgrades": []},
            {"owner": username, "upgrades": []},
        ]

    target_items = recipient["items"] if recipient else recipient_entity["items"]

    if give_qty == match["quantity"]:
        # ── Full stack transfer
        match["history"].append({"owner": recipient_username, "upgrades": []})
        sender["items"].remove(match)
        transferred_stack = merge_or_append_item_stack(target_items, match)

    else:
        # ── Partial transfer — split the stack
        match["quantity"] -= give_qty

        transferred_history = copy.deepcopy(match["history"])
        transferred_history.append({"owner": recipient_username, "upgrades": []})
        transferred_stack = merge_or_append_item_stack(
            target_items,
            {
                "name":     match["name"],
                "quantity": give_qty,
                "rarity":   match["rarity"],
                "stack_id": match["stack_id"],
                "history":  transferred_history,
            },
        )

    Database.save_db(db)
    if recipient_entity:
        Entity.save_entities(entities)
    print(f"Gave {give_qty}x {match['name']} (#{transferred_stack['stack_id']}) to {recipient_username}")
    return True

def cmd_item_delete(args, user_id, username, topic_id=None):
    item_name, stack_id, *qty_arg = args
    qty = int(qty_arg[0]) if qty_arg else None
    db = Database.load_db()
    user = db.get(str(user_id))
    if not user:
        print("Not registered.")
        return False

    for item in user["items"]:
        if item["name"].lower() == item_name.lower() and item["stack_id"] == stack_id:
            qty_deleted = item["quantity"] if (qty is None or qty >= item["quantity"]) else qty
            value_per_unit = config.RARITY_TOTAL_COST.get(item["rarity"].lower(), 1)
            refund = round(qty_deleted * value_per_unit * 0.5)
            user["balance"] += refund

            if qty is None or qty >= item["quantity"]:
                user["items"].remove(item)
                print(f"Deleted stack {stack_id} of {item_name} - refunded {refund} OT Bucks")
                Database.save_db(db)
                return True
            else:
                item["quantity"] -= qty
                print(f"Deleted {qty_deleted}x {item_name} from stack {stack_id} - refunded {refund} OT Bucks")
                Database.save_db(db)
                return True

    else:
        print("No matching item found.")
        return False



def cmd_item_upgrade(args, user_id, username, topic_id=None):
    item_name, stack_id, *qty_arg = args
    qty = int(qty_arg[0]) if qty_arg else 1  # default: upgrade just 1 item, not the whole stack
    if qty <= 0:
        print("Quantity must be at least 1.")
        return False

    db = Database.load_db()
    user = db.get(str(user_id))
    if not user:
        print("Not registered.")
        return False

    for item in user["items"]:
        if item["name"].lower() == item_name.lower() and item["stack_id"] == stack_id:
            if qty > item["quantity"]:
                print(f"You only have {item['quantity']}x {item['name']} in that stack.")
                return False

            rarity_next = next_rarity(item["rarity"])
            if not rarity_next:
                print("⚠️ Already at highest rarity.")
                return False
            new_rarity, cost_per_item = rarity_next
            cost = int(cost_per_item) * qty
            if user["balance"] < cost:
                print("Not enough OT bucks.")
                return False
            user["balance"] -= cost

            if qty == item["quantity"]:
                # Upgrading the whole stack — update it in place, same as before.
                item["rarity"] = new_rarity
                if not item.get("history"):
                    item["history"] = [
                        {"owner": "Unknown origin", "upgrades": []},
                        {"owner": username, "upgrades": [new_rarity]},
                    ]
                else:
                    last = item["history"][-1]
                    if last["owner"].lower() == username.lower():
                        last.setdefault("upgrades", []).append(new_rarity)
                    else:
                        item["history"].append({"owner": username, "upgrades": [new_rarity]})
            else:
                # Partial upgrade — split the stack: shrink the original,
                # and create a new stack at the new rarity for the upgraded units.
                item["quantity"] -= qty

                base_history = item.get("history") or [{"owner": "Unknown origin", "upgrades": []}]
                upgraded_history = copy.deepcopy(base_history)
                last = upgraded_history[-1]
                if last["owner"].lower() == username.lower():
                    last.setdefault("upgrades", []).append(new_rarity)
                else:
                    upgraded_history.append({"owner": username, "upgrades": [new_rarity]})

                new_stack_id = next_stack_id(user["items"], item["name"])
                user["items"].append({
                    "name":     item["name"],
                    "quantity": qty,
                    "rarity":   new_rarity,
                    "stack_id": new_stack_id,
                    "history":  upgraded_history,
                })

            Database.save_db(db)
            print(f"✅ Upgraded {qty}x {item_name} (stack {stack_id}) to {new_rarity} rarity.")
            return True
    print("Item not found.")
    return False

def cmd_invest(args, user_id, username, topic_id=None):
    """
    !invest [amount] [tier] [hours]

    Invests OT Bucks on a thread reaching a target number of new unique
    posters within the given time limit.

    Tiers: 10 / 20 / 30 / 40 / 50  (raw value is rounded DOWN to nearest tier)
    Payouts on success: 3% / 7% / 12% / 25% / 50% of stake (before time scaling)
    Time scaling per tier — full reward window / half / quarter / max:
        Tier 10:  ≤12h / ≤24h / ≤36h  — fail if >36h
        Tier 20:  ≤24h / ≤48h / ≤72h  — fail if >72h
        Tier 30:  ≤48h / ≤96h / ≤144h — fail if >144h
        Tier 40:  ≤72h / ≤144h / ≤216h — fail if >216h
        Tier 50: ≤168h / ≤336h / ≤504h — fail if >504h
    On failure: refund = round(stake × posters_reached / tier_target)
    """
    if topic_id is None:
        print("!invest could not determine the topic — post may be missing topic context.")
        return False

    if len(args) < 3:
        print("⚠️ Usage: !invest [amount] [tier] [hours]")
        return False

    try:
        invest_amount    = int(args[0])
        raw_tier         = int(args[1])
        time_limit_hours = int(args[2])
    except ValueError:
        print("!invest — all arguments must be whole numbers.")
        return False

    if invest_amount <= 0:
        print("Investment amount must be a positive number.")
        return False

    if time_limit_hours < 1:
        print("Time limit must be at least 1 hour.")
        return False

    # Resolve and validate tier
    tier = Investment.resolve_tier(raw_tier)
    if tier is None:
        print(f"Invalid tier {raw_tier}. Must be between 10 and 50 inclusive.")
        return False

    if tier != raw_tier:
        print(f"Tier {raw_tier} rounded down to tier {tier}.")

    # Validate time limit and determine reward scaling
    reward_multiplier = Investment.get_reward_multiplier(tier, time_limit_hours)
    if reward_multiplier is None:
        base = config.TIER_BASE_HOURS[tier]
        max_hours = base * 3
        print(
            f"Time limit {time_limit_hours}h is too long for tier {tier}. "
            f"Maximum is {max_hours}h ({base}h = full, {base*2}h = half, {base*3}h = quarter)."
        )
        return False

    # Create the investment (validates balance, snapshots baseline, deducts stake)
    success, result = Investment.create_investment(
        user_id, username, topic_id,
        invest_amount, tier, time_limit_hours, reward_multiplier
    )

    if not success:
        print(f"Investment failed: {result}")
        return False

    potential_reward = round(invest_amount * config.TIER_PCT[tier] * reward_multiplier)
    print(
        f"{username} invested {invest_amount} OT Bucks on tier {tier} "
        f"({tier} new unique posters in {time_limit_hours}h | "
        f"×{reward_multiplier} multiplier | "
        f"potential reward: +{potential_reward} OT Bucks)"
    )
    return True
