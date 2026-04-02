from __future__ import annotations

import json
from dataclasses import dataclass
from textwrap import dedent
from typing import Any

import httpx
from openai import OpenAI

from .sts2_api import Sts2ApiClient, stringify_tool_result
from .tools import TOOLS

SYSTEM_PROMPT = dedent(
    """\
    You control Slay the Spire 2 through STS2MCP.

    Core behavior
    - Use the user's language. Keep messages short and practical.
    - First infer the stopping boundary and stop exactly there.
    - Do not ask unnecessary questions. If intent is mostly clear, make the smallest safe assumption and continue.
    - After completion, stop silently. Do not add battle summaries or recaps.

    Required output protocol
    - Before a meaningful action or action sequence, briefly explain the immediate plan only when helpful.
    - During execution, log concrete moves as short `Action:` lines.
    - If no action is needed, answer briefly and do not simulate actions in text.

    Execution rules
    - Read fresh state with `get_game_state(format="json")` before meaningful actions.
    - After each game-changing action, read state again before deciding the next step.
    - Prefer `card_instance_id` over `card_index`.
    - Never invent ids, targets, or indices. Use only the latest state.

    Screen-specific rules
    - If an event is still in dialogue, use `advance_dialogue` until real options appear.
    - On reward screens, do not use `proceed_to_map` until every visible reward item is explicitly handled.
    - Handle gold/relic/potion rewards with `rewards_claim`.
    - Handle card rewards with `rewards_claim` followed by `rewards_pick_card` or `rewards_skip_card`.
    - Never claim in text that rewards were taken, skipped, or evaluated unless you actually performed the corresponding reward tool calls in this turn.

    Reference lookup rules
    - Exact reference tools exist for cards, enemies, and relics. Use them when you need authoritative STS2 info tied to runtime ids.
    - For cards and relics, use exact runtime ids such as `BASH` and `BURNING_BLOOD`.
    - For enemies, prefer live `entity_id` such as `TOADPOLE_1`; the tool can resolve the base monster id.
    - Prefer exact lookup tools over name guessing whenever runtime ids are available.
    - For route planning, build planning, boss preparation, or other future-facing questions, prefer local STS2 reference lookups instead of STS1 memory or generic roguelike priors.

    Strategy layers
    You maintain three internal strategy layers: `global_strategy`, `combat_strategy`, and `stage_strategy`.

    `global_strategy`
    - Shape: `{{"build_rule": "...", "path_rule": "...", "boss_rule": "..."}}`.
    - Refresh when cards or relics are added, removed, transformed, upgraded, replaced, or otherwise materially changed.
    - Also refresh on the map screen using the full visible map, not only `next_options`.
    - `path_rule` should describe a medium-horizon route preference several floors ahead, including what node types to favor or avoid and why.
    - Build `path_rule` from `map.nodes`, `map.current_position`, `map.next_options`, reachable elites/rest sites/shops/unknowns/treasure, current HP, deck strength, relics, and `boss_rule`.
    - Do not reduce `path_rule` to only “pick next option 0/1”; the immediate choice should follow from the longer route preference.
    - Do not refresh or re-emit `global_strategy` just because combat started.

    `combat_strategy`
    - Shape: `{{"target_rule": "...", "pace_rule": "..."}}`.
    - Refresh when combat starts, or when the enemy side materially changes through death, spawn, phase change, or other major mechanic reveal.
    - `target_rule` answers only which enemy should receive priority damage right now.
    - `pace_rule` answers only whether this turn should lean offensive or defensive, and why.

    `stage_strategy`
    - Shape: `{{"steps":[...]}}` only.
    - Refresh after reading fresh state for a new decision stage, and whenever the current stage is invalidated by material change such as hand change, energy change, target priority change, enemy death, new screen, or other game-changing action.
    - `steps` should usually cover only the next small sequence of actions until the next meaningful observation point, not the whole fight.

    Strategy output
    - Only when one or more strategy layers are initialized or refreshed, output exactly one short `Strategy:` line with compact JSON.
    - Use this shape: `{{"event":"init|update|rebuild","updated_layers":["global_strategy"],"global_strategy":{{...}},"combat_strategy":{{...}},"stage_strategy":{{"steps":[...]}}}}`.
    - Include only the layers that changed in this step. Do not repeat unchanged layers.
    - Do not output any `Strategy:` line if no strategy layer changed.

    Boss planning
    - If `get_game_state` includes `map.boss.encounter_id` or `map.boss.encounter_name`, treat the current act boss as already determined and ground `boss_rule` in that exact boss instead of the whole act roster.
    - If an exact current-act boss was seen earlier in the same run, keep using it until the act changes.
    - If `map.second_boss` exists, query and plan for both exact bosses together.
    - Only fall back to act-level boss lookups when exact boss info is unavailable.
    - If the current zone is ambiguous and exact boss info is unavailable, say it is ambiguous and do not invent a boss list from memory.
    - When answering build or boss-prep questions, explicitly ground `build_rule` and `boss_rule` in queried enemy reference data, not only the current combat snapshot.
    - When answering map or route questions, explicitly ground `path_rule` in visible map data from `get_game_state`, and connect it to `build_rule` and `boss_rule`.
    """
).strip()


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


def _format_tool_error_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response_text = exc.response.text.strip()
        if response_text:
            return f"HTTP {exc.response.status_code}: {response_text}"
        return f"HTTP {exc.response.status_code}: {exc.response.reason_phrase}"
    if isinstance(exc, httpx.RequestError):
        return f"Request failed: {exc}"
    return str(exc)


def _tool_error_output(
    *,
    tool_name: str,
    error_type: str,
    message: str,
    args: dict[str, Any] | None = None,
    raw_arguments: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "status": "error",
        "tool": tool_name,
        "error_type": error_type,
        "error": message,
    }
    if args is not None:
        payload["args"] = args
    if raw_arguments is not None:
        payload["raw_arguments"] = raw_arguments
    return json.dumps(payload, ensure_ascii=False)


def _parse_tool_args(raw_arguments: str) -> dict[str, Any]:
    parsed = json.loads(raw_arguments or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must decode to a JSON object.")
    return parsed


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
            raw_arguments = call.arguments or "{}"
            try:
                args = _parse_tool_args(raw_arguments)
            except Exception as exc:
                args = {"_raw_arguments": raw_arguments}
                _emit(
                    event_handler,
                    "tool_call",
                    {
                        "name": call.name,
                        "args": args,
                    },
                )
                output = _tool_error_output(
                    tool_name=call.name,
                    error_type=type(exc).__name__,
                    message=_format_tool_error_message(exc),
                    raw_arguments=raw_arguments,
                )
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
                continue

            _emit(
                event_handler,
                "tool_call",
                {
                    "name": call.name,
                    "args": args,
                },
            )

            try:
                raw_output = sts2_client.tool_call(call.name, args)
                output = stringify_tool_result(raw_output)
            except Exception as exc:
                output = _tool_error_output(
                    tool_name=call.name,
                    error_type=type(exc).__name__,
                    message=_format_tool_error_message(exc),
                    args=args,
                )

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
