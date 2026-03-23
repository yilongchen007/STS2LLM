from __future__ import annotations

import json
from typing import Any

import httpx


class Sts2ApiClient:
    def __init__(self, base_url: str) -> None:
        self._endpoint = f"{base_url}/api/v1/singleplayer"

    def get_game_state(self, format: str = "json") -> str:
        response = httpx.get(self._endpoint, params={"format": format}, timeout=15)
        response.raise_for_status()
        return response.text

    def post_action(self, body: dict[str, Any]) -> str:
        response = httpx.post(self._endpoint, json=body, timeout=15)
        response.raise_for_status()
        return response.text

    def _card_action_payload(
        self,
        *,
        action: str,
        card_index: int | None = None,
        card_instance_id: str | None = None,
        index_field: str = "card_index",
        target: str | None = None,
    ) -> dict[str, Any]:
        if card_index is None and card_instance_id is None:
            raise ValueError("Provide either card_instance_id or card_index.")

        payload: dict[str, Any] = {"action": action}
        if card_index is not None:
            payload[index_field] = card_index
        if card_instance_id is not None:
            payload["card_instance_id"] = card_instance_id
        if target is not None:
            payload["target"] = target
        return payload

    def tool_call(self, name: str, args: dict[str, Any]) -> str:
        match name:
            case "get_game_state":
                return self.get_game_state(format=args.get("format", "json"))
            case "combat_play_card":
                return self.post_action(
                    self._card_action_payload(
                        action="play_card",
                        card_index=args.get("card_index"),
                        card_instance_id=args.get("card_instance_id"),
                        target=args.get("target"),
                    )
                )
            case "combat_end_turn":
                return self.post_action({"action": "end_turn"})
            case "combat_select_card":
                return self.post_action(
                    self._card_action_payload(
                        action="combat_select_card",
                        card_index=args.get("card_index"),
                        card_instance_id=args.get("card_instance_id"),
                    )
                )
            case "combat_confirm_selection":
                return self.post_action({"action": "combat_confirm_selection"})
            case "map_choose_node":
                return self.post_action({"action": "choose_map_node", "index": args["node_index"]})
            case "event_choose_option":
                return self.post_action({"action": "choose_event_option", "index": args["option_index"]})
            case "advance_dialogue":
                return self.post_action({"action": "advance_dialogue"})
            case "proceed_to_map":
                return self.post_action({"action": "proceed"})
            case "rewards_claim":
                return self.post_action({"action": "claim_reward", "index": args["reward_index"]})
            case "rewards_pick_card":
                return self.post_action(
                    self._card_action_payload(
                        action="select_card_reward",
                        card_index=args.get("card_index"),
                        card_instance_id=args.get("card_instance_id"),
                    )
                )
            case "rewards_skip_card":
                return self.post_action({"action": "skip_card_reward"})
            case "deck_select_card":
                return self.post_action(
                    self._card_action_payload(
                        action="select_card",
                        card_index=args.get("card_index"),
                        card_instance_id=args.get("card_instance_id"),
                        index_field="index",
                    )
                )
            case "deck_confirm_selection":
                return self.post_action({"action": "confirm_selection"})
            case "deck_cancel_selection":
                return self.post_action({"action": "cancel_selection"})
            case "rest_choose_option":
                return self.post_action({"action": "choose_rest_option", "index": args["option_index"]})
            case "shop_purchase":
                return self.post_action({"action": "shop_purchase", "index": args["item_index"]})
            case "relic_select":
                return self.post_action({"action": "select_relic", "index": args["relic_index"]})
            case "relic_skip":
                return self.post_action({"action": "skip_relic_selection"})
            case "treasure_claim_relic":
                return self.post_action({"action": "claim_treasure_relic", "index": args["relic_index"]})
            case "use_potion":
                payload: dict[str, Any] = {"action": "use_potion", "slot": args["slot"]}
                if args.get("target"):
                    payload["target"] = args["target"]
                return self.post_action(payload)
            case _:
                raise ValueError(f"Unknown tool: {name}")


def stringify_tool_result(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(parsed, ensure_ascii=False)
