from __future__ import annotations

import argparse
import json
import traceback

from openai import OpenAI

from .agent import SessionAgent, ToolEvent
from .config import load_settings
from .logging_utils import SessionLogger
from .sts2_api import Sts2ApiClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Use the OpenAI API to control Slay the Spire 2 through STS2MCP.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a single prompt.")
    run_parser.add_argument("prompt", help="Prompt for the agent.")
    run_parser.add_argument("--model", help="Override OPENAI_MODEL.")
    run_parser.add_argument("--max-rounds", type=int, default=40, help="Maximum tool loop rounds.")
    run_parser.add_argument(
        "--mode",
        choices=["test", "run"],
        default="test",
        help="Terminal display mode. test shows tool activity, run hides tool activity and shows only assistant messages.",
    )
    run_parser.add_argument(
        "--show-tool-output",
        choices=["compact", "full", "off"],
        default="compact",
        help="How much tool output to print.",
    )
    run_parser.add_argument(
        "--log-dir",
        default="logs",
        help="Directory for session logs.",
    )

    chat_parser = subparsers.add_parser("chat", aliases=["repl"], help="Start an interactive chat session.")
    chat_parser.add_argument("--model", help="Override OPENAI_MODEL.")
    chat_parser.add_argument("--max-rounds", type=int, default=40, help="Maximum tool loop rounds.")
    chat_parser.add_argument(
        "--mode",
        choices=["test", "run"],
        default="test",
        help="Terminal display mode. test shows tool activity, run hides tool activity and shows only assistant messages.",
    )
    chat_parser.add_argument(
        "--show-tool-output",
        choices=["compact", "full", "off"],
        default="compact",
        help="How much tool output to print.",
    )
    chat_parser.add_argument(
        "--log-dir",
        default="logs",
        help="Directory for session logs.",
    )

    return parser


def _format_tool_output(output: str, mode: str) -> str:
    if mode == "off":
        return ""

    if mode == "full":
        return output

    compact = output.replace("\n", " ").strip()
    if len(compact) <= 220:
        return compact
    return compact[:217] + "..."


def _print_header(label: str) -> None:
    print(f"\n[{label}]")


def _event_printer(display_mode: str, show_tool_output: str, session_logger: SessionLogger | None = None):
    seen_boundary = False

    def printer(event_type: str, payload: object) -> None:
        if session_logger is not None:
            session_logger.write(event_type, payload)

        if event_type == "assistant_text":
            text = str(payload).strip()
            if text:
                lines = []
                nonlocal seen_boundary
                for raw_line in text.splitlines():
                    line = raw_line.rstrip()
                    if line.strip().startswith("Boundary:"):
                        if seen_boundary:
                            continue
                        seen_boundary = True
                    lines.append(line)
                text = "\n".join(line for line in lines if line.strip()).strip()
            if text:
                _print_header("Assistant")
                print(text)
            return

        if display_mode == "run":
            return

        if event_type == "tool_call":
            call = dict(payload)
            _print_header("Tool")
            print(f"{call['name']}({json.dumps(call['args'], ensure_ascii=False)})")
            return

        if event_type == "tool_output":
            event = payload
            if not isinstance(event, ToolEvent):
                return
            formatted = _format_tool_output(event.output, show_tool_output)
            if formatted:
                _print_header("Tool Output")
                print(formatted)

    return printer


def _build_session(model: str, max_rounds: int) -> SessionAgent:
    settings = load_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    game = Sts2ApiClient(settings.sts2_base_url)
    return SessionAgent(
        openai_client=client,
        sts2_client=game,
        model=model or settings.openai_model,
        max_rounds=max_rounds,
    )


def _run_once(prompt: str, model: str, max_rounds: int, display_mode: str, show_tool_output: str, log_dir: str) -> None:
    session = _build_session(model, max_rounds)
    session_logger = SessionLogger(log_dir)
    print(f"Logging session to {session_logger.path}")
    _print_header("You")
    print(prompt)
    session_logger.write("user_prompt", {"text": prompt})
    try:
        turn = session.run_turn(prompt, event_handler=_event_printer(display_mode, show_tool_output, session_logger))
        session_logger.write("turn_complete", {"response_id": turn.response_id, "final_text": turn.final_text})
    except Exception as exc:
        session_logger.write("error", {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        raise


def _chat(model: str, max_rounds: int, display_mode: str, show_tool_output: str, log_dir: str) -> None:
    session = _build_session(model, max_rounds)
    session_logger = SessionLogger(log_dir)
    print(f"Logging session to {session_logger.path}")
    print("Commands: /reset clears conversation, /exit quits.")
    session_logger.write("session_start", {"mode": "chat", "display_mode": display_mode, "max_rounds": max_rounds})

    while True:
        try:
            prompt = input("\nsts2llm> ").strip()
        except EOFError:
            print()
            return
        if not prompt:
            continue
        if prompt in {"/exit", "exit", "quit"}:
            session_logger.write("session_end", {"reason": "user_exit"})
            return
        if prompt == "/reset":
            session.reset()
            session_logger.write("conversation_reset", {})
            print("Conversation reset.")
            continue

        _print_header("You")
        print(prompt)
        session_logger.write("user_prompt", {"text": prompt})
        try:
            turn = session.run_turn(prompt, event_handler=_event_printer(display_mode, show_tool_output, session_logger))
            session_logger.write("turn_complete", {"response_id": turn.response_id, "final_text": turn.final_text})
        except Exception as exc:
            session_logger.write("error", {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
            raise


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run":
        _run_once(args.prompt, args.model, args.max_rounds, args.mode, args.show_tool_output, args.log_dir)
        return

    if args.command in {"chat", "repl"}:
        _chat(args.model, args.max_rounds, args.mode, args.show_tool_output, args.log_dir)
        return

    raise AssertionError(f"Unhandled command: {args.command}")
