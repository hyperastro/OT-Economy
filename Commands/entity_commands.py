import copy
import config
from DatabaseLogic.db import Database
from Entities.entities import Entity
from Commands.utils import validate_item_name, next_stack_id

"""
Entity (business) commands:
- !entity create [entity_name]
- !entity hire [entity_name] [target_user]
- !entity fire [entity_name] [target_user]
- !entity deposit [entity_name] [amount]
- !entity withdraw [entity_name] [amount]
- !entity item create [entity_name] [item_name] {quantity}
- !entity sell [entity_name] [price] [item_name] {stack_id} {quantity}
- !entity permission grant withdraw [entity] [target_user]
- !entity permission revoke withdraw [entity] [target_user]
- !entity transfer ownership [entity] [new_owner]
- !buy [item_name] [entity_name] {stack_id} {quantity}
"""

# === ENTITY COMMANDS ===

def cmd_entity_create(args, user_id, username, topic_id=None):
    """!entity create [entity_name] — costs 50 OT Bucks from creator's personal balance."""
    if not args:
        print("Usage: !entity create [entity_name]")
        return False

    entity_name = args[0].strip()
    db = Database.load_db()
    user = db.get(str(user_id))
    if not user:
        print("You are not registered.")
        return False
    if user["balance"] < config.ENTITY_CREATE_COST:
        print(f"Not enough OT Bucks (need {config.ENTITY_CREATE_COST}, have {user['balance']}).")
        return False

    entities = Entity.load_entities()
    _, existing = Entity.find_entity(entities, entity_name)
    if existing:
        print(f"An entity named '{entity_name}' already exists.")
        return False

    user["balance"] -= config.ENTITY_CREATE_COST
    Database.save_db(db)

    # Route the creation fee to OT! Government
    _, gov = Entity.find_entity(entities, "OT! Government")
    if gov:
        gov["balance"] += config.ENTITY_CREATE_COST
    else:
        print("OT! Government entity not found — creation fee was deducted but not redirected.")

    entities[entity_name] = {
        "name":         entity_name,
        "creator_id":   str(user_id),
        "employee_ids": [],
        "balance":      0,
        "items":        [],
        "listings":     [],
    }
    Entity.save_entities(entities)
    print(f"Entity '{entity_name}' created by {username}.")
    return True


def cmd_entity_hire(args, user_id, username, topic_id=None):
    """!entity hire [entity_name] [target_user] — creator only, costs 35 OT Bucks."""
    if len(args) < 2:
        print("Usage: !entity hire [entity_name] [target_user]")
        return False

    entity_name, target_name = args[0], args[1]
    db = Database.load_db()
    user = db.get(str(user_id))
    if not user:
        print("You are not registered.")
        return False

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False
    if not Entity.is_creator(entity, user_id):
        print("Only the entity creator can hire employees.")
        return False
    if user["balance"] < config.ENTITY_HIRE_COST:
        print(f"Not enough OT Bucks (need {config.ENTITY_HIRE_COST}, have {user['balance']}).")
        return False

    target_id = None
    for uid, data in db.items():
        if data["username"].lower() == target_name.lower() or uid == str(target_name):
            target_id = uid
            break
    if not target_id:
        print("Target user not found.")
        return False
    if Entity.is_member(entity, target_id):
        print(f"{target_name} is already a member of '{entity_name}'.")
        return False

    user["balance"] -= config.ENTITY_HIRE_COST
    Database.save_db(db)
    entity["employee_ids"].append(str(target_id))
    Entity.save_entities(entities)
    print(f"✅ {target_name} hired into '{entity_name}' by {username}.")
    return True


def cmd_entity_fire(args, user_id, username, topic_id=None):
    """!entity fire [entity_name] [target_user] — creator only."""
    if len(args) < 2:
        print("Usage: !entity fire [entity_name] [target_user]")
        return False

    entity_name, target_name = args[0], args[1]
    db = Database.load_db()

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False
    if not Entity.is_creator(entity, user_id):
        print("Only the entity creator can fire employees.")
        return False

    target_id = None
    for uid, data in db.items():
        if data["username"].lower() == target_name.lower() or uid == str(target_name):
            target_id = uid
            break
    if not target_id:
        print("Target user not found.")
        return False
    if Entity.is_creator(entity, target_id):
        print("Cannot fire the entity creator.")
        return False
    if str(target_id) not in [str(e) for e in entity["employee_ids"]]:
        print(f"{target_name} is not an employee of '{entity_name}'.")
        return False

    entity["employee_ids"] = [e for e in entity["employee_ids"] if str(e) != str(target_id)]
    # Auto-revoke withdraw permission on firing so it doesn't linger
    entity["withdraw_permissions"] = [p for p in entity.get("withdraw_permissions", []) if str(p) != str(target_id)]
    Entity.save_entities(entities)
    print(f"✅ {target_name} fired from '{entity_name}' by {username}.")
    return True


