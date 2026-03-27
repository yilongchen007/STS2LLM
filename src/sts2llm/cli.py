from __future__ import annotations

import argparse
import json
import traceback
from typing import TYPE_CHECKING, Any

from .enemy_pack import build_enemy_pack
from .games_gg_guides import crawl_games_gg_guides
from .reference_packs import build_reference_packs
from .wiki_gg_crawler import crawl_wiki_gg, crawl_wiki_gg_act_enemies

if TYPE_CHECKING:
    from .agent import SessionAgent


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

    crawl_games_gg_parser = subparsers.add_parser(
        "crawl-games-gg-guides",
        help="Fetch raw guide data from games.gg and save it under data/raw.",
    )
    crawl_games_gg_parser.add_argument(
        "--game-slug",
        default="slay-the-spire-2",
        help="games.gg game slug to crawl.",
    )
    crawl_games_gg_parser.add_argument(
        "--output-dir",
        default="data/raw/games_gg",
        help="Base output directory for raw crawl artifacts.",
    )
    crawl_games_gg_parser.add_argument(
        "--limit",
        type=int,
        help="Optional cap on the number of guide URLs to fetch.",
    )
    crawl_games_gg_parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Reuse existing article/html files when present.",
    )

    crawl_wiki_gg_parser = subparsers.add_parser(
        "crawl-wiki-gg",
        help="Fetch wiki.gg pages with a real Chrome session and save raw page data under data/raw.",
    )
    crawl_wiki_gg_parser.add_argument(
        "start_url",
        help="Starting wiki.gg page URL.",
    )
    crawl_wiki_gg_parser.add_argument(
        "--output-dir",
        default="data/raw/wiki_gg",
        help="Base output directory for raw crawl artifacts.",
    )
    crawl_wiki_gg_parser.add_argument(
        "--max-depth",
        type=int,
        default=1,
        help="Maximum link depth to follow from the starting page.",
    )
    crawl_wiki_gg_parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum number of pages to save in this crawl.",
    )
    crawl_wiki_gg_parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Reuse existing article/html files when present.",
    )
    crawl_wiki_gg_parser.add_argument(
        "--browser-binary",
        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        help="Chrome browser binary used for the crawl.",
    )
    crawl_wiki_gg_parser.add_argument(
        "--profile-dir",
        default="/tmp/sts2llm-wikigg-profile",
        help="Chrome user-data directory used during the crawl.",
    )
    crawl_wiki_gg_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome headless. wiki.gg may require a visible browser session instead.",
    )

    crawl_wiki_gg_act_enemies_parser = subparsers.add_parser(
        "crawl-wiki-gg-act-enemies",
        help="Fetch enemy pages linked from selected act pages and save them under data/raw.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--source-dir",
        default="data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Main",
        help="Previously crawled wiki.gg directory that contains the act page JSON files.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--acts",
        nargs="+",
        default=["Overgrowth", "Underdocks", "Hive", "Glory"],
        help="Act page names to scan for encounter links.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--sections",
        nargs="+",
        default=["Monsters", "Elites", "Bosses"],
        help="Top-level h2 sections to include from each act page.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--crawl-name",
        default="Slay_the_Spire_2_Act_Enemies",
        help="Output subdirectory name for this explicit-target crawl.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--output-dir",
        default="data/raw/wiki_gg",
        help="Base output directory for raw crawl artifacts.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Reuse existing article/html files when present.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--browser-binary",
        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        help="Chrome browser binary used for the crawl.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--profile-dir",
        default="/tmp/sts2llm-wikigg-profile",
        help="Chrome user-data directory used during the crawl.",
    )
    crawl_wiki_gg_act_enemies_parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome headless. wiki.gg may require a visible browser session instead.",
    )

    build_enemy_pack_parser = subparsers.add_parser(
        "build-enemy-pack",
        help="Build a simplified enemy_pack.json from previously crawled wiki.gg enemy pages.",
    )
    build_enemy_pack_parser.add_argument(
        "--source-dir",
        default="data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Act_Enemies",
        help="Crawl directory that contains enemy pages.jsonl.",
    )
    build_enemy_pack_parser.add_argument(
        "--output-path",
        default="data/processed/wiki_gg/enemy_pack.json",
        help="Destination path for the simplified enemy pack JSON.",
    )

    build_reference_packs_parser = subparsers.add_parser(
        "build-reference-packs",
        help="Build card, keyword, buff, and debuff packs from the saved wiki.gg main crawl.",
    )
    build_reference_packs_parser.add_argument(
        "--source-dir",
        default="data/raw/wiki_gg/slaythespire.wiki.gg/Slay_the_Spire_2_Main",
        help="Crawl directory that contains the main wiki.gg reference pages.",
    )
    build_reference_packs_parser.add_argument(
        "--output-dir",
        default="data/processed/wiki_gg",
        help="Destination directory for the generated reference pack JSON files.",
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


def _event_printer(display_mode: str, show_tool_output: str, session_logger: Any | None = None):
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
            from .agent import ToolEvent

            event = payload
            if not isinstance(event, ToolEvent):
                return
            formatted = _format_tool_output(event.output, show_tool_output)
            if formatted:
                _print_header("Tool Output")
                print(formatted)

    return printer


def _build_session(model: str, max_rounds: int) -> SessionAgent:
    from openai import OpenAI

    from .agent import SessionAgent
    from .config import load_settings
    from .sts2_api import Sts2ApiClient

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
    from .logging_utils import SessionLogger

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
    from .logging_utils import SessionLogger

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

    if args.command == "crawl-games-gg-guides":
        report = crawl_games_gg_guides(
            game_slug=args.game_slug,
            output_dir=args.output_dir,
            limit=args.limit,
            skip_existing=args.skip_existing,
        )
        print(f"Discovered {report.discovered_count} guide URLs.")
        print(f"Saved {report.saved_count} guide records under {report.base_dir}.")
        print(f"Downloaded {report.downloaded_count} guides, skipped {report.skipped_existing_count}.")
        print(f"Manifest: {report.manifest_path}")
        print(f"JSONL: {report.jsonl_path}")
        return

    if args.command == "crawl-wiki-gg":
        report = crawl_wiki_gg(
            start_url=args.start_url,
            output_dir=args.output_dir,
            max_depth=args.max_depth,
            max_pages=args.max_pages,
            skip_existing=args.skip_existing,
            browser_binary=args.browser_binary,
            profile_dir=args.profile_dir,
            headless=args.headless,
        )
        print(f"Discovered {report.discovered_count} wiki URLs.")
        print(f"Saved {report.saved_count} wiki pages under {report.base_dir}.")
        print(f"Downloaded {report.downloaded_count} pages, skipped {report.skipped_existing_count}.")
        print(f"Manifest: {report.manifest_path}")
        print(f"JSONL: {report.jsonl_path}")
        return

    if args.command == "crawl-wiki-gg-act-enemies":
        report = crawl_wiki_gg_act_enemies(
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            act_names=args.acts,
            sections=args.sections,
            crawl_name=args.crawl_name,
            skip_existing=args.skip_existing,
            browser_binary=args.browser_binary,
            profile_dir=args.profile_dir,
            headless=args.headless,
        )
        print(f"Discovered {report.discovered_count} wiki URLs.")
        print(f"Saved {report.saved_count} wiki pages under {report.base_dir}.")
        print(f"Downloaded {report.downloaded_count} pages, skipped {report.skipped_existing_count}.")
        print(f"Manifest: {report.manifest_path}")
        print(f"JSONL: {report.jsonl_path}")
        return

    if args.command == "build-enemy-pack":
        report = build_enemy_pack(
            source_dir=args.source_dir,
            output_path=args.output_path,
        )
        print(f"Built {report.enemy_count} enemy records from {report.page_count} canonical pages.")
        print(f"Output: {report.output_path}")
        return

    if args.command == "build-reference-packs":
        report = build_reference_packs(
            source_dir=args.source_dir,
            output_dir=args.output_dir,
        )
        print(f"Built {report.card_count} cards.")
        print(f"Built {report.keyword_count} keywords.")
        print(f"Built {report.buff_count} buffs.")
        print(f"Built {report.debuff_count} debuffs.")
        print(f"Output directory: {report.output_dir}")
        return

    raise AssertionError(f"Unhandled command: {args.command}")
