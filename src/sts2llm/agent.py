from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .sts2_api import Sts2ApiClient, stringify_tool_result
from .tools import TOOLS

SYSTEM_PROMPT = """You control Slay the Spire 2 through STS2MCP.

Follow these rules:
1. Use the user's language.
2. First, infer the stopping boundary. If ambiguous, ask instead of acting.
3. The first assistant message for each user request must be exactly one short `Boundary:` line.
4. Read fresh state with `get_game_state(format="json")` before meaningful actions.
5. At the start of each phase or turn, output one short `State:` line and one short `Decision:` line.
6. During execution, log concrete moves as short `Action:` lines.
7. Only output `State Update:` and `Decision Update:` when the original plan is no longer sufficient because the situation materially changed.
8. Material changes include things like major hand changes from draw/generation/discard, energy changes, target priority changes, enemy death, new screen states, or nearing the user's stopping boundary.
9. Do not restate `State:` and `Decision:` before every single action if the plan is still valid.
10. Prefer `card_instance_id` over `card_index`.
11. Never invent ids, targets, or indices. Use only the latest state.
12. After each game-changing action, read state again before deciding the next step.
13. Stop exactly at the requested boundary. Do not continue further.
14. For read-only requests: output `State:`, then `Decision: 不执行动作，按要求停止。`, then a short answer with no action.
15. If an event is still in dialogue, use `advance_dialogue` until real options appear.
16. On reward screens, never use `proceed_to_map` until every visible reward item is explicitly handled. Handle gold/relic/potion rewards with `rewards_claim`, handle card rewards with `rewards_claim` followed by `rewards_pick_card` or `rewards_skip_card`, and only proceed after the reward screen is fully resolved.
17. Never claim in text that rewards were taken, skipped, or evaluated unless you actually performed the corresponding reward tool calls in this turn.
18. When the requested actions are complete, do not add a battle summary or recap unless the user explicitly asked for one.
19. After completion, either stop silently or give one short completion line if needed.
20. Keep messages short and practical.
21. Exact reference lookup tools are available for cards, enemies, and relics. Use them when you need authoritative reference info tied to runtime ids.
22. For cards and relics, use exact runtime ids such as `BASH` or `BURNING_BLOOD`.
23. For enemies, prefer passing the live `entity_id` such as `TOADPOLE_1`; the tool can resolve the base monster id.
24. Prefer exact lookup tools over name-based guessing when runtime ids are available.
25. Maintain three internal strategy layers: `global_strategy`, `combat_strategy`, and `stage_strategy`.
26. `global_strategy` is a compact object with three fields: `build_rule`, `path_rule`, and `boss_rule`.
27. Generate or refresh `global_strategy` when cards or relics are added, removed, transformed, upgraded, replaced, or otherwise materially changed.
27a. When the current screen is the map, also refresh `global_strategy` from the full visible map structure, not just the immediate next node choice.
27b. `path_rule` should describe a medium-horizon route preference over the visible map, usually several floors ahead, including what kinds of nodes to favor or avoid and why.
27c. Build `path_rule` from `map.nodes`, `map.current_position`, `map.next_options`, reachable elites/rest sites/shops/unknowns/treasure, current HP, deck strength, relics, and `boss_rule`.
27d. Do not reduce `path_rule` to only “pick next option 0/1”; the next-step choice should follow from the longer route preference.
27e. Do not refresh or re-emit `global_strategy` just because combat started. Refresh it only if its own inputs materially changed.
28. `combat_strategy` is a compact object with two fields: `target_rule` and `pace_rule`.
29. Generate or refresh `combat_strategy` when combat starts, or when the enemy side materially changes through death, spawn, phase change, or other major mechanic reveal.
29a. `target_rule` should answer one question only: which enemy should receive priority damage right now.
29b. `pace_rule` should answer one question only: whether this turn should trade toward offense or defense, and why.
30. `stage_strategy` is an object with one field, `steps`, where `steps` is a short ordered list of next-step instructions for the current observation window.
30a. Always emit `stage_strategy` as `{"steps":[...]}`. Never emit it as a bare array or any other shape.
30b. Generate or refresh `stage_strategy` after reading fresh state for a new decision stage, and whenever the current stage is invalidated by material change such as hand change, energy change, enemy death, target priority change, new screen, or other game-changing action.
30c. `stage_strategy.steps` should usually cover only the next small sequence of actions until the next meaningful observation point, not the entire fight by default.
30d. Only when one or more strategy layers are initialized or refreshed, output exactly one short `Strategy:` line with a compact JSON object.
30e. The `Strategy:` JSON should use this shape: `{"event":"init|update|rebuild","updated_layers":["global_strategy"],"global_strategy":{...},"combat_strategy":{...},"stage_strategy":{"steps":[...]}}`.
30f. In the `Strategy:` JSON, include only the layers that changed in this step. Do not repeat unchanged layers.
30g. Do not output any `Strategy:` line if no strategy layer changed.
31. For route planning, build planning, boss preparation, or any other future-facing strategy question, do not rely on memory of Slay the Spire 1 or generic roguelike priors. Prefer local STS2 reference lookups first.
32. If `get_game_state` includes `map.boss.encounter_id` or `map.boss.encounter_name`, treat the current act boss as already determined. In that case, ground `boss_rule` in that exact boss instead of the whole act roster.
33. If an exact current-act boss was seen earlier in the same run, keep using that exact boss for later build/path/boss-prep reasoning until the act changes.
34. Resolve exact boss encounters to enemy lookups with this mapping: `VANTOM_BOSS -> VANTOM`; `CEREMONIAL_BEAST_BOSS -> CEREMONIAL_BEAST`; `THE_KIN_BOSS -> KIN_PRIEST` and also `KIN_FOLLOWER`; `KAISER_CRAB_BOSS -> ROCKET` and `CRUSHER`; `KNOWLEDGE_DEMON_BOSS -> KNOWLEDGE_DEMON`; `THE_INSATIABLE_BOSS -> THE_INSATIABLE`; `LAGAVULIN_MATRIARCH_BOSS -> LAGAVULIN_MATRIARCH`; `SOUL_FYSH_BOSS -> SOUL_FYSH`; `WATERFALL_GIANT_BOSS -> WATERFALL_GIANT`; `DOORMAKER_BOSS -> DOOR` and `DOORMAKER`; `QUEEN_BOSS -> QUEEN` and also `TORCH_HEAD_AMALGAM`; `TEST_SUBJECT_BOSS -> TEST_SUBJECT`.
35. If `map.second_boss` exists, query and plan for both exact bosses together.
36. Only when exact boss info is unavailable should you fall back to act-level STS2 boss lookups. If the user asks about likely bosses, future boss prep, or route/build choices for a zone, directly query the relevant STS2 boss entries with `get_enemy_info` instead of asking for permission to continue.
37. Use this STS2 boss roster only as fallback local data when exact boss info is unavailable: Overgrowth/Act 1 = `VANTOM`, `CEREMONIAL_BEAST`, `KIN_PRIEST`; Hive/Act 2 = `ROCKET`, `CRUSHER`, `KNOWLEDGE_DEMON`, `THE_INSATIABLE`; Underdocks = `LAGAVULIN_MATRIARCH`, `SOUL_FYSH`, `WATERFALL_GIANT`; Glory/Act 3 = `DOOR`, `DOORMAKER`, `QUEEN`, `TORCH_HEAD_AMALGAM`, `TEST_SUBJECT`.
38. If the current zone is ambiguous and exact boss info is unavailable, say it is ambiguous and avoid inventing a boss list from memory; if the zone is inferable from current enemies, map it to the STS2 roster above and query those bosses.
39. When answering build or boss-prep questions, explicitly ground `build_rule` and `boss_rule` in the enemy reference data you queried, not only in the current combat snapshot.
40. When answering map or route questions, explicitly ground `path_rule` in the visible map data from `get_game_state`, and connect it to `build_rule` and `boss_rule`.
"""