def cmd_entity_deposit(args, user_id, username, topic_id=None):
    """!entity deposit [entity_name] [amount] — any member can deposit."""
    if len(args) < 2:
        print("Usage: !entity deposit [entity_name] [amount]")
        return False

    entity_name = args[0]
    try:
        amount = int(args[1])
    except ValueError:
        print("Amount must be a whole number.")
        return False
    if amount <= 0:
        print("Amount must be positive.")
        return False

    db = Database.load_db()
    user = db.get(str(user_id))
    if not user:
        print("You are not registered.")
        return False

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False
    if not Entity.is_member(entity, user_id):
        print(f"You are not a member of '{entity_name}'.")
        return False
    if user["balance"] < amount:
        print(f"Not enough OT Bucks (have {user['balance']}, need {amount}).")
        return False

    user["balance"]    -= amount
    entity["balance"]  += amount
    Database.save_db(db)
    Entity.save_entities(entities)
    print(f"{username} deposited {amount} OT Bucks into '{entity_name}'.")
    return True


def cmd_entity_withdraw(args, user_id, username, topic_id=None):
    """!entity withdraw [entity_name] [amount] — creator, or employees granted withdraw permission."""
    if len(args) < 2:
        print("Usage: !entity withdraw [entity_name] [amount]")
        return False

    entity_name = args[0]
    try:
        amount = int(args[1])
    except ValueError:
        print("Amount must be a whole number.")
        return False
    if amount <= 0:
        print("Amount must be positive.")
        return False

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False

    has_permission = Entity.is_creator(entity, user_id) or str(user_id) in [str(p) for p in entity.get("withdraw_permissions", [])]
    if not has_permission:
        print("You do not have withdraw permission for this entity.")
        return False
    if entity["balance"] < amount:
        print(f"Entity only has {entity['balance']} OT Bucks.")
        return False

    db = Database.load_db()
    user = db.get(str(user_id))
    if not user:
        print("You are not registered.")
        return False

    entity["balance"] -= amount
    user["balance"]   += amount
    Database.save_db(db)
    Entity.save_entities(entities)
    print(f"{username} withdrew {amount} OT Bucks from '{entity_name}'.")
    return True


def cmd_entity_item_create(args, user_id, username, topic_id=None):
    """!entity item create [entity_name] [item_name] {quantity} — costs OT Bucks from entity balance."""
    if len(args) < 2:
        print("Usage: !entity item create [entity_name] [item_name] {quantity}")
        return False

    entity_name = args[0]
    item_name   = args[1].strip()
    try:
        qty = int(args[2]) if len(args) > 2 else 1
    except ValueError:
        print("Quantity must be a whole number.")
        return False
    if qty <= 0:
        print("Quantity must be at least 1.")
        return False
    if item_name.lower() in [b.lower() for b in config.BLACKLISTED_ITEMS]:
        print("This item name is blacklisted.")
        return False

    ok, reason = validate_item_name(item_name)
    if not ok:
        print(f"{reason}")
        return False

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False
    if not Entity.is_member(entity, user_id):
        print(f"You are not a member of '{entity_name}'.")
        return False

    cost = qty  # 1 OT Buck per item unit, same as personal item creation
    if entity["balance"] < cost:
        print(f"Entity has insufficient balance ({entity['balance']} OT Bucks, need {cost}).")
        return False

    entity["balance"] -= cost
    stack_id = Entity.next_entity_stack_id(entity["items"], item_name)
    entity["items"].append({
        "name":     item_name,
        "quantity": qty,
        "rarity":   "common",
        "stack_id": stack_id,
        "history":  [{"owner": entity["name"], "upgrades": []}],
    })
    Entity.save_entities(entities)
    print(f"Created {qty}x '{item_name}' (stack {stack_id}) for entity '{entity_name}'.")
    return True


