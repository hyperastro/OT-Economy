import sys
import types
import unittest
from unittest.mock import patch


# The production configuration is intentionally gitignored.  These tests only
# exercise inventory transfers, so a minimal in-memory module is sufficient.
config = types.ModuleType("config")
config.BLACKLISTED_ITEMS = []
config.RARITY_ORDER = [("common", 1), ("rare", 2)]
config.RARITY_TOTAL_COST = {"common": 1, "rare": 100}
sys.modules.setdefault("config", config)

# Avoid importing the optional osu! API dependency through economy_commands.
investments = types.ModuleType("Investments.investments")
investments.Investment = type("Investment", (), {})
sys.modules.setdefault("Investments.investments", investments)

from Commands import economy_commands, entity_commands


def item(name, quantity, rarity, stack_id, owners):
    return {
        "name": name,
        "quantity": quantity,
        "rarity": rarity,
        "stack_id": stack_id,
        "history": [
            {"owner": owner, "upgrades": []}
            for owner in owners
        ],
    }


class ItemTransferCollisionTests(unittest.TestCase):
    def test_transfer_keeps_different_rarities_separate_on_id_collision(self):
        database = {
            "1": {
                "username": "sender",
                "balance": 0,
                "items": [item("Gem", 3, "common", "0001", ["sender"])],
            },
            "2": {
                "username": "recipient",
                "balance": 0,
                "items": [item("Gem", 2, "rare", "0001", ["recipient"])],
            },
        }

        with (
            patch.object(economy_commands.Database, "load_db", return_value=database),
            patch.object(economy_commands.Database, "save_db"),
        ):
            self.assertTrue(
                economy_commands.cmd_item_give(
                    ["Gem", "recipient", "0001"], "1", "sender"
                )
            )

        recipient_items = database["2"]["items"]
        self.assertEqual(2, len(recipient_items))
        self.assertEqual(
            [("0001", "rare", 2), ("0002", "common", 3)],
            sorted(
                (stack["stack_id"], stack["rarity"], stack["quantity"])
                for stack in recipient_items
            ),
        )

    def test_partial_transfer_keeps_different_rarities_separate(self):
        database = {
            "1": {
                "username": "sender",
                "balance": 0,
                "items": [item("Gem", 5, "common", "0001", ["sender"])],
            },
            "2": {
                "username": "recipient",
                "balance": 0,
                "items": [item("Gem", 2, "rare", "0001", ["recipient"])],
            },
        }

        with (
            patch.object(economy_commands.Database, "load_db", return_value=database),
            patch.object(economy_commands.Database, "save_db"),
        ):
            self.assertTrue(
                economy_commands.cmd_item_give(
                    ["Gem", "recipient", "0001", "3"], "1", "sender"
                )
            )

        self.assertEqual(2, database["1"]["items"][0]["quantity"])
        self.assertEqual(
            [("0001", "rare", 2), ("0002", "common", 3)],
            sorted(
                (stack["stack_id"], stack["rarity"], stack["quantity"])
                for stack in database["2"]["items"]
            ),
        )

    def test_transfer_merges_an_identical_lineage(self):
        database = {
            "1": {
                "username": "sender",
                "balance": 0,
                "items": [item("Gem", 3, "common", "0001", ["sender"])],
            },
            "2": {
                "username": "recipient",
                "balance": 0,
                "items": [
                    item("Gem", 2, "common", "0001", ["sender", "recipient"])
                ],
            },
        }

        with (
            patch.object(economy_commands.Database, "load_db", return_value=database),
            patch.object(economy_commands.Database, "save_db"),
        ):
            self.assertTrue(
                economy_commands.cmd_item_give(
                    ["Gem", "recipient", "0001"], "1", "sender"
                )
            )

        self.assertEqual(1, len(database["2"]["items"]))
        self.assertEqual(5, database["2"]["items"][0]["quantity"])

    def test_transfer_keeps_different_histories_separate(self):
        database = {
            "1": {
                "username": "sender",
                "balance": 0,
                "items": [item("Gem", 3, "common", "0001", ["sender"])],
            },
            "2": {
                "username": "recipient",
                "balance": 0,
                "items": [item("Gem", 2, "common", "0001", ["recipient"])],
            },
        }

        with (
            patch.object(economy_commands.Database, "load_db", return_value=database),
            patch.object(economy_commands.Database, "save_db"),
        ):
            self.assertTrue(
                economy_commands.cmd_item_give(
                    ["Gem", "recipient", "0001"], "1", "sender"
                )
            )

        self.assertEqual(2, len(database["2"]["items"]))
        self.assertEqual(
            {"0001", "0002"},
            {stack["stack_id"] for stack in database["2"]["items"]},
        )