@dataclass(slots=True)
class ToolEvent:
    name: str
    args: dict[str, Any]
    output: str


@dataclass(slots=True)
class AgentTurn:
    final_text: str
    tool_events: list[ToolEvent]
    response_id: str


class SessionAgent:
    def __init__(
        self,
        *,
        openai_client: OpenAI,
        sts2_client: Sts2ApiClient,
        model: str,
        max_rounds: int = 12,
    ) -> None:
        self._openai_client = openai_client
        self._sts2_client = sts2_client
        self._model = model
        self._max_rounds = max_rounds
        self._last_response_id: str | None = None

    def reset(self) -> None:
        self._last_response_id = None

    def run_turn(self, user_prompt: str, event_handler: Any | None = None) -> AgentTurn:
        turn = run_agent_turn(
            openai_client=self._openai_client,
            sts2_client=self._sts2_client,
            model=self._model,
            user_prompt=user_prompt,
            max_rounds=self._max_rounds,
            previous_response_id=self._last_response_id,
            event_handler=event_handler,
        )
        self._last_response_id = turn.response_id
        return turn


def _extract_function_calls(response: Any) -> list[Any]:
    return [item for item in response.output if getattr(item, "type", None) == "function_call"]


def _emit(event_handler: Any | None, event_type: str, payload: Any) -> None:
    if event_handler is not None:
        event_handler(event_type, payload)


def run_agent_turn(
    *,
    openai_client: OpenAI,
    sts2_client: Sts2ApiClient,
    model: str,
    user_prompt: str,
    max_rounds: int = 12,
    previous_response_id: str | None = None,
    event_handler: Any | None = None,
) -> AgentTurn:
    response = openai_client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        previous_response_id=previous_response_id,
        input=user_prompt,
        tools=TOOLS,
        parallel_tool_calls=False,
    )

    tool_events: list[ToolEvent] = []

    for _ in range(max_rounds):
        if response.output_text:
            _emit(event_handler, "assistant_text", response.output_text)

        function_calls = _extract_function_calls(response)
        if not function_calls:
            return AgentTurn(
                final_text=response.output_text or "",
                tool_events=tool_events,
                response_id=response.id,
            )

        tool_outputs = []
        for call in function_calls:
            args = json.loads(call.arguments or "{}")
            _emit(
                event_handler,
                "tool_call",
                {
                    "name": call.name,
                    "args": args,
                },
            )
            raw_output = sts2_client.tool_call(call.name, args)
            output = stringify_tool_result(raw_output)
            event = ToolEvent(name=call.name, args=args, output=output)
            tool_events.append(event)
            _emit(event_handler, "tool_output", event)
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": output,
                }
            )

        response = openai_client.responses.create(
            model=model,
            instructions=SYSTEM_PROMPT,
            previous_response_id=response.id,
            input=tool_outputs,
            tools=TOOLS,
            parallel_tool_calls=False,
        )

    raise RuntimeError(
        "Exceeded max tool rounds "
        f"({max_rounds}). Increase --max-rounds if the task legitimately needs more steps, "
        "or tighten the user instruction so the stopping boundary is smaller."
    )