def cmd_entity_sell(args, user_id, username, topic_id=None):
    """!entity sell [entity_name] [price] [item_name] {stack_id} {quantity}
    Lists items from the entity's inventory for sale. Re-running on the same
    item/stack updates the price and quantity of the existing listing.
    """
    if len(args) < 3:
        print("Usage: !entity sell [entity_name] [price] [item_name] {stack_id} {quantity}")
        return False

    entity_name = args[0]
    try:
        price = int(args[1])
    except ValueError:
        print("Price must be a whole number.")
        return False
    if price <= 0:
        print("Price must be positive.")
        return False

    item_name = args[2]
    stack_id  = args[3] if len(args) > 3 else None
    try:
        quantity = int(args[4]) if len(args) > 4 else None
    except ValueError:
        print("Quantity must be a whole number.")
        return False

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False
    if not Entity.is_member(entity, user_id):
        print(f"You are not a member of '{entity_name}'.")
        return False

    # Find matching item in entity inventory
    match = None
    for item in entity["items"]:
        if item["name"].lower() == item_name.lower() and (stack_id is None or item["stack_id"] == stack_id):
            match = item
            break
    if not match:
        print(f"Item '{item_name}' not found in '{entity_name}' inventory.")
        return False

    list_qty = quantity if quantity is not None else match["quantity"]
    if list_qty > match["quantity"]:
        print(f"Entity only has {match['quantity']}x {match['name']} in that stack.")
        return False
    if list_qty <= 0:
        print("Listing quantity must be at least 1.")
        return False

    # Update existing listing for same item+stack, or create a new one
    for listing in entity["listings"]:
        if listing["item_name"].lower() == match["name"].lower() and listing["stack_id"] == match["stack_id"]:
            listing["price_per_unit"] = price
            listing["quantity"]       = list_qty
            Entity.save_entities(entities)
            print(f"Updated listing: {list_qty}x '{match['name']}' (#{match['stack_id']}) at {price} OT Bucks each in '{entity_name}'.")
            return True

    entity["listings"].append({
        "item_name":     match["name"],
        "stack_id":      match["stack_id"],
        "quantity":      list_qty,
        "price_per_unit": price,
    })
    Entity.save_entities(entities)
    print(f"Listed {list_qty}x '{match['name']}' (#{match['stack_id']}) at {price} OT Bucks each in '{entity_name}'.")
    return True


def cmd_buy(args, user_id, username, topic_id=None):
    """!buy [item_name] [entity_name] {stack_id} {quantity}
    Buys from an entity's shop listing. OT Bucks go to the entity's balance.
    """
    if len(args) < 2:
        print("Usage: !buy [item_name] [entity_name] {stack_id} {quantity}")
        return False

    item_name   = args[0]
    entity_name = args[1]
    stack_id    = args[2] if len(args) > 2 else None
    try:
        quantity = int(args[3]) if len(args) > 3 else None
    except ValueError:
        print("Quantity must be a whole number.")
        return False

    db = Database.load_db()
    buyer = db.get(str(user_id))
    if not buyer:
        print("You are not registered.")
        return False

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False

    # Find matching listing
    listing = None
    for lst in entity["listings"]:
        if lst["item_name"].lower() == item_name.lower() and (stack_id is None or lst["stack_id"] == stack_id):
            listing = lst
            break
    if not listing:
        print(f"No listing for '{item_name}' found in '{entity_name}'.")
        return False

    buy_qty = quantity if quantity is not None else listing["quantity"]
    if buy_qty <= 0:
        print("Quantity must be at least 1.")
        return False
    if buy_qty > listing["quantity"]:
        print(f"Listing only has {listing['quantity']}x available.")
        return False

    total_cost = buy_qty * listing["price_per_unit"]
    if buyer["balance"] < total_cost:
        print(f"Not enough OT Bucks (need {total_cost}, have {buyer['balance']}).")
        return False

    # Locate the actual item in entity inventory
    entity_item = None
    for item in entity["items"]:
        if item["name"].lower() == listing["item_name"].lower() and item["stack_id"] == listing["stack_id"]:
            entity_item = item
            break
    if not entity_item or entity_item["quantity"] < buy_qty:
        print("Entity inventory is out of sync with its listing — contact an admin.")
        return False

    # Transfer OT Bucks
    buyer["balance"]  -= total_cost
    entity["balance"] += total_cost

    # Deduct from entity inventory; remove item entirely if stock hits zero
    entity_item["quantity"] -= buy_qty
    if entity_item["quantity"] == 0:
        entity["items"].remove(entity_item)

    # Deduct from listing; remove listing if fully sold out
    listing["quantity"] -= buy_qty
    if listing["quantity"] == 0:
        entity["listings"].remove(listing)

    # Build item history: entity chain + buyer as new owner
    transferred_history = copy.deepcopy(entity_item.get("history", [{"owner": entity["name"], "upgrades": []}]))
    transferred_history.append({"owner": username, "upgrades": []})

    # Merge into existing buyer stack if same name+stack_id, else create new entry
    existing = next(
        (it for it in buyer.get("items", [])
         if it["name"].lower() == entity_item["name"].lower() and it["stack_id"] == entity_item["stack_id"]),
        None
    )
    if existing:
        existing["quantity"] += buy_qty
    else:
        # Avoid stack_id collision with a different item of the same name in buyer inventory
        new_stack_id = entity_item["stack_id"]
        taken = {it["stack_id"] for it in buyer.get("items", []) if it["name"].lower() == entity_item["name"].lower()}
        if new_stack_id in taken:
            new_stack_id = next_stack_id(buyer["items"], entity_item["name"])
        buyer["items"].append({
            "name":     entity_item["name"],
            "quantity": buy_qty,
            "rarity":   entity_item["rarity"],
            "stack_id": new_stack_id,
            "history":  transferred_history,
        })

    Database.save_db(db)
    Entity.save_entities(entities)
    print(f"{username} bought {buy_qty}x '{entity_item['name']}' from '{entity_name}' for {total_cost} OT Bucks.")
    return True


