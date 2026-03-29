from __future__ import annotations

TOOLS: list[dict] = [
    {
        "type": "function",
        "name": "get_card_info",
        "description": "Look up a card by exact runtime card id and return its reference entry.",
        "parameters": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "string",
                    "description": "Exact runtime card id, for example BASH or DEFEND_IRONCLAD.",
                }
            },
            "required": ["card_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_enemy_info",
        "description": "Look up an enemy by entity_id or exact monster_id and return its reference entry.",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Runtime entity_id, for example TOADPOLE_1.",
                },
                "monster_id": {
                    "type": "string",
                    "description": "Exact base monster id, for example TOADPOLE.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_relic_info",
        "description": "Look up a relic by exact runtime relic id and return its reference entry.",
        "parameters": {
            "type": "object",
            "properties": {
                "relic_id": {
                    "type": "string",
                    "description": "Exact runtime relic id, for example BURNING_BLOOD.",
                }
            },
            "required": ["relic_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_game_state",
        "description": "Read the current Slay the Spire 2 game state. Use format=json when making decisions.",
        "parameters": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["json", "markdown"],
                    "description": "Response format.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "combat_play_card",
        "description": "Play a card during combat. Prefer card_instance_id over card_index.",
        "parameters": {
            "type": "object",
            "properties": {
                "card_index": {"type": "integer", "description": "Legacy hand index."},
                "card_instance_id": {"type": "string", "description": "Stable card instance id."},
                "target": {"type": "string", "description": "Target entity_id when required."},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "combat_end_turn",
        "description": "End the current combat turn.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "combat_select_card",
        "description": "Select a card during an in-combat card selection prompt. Prefer card_instance_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "card_index": {"type": "integer"},
                "card_instance_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "combat_confirm_selection",
        "description": "Confirm in-combat card selection.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "map_choose_node",
        "description": "Choose a map node from map.next_options by index.",
        "parameters": {
            "type": "object",
            "properties": {"node_index": {"type": "integer"}},
            "required": ["node_index"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "event_choose_option",
        "description": "Choose an event option by index.",
        "parameters": {
            "type": "object",
            "properties": {"option_index": {"type": "integer"}},
            "required": ["option_index"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "advance_dialogue",
        "description": "Advance ancient dialogue until options become available.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "proceed_to_map",
        "description": "Proceed from rewards, rest site, shop, or treasure screens.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "rewards_claim",
        "description": "Claim a reward from the combat rewards screen.",
        "parameters": {
            "type": "object",
            "properties": {"reward_index": {"type": "integer"}},
            "required": ["reward_index"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "rewards_pick_card",
        "description": "Pick a card reward. Prefer card_instance_id over card_index.",
        "parameters": {
            "type": "object",
            "properties": {
                "card_index": {"type": "integer"},
                "card_instance_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "rewards_skip_card",
        "description": "Skip a card reward.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "deck_select_card",
        "description": "Select a card in an out-of-combat grid selection screen. Prefer card_instance_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "card_index": {"type": "integer"},
                "card_instance_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "deck_confirm_selection",
        "description": "Confirm an out-of-combat deck selection.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "deck_cancel_selection",
        "description": "Cancel or back out of a deck selection preview.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "rest_choose_option",
        "description": "Choose a rest site option by index.",
        "parameters": {
            "type": "object",
            "properties": {"option_index": {"type": "integer"}},
            "required": ["option_index"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "shop_purchase",
        "description": "Purchase a shop item by index.",
        "parameters": {
            "type": "object",
            "properties": {"item_index": {"type": "integer"}},
            "required": ["item_index"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "relic_select",
        "description": "Select a relic by index from a relic selection screen.",
        "parameters": {
            "type": "object",
            "properties": {"relic_index": {"type": "integer"}},
            "required": ["relic_index"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "relic_skip",
        "description": "Skip relic selection.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "treasure_claim_relic",
        "description": "Claim a relic from treasure by index.",
        "parameters": {
            "type": "object",
            "properties": {"relic_index": {"type": "integer"}},
            "required": ["relic_index"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "use_potion",
        "description": "Use a potion by slot, with an optional target entity_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "slot": {"type": "integer"},
                "target": {"type": "string"},
            },
            "required": ["slot"],
            "additionalProperties": False,
        },
    },
]
