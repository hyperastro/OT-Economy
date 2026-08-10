from ossapi import Ossapi, Scope
import string
import time
import json
import config


# === osu! API Setup ===
scopes = [Scope.PUBLIC, Scope.FORUM_WRITE]
api = Ossapi(config.client_id, config.client_secret, config.callback_url, scopes=scopes)

# === Local DB ===
class ForumUpdate:
    @staticmethod
    # === Build Leaderboard ===
    def update_leaderboard(db):
        """Return a formatted leaderboard showing the top 10 richest users with colored ranks and economy statistics."""
        # Sort users by OT bucks (balance)
        sorted_users = sorted(
            db.items(),
            key=lambda x: x[1].get("balance", 0),
            reverse=True
        )[:10]  # only top 10

        # Colors for top ranks
        rank_colors = {
            1: "gold",     #
            2: "silver",   #
            3: "#cd7f32"   #(bronze)
        }

        # --- Stat 1: Total + average OT bucks ---
        total_ot_bucks = sum(user.get("balance", 0) for user in db.values())
        user_count = len(db)
        avg_bucks = round(total_ot_bucks / user_count) if user_count > 0 else 0

        # --- Stat 2: Investment success rate (last 2 weeks) ---
        two_weeks_ago = time.time() - (14 * 24 * 3600)
        success_count = 0
        resolved_count = 0
        if config.INVESTMENTS_PATH.exists():
            with open(config.INVESTMENTS_PATH, "r") as f:
                try:
                    investments = json.load(f)
                except json.JSONDecodeError:
                    investments = []
            for inv in investments:
                if inv.get("status") in ("success", "failed"):
                    if inv.get("resolved_at", 0) >= two_weeks_ago:
                        resolved_count += 1
                        if inv["status"] == "success":
                            success_count += 1

        if resolved_count > 0:
            success_pct = round(success_count / resolved_count * 100)
            success_str = f"{success_pct}% ({success_count}/{resolved_count} investments)"
        else:
            success_str = "No resolved investments in the last 2 weeks"

        # --- Stat 3: Richest gains this week (vs weekly balance snapshot) ---
        top_gainer_str = "No snapshot yet — gains will appear after the first weekly tick"
        if config.SNAPSHOT_PATH.exists():
            with open(config.SNAPSHOT_PATH, "r") as f:
                try:
                    snapshot = json.load(f)
                except json.JSONDecodeError:
                    snapshot = {}
            snapshot_balances = snapshot.get("balances", {})
            best_uid, best_gain = None, None
            for uid, user in db.items():
                prev = snapshot_balances.get(uid, 0)  # new users had 0 last week
                gain = user.get("balance", 0) - prev
                if best_gain is None or gain > best_gain:
                    best_gain = gain
                    best_uid = uid
            if best_uid is not None:
                name = db[best_uid]["username"]
                sign = f"+{best_gain}" if best_gain >= 0 else str(best_gain)
                top_gainer_str = f"{name} ({sign} OT Bucks)"

        # --- Stat 4: Item rarity distribution ---
        rarity_colors = {
            "common": "grey", "rare": "lime", "exotic": "cyan",
            "legendary": "red", "sacred": "gold",
        }
        rarity_counts = {r: 0 for r in rarity_colors}
        total_items = 0
        for user in db.values():
            for item in user.get("items", []):
                r = item.get("rarity", "common").lower()
                if r in rarity_counts:
                    rarity_counts[r] += 1
                else:
                    rarity_counts[r] = rarity_counts.get(r, 0) + 1
                total_items += 1

        if total_items > 0:
            parts = []
            for r, color in rarity_colors.items():
                count = rarity_counts.get(r, 0)
                if count:
                    pct = round(count / total_items * 100, 2)
                    parts.append(f"[color={color}]{r}: {count} ({pct}%)[/color]")
            rarity_str = " | ".join(parts) if parts else "None"
        else:
            rarity_str = "No items in circulation"

        # --- Assemble output ---
        lines = ["[centre][b]OT!Economy Richest Users:[/b][/centre]"]
        for rank, (uid, user) in enumerate(sorted_users, start=1):
            color = rank_colors.get(rank)
            if color:
                lines.append(f"[color={color}]{rank}. {user['username']} — {user['balance']} OT bucks[/color]")
            else:
                lines.append(f"{rank}. {user['username']} — {user['balance']} OT bucks")

        lines.append("")
        lines.append(f"[i]Total OT Bucks in circulation: {total_ot_bucks}[/i]")
        lines.append(f"[i]Average OT Bucks per user: {avg_bucks}[/i]")
        lines.append(f"[i]Investment success rate (last 2 weeks): {success_str}[/i]")
        lines.append(f"[i]Richest gains this week: {top_gainer_str}[/i]")
        lines.append(f"[i]Item rarity distribution: {rarity_str}[/i]")

        return "\n".join(lines)



    # === Compact item list (character-budget friendly) ===
    @staticmethod
    def format_items_compact(items):
        """
        Build a compact, comma-separated description of an inventory.

        Items are grouped by (name, rarity) — two stacks only merge if both
        the name AND the rarity match. Within a group, stacks whose numeric
        IDs are consecutive AND share the same per-stack quantity are folded
        into a single "#AAAA-#BBBB×Q" range. Any stack that breaks that
        pattern (different quantity, or a gap in the numbering) is kept as
        its own "#AAAA×Q" entry. Stacks with a non-numeric stack_id can't be
        range-merged and are always listed individually.

        This intentionally drops the old per-item [box]...[/box] wrapper and
        inline ownership history — those are what were blowing up the post's
        character count when an item existed as dozens/hundreds of stacks.
        Single-stack items keep the old flat "name #id ×qty" look.

        Returns a list of formatted strings (one per group), in first-seen
        order. Join with ", " for the classic inline look.
        """
        rarity_colors = {
            "common": "grey", "rare": "lime", "exotic": "cyan",
            "legendary": "red", "sacred": "gold", "redacted": "purple",
        }

        groups = {}  # (name_lower, rarity) -> {"name": str, "rarity": str, "stacks": [(int_id|None, id_str, qty)]}
        for item in items:
            name = item.get("name", "")
            rarity = item.get("rarity", "common").lower()
            key = (name.lower(), rarity)
            if key not in groups:
                groups[key] = {"name": name, "rarity": rarity, "stacks": []}

            sid_str = item.get("stack_id", "")
            try:
                sid_int = int(sid_str)
            except (TypeError, ValueError):
                sid_int = None

            groups[key]["stacks"].append((sid_int, sid_str, item.get("quantity", 0)))

        entries = []
        for data in groups.values():
            color = rarity_colors.get(data["rarity"], "grey")
            name = data["name"]
            stacks = data["stacks"]
            total_qty = sum(s[2] for s in stacks)

            if len(stacks) == 1:
                _, sid_str, qty = stacks[0]
                entries.append(f"[color={color}]{name}[/color] #{sid_str} ×{qty}")
                continue

            sortable = sorted((s for s in stacks if s[0] is not None), key=lambda s: s[0])
            unsortable = [s for s in stacks if s[0] is None]

            run_parts = []
            i = 0
            while i < len(sortable):
                start_int, start_str, qty = sortable[i]
                j = i
                while (
                    j + 1 < len(sortable)
                    and sortable[j + 1][0] == sortable[j][0] + 1
                    and sortable[j + 1][2] == qty
                ):
                    j += 1
                end_int, end_str, _ = sortable[j]
                if j == i:
                    run_parts.append(f"#{start_str}×{qty}")
                else:
                    run_parts.append(f"#{start_str}-#{end_str}×{qty}")
                i = j + 1

            for _, sid_str, qty in unsortable:
                run_parts.append(f"#{sid_str}×{qty}")

            stacks_str = ", ".join(run_parts)
            entries.append(f"[color={color}]{name}[/color] [stacks {stacks_str}] ×{total_qty}")

        return entries


    # === Item boxes with history + rarity (character-budget aware) ===
    @staticmethod
    def format_items_boxes(items, current_owner_name, entity_names: set = None):
        """
        Build one [box=...] per item stack — title, ownership history, and
        rarity — matching the original ledger look.

        To avoid the exact bloat that hit the 60k character limit, stacks
        only collapse into a single box (with an ID range like #0001-#0061)
        when they share the same name, rarity, per-stack quantity, AND an
        *identical* ownership history. That's the common case: a batch of
        stacks created together and never individually transferred/upgraded.
        The moment a stack's history diverges (transferred, upgraded, split)
        it gets its own box, so provenance is never hidden or blended.

        Returns a list of "[box=...]...[/box]" strings, in first-seen order.
        Join with ", " for the classic inline look.
        """
        rarity_colors = {
            "common": "grey", "rare": "lime", "exotic": "cyan",
            "legendary": "red", "sacred": "gold", "redacted": "purple",
        }

        groups = {}  # (name_lower, rarity) -> {"name": str, "rarity": str, "stacks": [item, ...]}
        for item in items:
            name = item.get("name", "")
            rarity = item.get("rarity", "common").lower()
            key = (name.lower(), rarity)
            if key not in groups:
                groups[key] = {"name": name, "rarity": rarity, "stacks": []}
            groups[key]["stacks"].append(item)

        def sid_int(it):
            try:
                return int(it.get("stack_id"))
            except (TypeError, ValueError):
                return None

        boxes = []
        for data in groups.values():
            color = rarity_colors.get(data["rarity"], "grey")
            name = data["name"]
            rarity = data["rarity"]
            stacks = data["stacks"]

            sortable = sorted((it for it in stacks if sid_int(it) is not None), key=sid_int)
            unsortable = [it for it in stacks if sid_int(it) is None]

            # Build runs of consecutive stack IDs sharing quantity + history
            runs = []
            i = 0
            while i < len(sortable):
                run = [sortable[i]]
                j = i
                while (
                    j + 1 < len(sortable)
                    and sid_int(sortable[j + 1]) == sid_int(sortable[j]) + 1
                    and sortable[j + 1]["quantity"] == sortable[j]["quantity"]
                    and sortable[j + 1].get("history") == sortable[j].get("history")
                ):
                    j += 1
                    run.append(sortable[j])
                runs.append(run)
                i = j + 1

            for it in unsortable:
                runs.append([it])

            for run in runs:
                total_qty = sum(it["quantity"] for it in run)
                history_str = ForumUpdate.format_item_history(run[0], current_owner_name, entity_names)

                if len(run) == 1:
                    sid_label = f"#{run[0]['stack_id']}"
                else:
                    sid_label = f"#{run[0]['stack_id']}-#{run[-1]['stack_id']}"

                box_title = f"[color={color}]{name}[/color] {sid_label} ×{total_qty}"
                box_content = f"{history_str}\nitem rarity: [color={color}]{rarity}[/color]"
                boxes.append(f"[box={box_title}]{box_content}[/box]")

        return boxes


    # === Build Ledger (A–Z boxes) ===
    @staticmethod
    def create_ledger(db):
        """Return formatted ledger boxes for all users grouped by first letter, with colored item rarities."""

        import string
        alphabet = list(string.ascii_uppercase)
        ledger_lines = []
        grouped = {letter: [] for letter in alphabet}
        grouped["#"] = []

        # Build a set of entity names (lowercased) so format_item_history
        # can tag entity owners without hitting disk on every item.
        entity_names: set = set()
        if config.ENTITIES_PATH.exists():
            with open(config.ENTITIES_PATH, "r", encoding="utf-8") as f:
                try:
                    ents = json.load(f)
                    entity_names = {e["name"].lower() for e in ents.values()}
                except json.JSONDecodeError:
                    pass

        # Group users by starting letter
        for user in db.values():
            name = user["username"]
            first = name[0].upper() if name else "#"
            if first not in grouped:
                first = "#"
            grouped[first].append(user)

        for letter in grouped:
            if not grouped[letter]:
                continue

            ledger_lines.append(f"[box={letter}]")
            for user in sorted(grouped[letter], key=lambda u: u["username"].lower()):
                item_boxes = ForumUpdate.format_items_boxes(user.get("items", []), user["username"], entity_names)
                items_str = ", ".join(item_boxes) if item_boxes else "None"

                ledger_lines.append(f"[box={user['username']}]")
                ledger_lines.append(f"OT bucks : {user.get('balance', 0)}")
                ledger_lines.append(f"Items : {items_str}")
                ledger_lines.append("[/box]")
            ledger_lines.append("[/box]")

        return "\n".join(ledger_lines)


    # === Item history formatter ===
    @staticmethod
    def format_item_history(item, current_username, entity_names: set = None):
        """
        Render the ownership chain for a single item stack as a single line.
        e.g.  Google LTD (entity) -> PlayerA (upgraded to rare) -> PlayerB
        Legacy items with no history field fall back to: Unknown origin -> current_username

        entity_names: optional set of lowercased entity names. When an owner
        matches, "(entity)" is appended so readers can't confuse entities with
        real player names.
        """
        history = item.get("history")
        if not history:
            return f"Unknown origin -> {current_username}"

        parts = []
        for entry in history:
            label    = entry.get("owner", "?")
            upgrades = entry.get("upgrades", [])

            # Tag entity owners so they're distinguishable from player names
            if entity_names and label.lower() in entity_names:
                label += " (entity)"

            if upgrades:
                label += f" (upgraded to {upgrades[-1]})"
            parts.append(label)

        return " -> ".join(parts)


    # === Build Recent Commands Log ===
    @staticmethod
    def create_command_history():
        """Return a formatted list of the most recently executed commands (most recent first)."""
        if not config.COMMAND_HISTORY_PATH.exists():
            return "[i]No commands have been executed yet.[/i]"

        with open(config.COMMAND_HISTORY_PATH, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []

        if not history:
            return "[i]No commands have been executed yet.[/i]"

        lines = []
        for entry in reversed(history):  # most recent first
            timestamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry.get("timestamp", 0)))
            username = entry.get("username", "unknown")
            command = entry.get("command", "")
            if entry.get("success"):
                status = "[color=lime]✅[/color]"
            else:
                status = "[color=red]❌[/color]"
            lines.append(f"{status} [{timestamp}] {username}: {command}")

        return "\n".join(lines)


    # === Build Entity Ledger ===
    @staticmethod
    def create_entity_ledger():
        """Return formatted entity ledger boxes grouped A–Z, mirroring the user ledger style."""
        if not config.ENTITIES_PATH.exists():
            return "[i]No entities registered yet.[/i]"

        with open(config.ENTITIES_PATH, "r", encoding="utf-8") as f:
            try:
                entities = json.load(f)
            except json.JSONDecodeError:
                return "[i]No entities registered yet.[/i]"

        if not entities:
            return "[i]No entities registered yet.[/i]"

        # Load user DB so we can resolve IDs to usernames
        db = {}
        if config.DB_PATH.exists():
            with open(config.DB_PATH, "r", encoding="utf-8") as f:
                db = json.load(f)

        alphabet = list(string.ascii_uppercase)
        grouped = {letter: [] for letter in alphabet}
        grouped["#"] = []

        # Build entity name set for history tagging (same logic as create_ledger)
        entity_names: set = {e["name"].lower() for e in entities.values()}

        for entity in entities.values():
            first = entity["name"][0].upper() if entity["name"] else "#"
            if first not in grouped:
                first = "#"
            grouped[first].append(entity)

        ledger_lines = []
        for letter in alphabet + ["#"]:
            if not grouped.get(letter):
                continue

            ledger_lines.append(f"[box={letter}]")
            for entity in sorted(grouped[letter], key=lambda e: e["name"].lower()):

                # Resolve member names
                creator_id   = str(entity.get("creator_id", ""))
                creator_name = db.get(creator_id, {}).get("username", f"ID:{creator_id}")
                employee_names = [
                    db.get(str(eid), {}).get("username", f"ID:{eid}")
                    for eid in entity.get("employee_ids", [])
                ]
                members_str = creator_name + " (owner)"
                if employee_names:
                    members_str += ", " + ", ".join(employee_names)

                # Format inventory items (same box+history style as user ledger)
                item_boxes = ForumUpdate.format_items_boxes(entity.get("items", []), entity["name"], entity_names)
                items_str = ", ".join(item_boxes) if item_boxes else "None"

                # Format shop listings
                listing_lines = []
                for lst in entity.get("listings", []):
                    listing_lines.append(
                        f"{lst['quantity']}x {lst['item_name']} (#{lst['stack_id']}) "
                        f"— {lst['price_per_unit']} OT Bucks each"
                    )
                listings_str = "\n".join(listing_lines) if listing_lines else "No active listings"

                ledger_lines.append(f"[box={entity['name']}]")
                ledger_lines.append(f"Balance : {entity.get('balance', 0)} OT Bucks")
                ledger_lines.append(f"Members : {members_str}")
                ledger_lines.append(f"Items : {items_str}")
                ledger_lines.append(f"[box=Shop listings]{listings_str}[/box]")
                ledger_lines.append("[/box]")

            ledger_lines.append("[/box]")

        return "\n".join(ledger_lines)



    @staticmethod
    def create_updated_post():
        """Combine static intro text from file, ledger, and leaderboard into final forum post."""
        if not config.DB_PATH.exists():
            return "No data available."

        with open(config.DB_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)

        # Load your formatted intro text
        if config.INTRO_PATH.exists():
            with open(config.INTRO_PATH, "r", encoding="utf-8") as f:
                static_text = f.read().strip()
        else:
            static_text = "[b]OT!Economy[/b] missing intro text file!"

        # Build ledger + leaderboard + entity ledger + command history
        ledger = ForumUpdate.create_ledger(db)
        leaderboard = ForumUpdate.update_leaderboard(db)
        entity_ledger = ForumUpdate.create_entity_ledger()
        command_history = ForumUpdate.create_command_history()

        # Combine final post
        return (
            f"{static_text}\n"
            f"[notice]{leaderboard}\n[/notice]"
            f"[notice][centre][b]OT! Economy Ledger[/b][/centre]\n{ledger}\n[/notice]"
            f"[notice][centre][b]OT! Entities[/b][/centre]\n{entity_ledger}\n[/notice]"
            f"[notice][centre][b]Recent Commands[/b][/centre]\n{command_history}\n[/notice]"
        )

    # === Upload the post ===
    @staticmethod
    def update_post():
        text = ForumUpdate.create_updated_post()
        api.forum_edit_post(post_id=config.POST_ID, body=text)
        print("✅ Forum post updated successfully.")