def cmd_entity_transfer(args, user_id, username, topic_id=None):
    """!entity transfer ownership [entity] [new_owner]
    Transfers creator rights to another registered user.
    The old creator becomes a regular employee; the new owner is removed
    from the employee list (if present) and set as creator.
    """
    if len(args) < 2:
        print("Usage: !entity transfer ownership [entity] [new_owner]")
        return False

    entity_name, new_owner_name = args[0], args[1]

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False
    if not Entity.is_creator(entity, user_id):
        print("Only the entity creator can transfer ownership.")
        return False

    db = Database.load_db()
    new_owner_id = None
    for uid, data in db.items():
        if data["username"].lower() == new_owner_name.lower() or uid == str(new_owner_name):
            new_owner_id = uid
            break
    if not new_owner_id:
        print(f"User '{new_owner_name}' not found.")
        return False
    if str(new_owner_id) == str(user_id):
        print("You are already the owner of this entity.")
        return False

    # Demote old creator to employee, promote new owner to creator
    old_creator_id = str(entity["creator_id"])
    entity["creator_id"] = str(new_owner_id)

    # Remove new owner from employees if they were already a member
    entity["employee_ids"] = [e for e in entity["employee_ids"] if str(e) != str(new_owner_id)]

    # Add old creator as an employee so they keep member access
    if old_creator_id not in [str(e) for e in entity["employee_ids"]]:
        entity["employee_ids"].append(old_creator_id)

    Entity.save_entities(entities)
    new_owner_username = db[new_owner_id]["username"]
    print(f"Ownership of '{entity_name}' transferred from {username} to {new_owner_username}.")
    return True


def cmd_entity_permission_grant(args, user_id, username, topic_id=None):
    """!entity permission grant withdraw [entity] [target_user] — creator only."""
    if len(args) < 2:
        print("Usage: !entity permission grant withdraw [entity] [target_user]")
        return False

    entity_name, target_name = args[0], args[1]

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False
    if not Entity.is_creator(entity, user_id):
        print("Only the entity creator can grant permissions.")
        return False

    db = Database.load_db()
    target_id = None
    for uid, data in db.items():
        if data["username"].lower() == target_name.lower() or uid == str(target_name):
            target_id = uid
            break
    if not target_id:
        print(f"User '{target_name}' not found.")
        return False
    if Entity.is_creator(entity, target_id):
        print("The creator already has withdraw permission.")
        return False
    if not Entity.is_member(entity, target_id):
        print(f"{target_name} is not a member of '{entity_name}' — hire them first.")
        return False
    if str(target_id) in [str(p) for p in entity.get("withdraw_permissions", [])]:
        print(f"{target_name} already has withdraw permission in '{entity_name}'.")
        return False

    entity.setdefault("withdraw_permissions", []).append(str(target_id))
    Entity.save_entities(entities)
    print(f"Withdraw permission granted to {target_name} in '{entity_name}'.")
    return True


def cmd_entity_permission_revoke(args, user_id, username, topic_id=None):
    """!entity permission revoke withdraw [entity] [target_user] — creator only."""
    if len(args) < 2:
        print("Usage: !entity permission revoke withdraw [entity] [target_user]")
        return False

    entity_name, target_name = args[0], args[1]

    entities = Entity.load_entities()
    _, entity = Entity.find_entity(entities, entity_name)
    if not entity:
        print(f"Entity '{entity_name}' not found.")
        return False
    if not Entity.is_creator(entity, user_id):
        print("Only the entity creator can revoke permissions.")
        return False

    db = Database.load_db()
    target_id = None
    for uid, data in db.items():
        if data["username"].lower() == target_name.lower() or uid == str(target_name):
            target_id = uid
            break
    if not target_id:
        print(f"User '{target_name}' not found.")
        return False
    if str(target_id) not in [str(p) for p in entity.get("withdraw_permissions", [])]:
        print(f"{target_name} does not have withdraw permission in '{entity_name}'.")
        return False

    entity["withdraw_permissions"] = [p for p in entity.get("withdraw_permissions", []) if str(p) != str(target_id)]
    Entity.save_entities(entities)
    print(f"Withdraw permission revoked from {target_name} in '{entity_name}'.")
    return True
