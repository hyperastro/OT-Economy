import json
import config

class Entity:

    @staticmethod
    def load_entities():
        if config.ENTITIES_PATH.exists():
            with open(config.ENTITIES_PATH, "r") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    @staticmethod
    def save_entities(entities):
        with open(config.ENTITIES_PATH, "w") as f:
            json.dump(entities, f, indent=4)

    @staticmethod
    def find_entity(entities, name):
        """Case-insensitive entity lookup. Returns (key, entity_dict) or (None, None)."""
        name_lower = name.strip().lower()
        for key, entity in entities.items():
            if key.lower() == name_lower:
                return key, entity
        return None, None

    @staticmethod
    def is_creator(entity, user_id):
        return str(entity["creator_id"]) == str(user_id)

    @staticmethod
    def is_member(entity, user_id):
        uid = str(user_id)
        return str(entity["creator_id"]) == uid or uid in [str(e) for e in entity.get("employee_ids", [])]

    @staticmethod
    def next_entity_stack_id(items, item_name):
        """Generate next stack ID for an item type inside an entity's inventory."""
        same = [it for it in items if it["name"].lower() == item_name.lower()]
        if not same:
            return "0001"
        max_id = max(int(it["stack_id"]) for it in same)
        return f"{max_id + 1:04d}"