class ShopPurchaseCollisionTests(unittest.TestCase):
    def test_purchase_keeps_different_rarities_separate_on_id_collision(self):
        database = {
            "2": {
                "username": "buyer",
                "balance": 100,
                "items": [item("Gem", 2, "rare", "0001", ["buyer"])],
            }
        }
        entities = {
            "Shop": {
                "name": "Shop",
                "balance": 0,
                "items": [item("Gem", 10, "common", "0001", ["Shop"])],
                "listings": [
                    {
                        "item_name": "Gem",
                        "stack_id": "0001",
                        "quantity": 10,
                        "price_per_unit": 1,
                    }
                ],
            }
        }

        with (
            patch.object(entity_commands.Database, "load_db", return_value=database),
            patch.object(entity_commands.Database, "save_db"),
            patch.object(entity_commands.Entity, "load_entities", return_value=entities),
            patch.object(entity_commands.Entity, "save_entities"),
        ):
            self.assertTrue(
                entity_commands.cmd_buy(
                    ["Gem", "Shop", "0001", "3"], "2", "buyer"
                )
            )

        buyer_items = database["2"]["items"]
        self.assertEqual(2, len(buyer_items))
        self.assertEqual(
            [("0001", "rare", 2), ("0002", "common", 3)],
            sorted(
                (stack["stack_id"], stack["rarity"], stack["quantity"])
                for stack in buyer_items
            ),
        )

    def test_common_purchase_cannot_inflate_rare_stack_or_create_profit(self):
        database = {
            "2": {
                "username": "buyer",
                "balance": 100,
                "items": [item("Gem", 1, "rare", "0001", ["buyer"])],
            }
        }
        entities = {
            "Buyer Shop": {
                "name": "Buyer Shop",
                "balance": 0,
                "items": [
                    item("Gem", 1, "common", "0001", ["Buyer Shop"])
                ],
                "listings": [
                    {
                        "item_name": "Gem",
                        "stack_id": "0001",
                        "quantity": 1,
                        "price_per_unit": 1,
                    }
                ],
            }
        }

        with (
            patch.object(entity_commands.Database, "load_db", return_value=database),
            patch.object(entity_commands.Database, "save_db"),
            patch.object(entity_commands.Entity, "load_entities", return_value=entities),
            patch.object(entity_commands.Entity, "save_entities"),
        ):
            self.assertTrue(
                entity_commands.cmd_buy(
                    ["Gem", "Buyer Shop", "0001", "1"], "2", "buyer"
                )
            )

        purchased = next(
            stack
            for stack in database["2"]["items"]
            if stack["stack_id"] != "0001"
        )
        self.assertEqual("common", purchased["rarity"])

        with (
            patch.object(economy_commands.Database, "load_db", return_value=database),
            patch.object(economy_commands.Database, "save_db"),
        ):
            self.assertTrue(
                economy_commands.cmd_item_delete(
                    ["Gem", purchased["stack_id"], "1"], "2", "buyer"
                )
            )

        self.assertEqual(99, database["2"]["balance"])
        self.assertEqual(
            [("0001", "rare", 1)],
            [
                (stack["stack_id"], stack["rarity"], stack["quantity"])
                for stack in database["2"]["items"]
            ],
        )


if __name__ == "__main__":
    unittest.main()
