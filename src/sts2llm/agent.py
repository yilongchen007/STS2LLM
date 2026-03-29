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
16. When the requested actions are complete, do not add a battle summary or recap unless the user explicitly asked for one.
17. After completion, either stop silently or give one short completion line if needed.
18. Keep messages short and practical.
19. Exact reference lookup tools are available for cards, enemies, and relics. Use them when you need authoritative reference info tied to runtime ids.
20. For cards and relics, use exact runtime ids such as `BASH` or `BURNING_BLOOD`.
21. For enemies, prefer passing the live `entity_id` such as `TOADPOLE_1`; the tool can resolve the base monster id.
22. Prefer exact lookup tools over name-based guessing when runtime ids are available.
23. Maintain three internal strategy layers: `global_strategy`, `combat_strategy`, and `stage_strategy`.
24. `global_strategy` is a compact object with three fields: `build_rule`, `path_rule`, and `boss_rule`.
25. Generate or refresh `global_strategy` when cards or relics are added, removed, transformed, upgraded, replaced, or otherwise materially changed.
26. `combat_strategy` is a compact object with three fields: `target_rule`, `pace_rule`, and `danger_rule`.
27. Generate or refresh `combat_strategy` when combat starts, or when the enemy side materially changes through death, spawn, phase change, or other major mechanic reveal.
28. `stage_strategy` is a short ordered list of next-step instructions for the current observation window. It should be concrete enough to specify action order, preferred targets, and when to stop and re-observe.
29. Generate or refresh `stage_strategy` after reading fresh state for a new decision stage, and whenever the current stage is invalidated by material change such as hand change, energy change, enemy death, target priority change, new screen, or other game-changing action.
30. `stage_strategy` should usually cover only the next small sequence of actions until the next meaningful observation point, not the entire fight by default.
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
