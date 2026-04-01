from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

GENERIC_SECTION_NAMES = {
    "encounters",
    "in party with",
    "notes",
    "pattern",
    "strategy",
    "trivia",
    "useful cards",
}


@dataclass(slots=True)
class EnemyPackReport:
    output_path: Path
    page_count: int
    enemy_count: int


def _load_enemy_annotations(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}

    source = Path(path)
    if not source.exists():
        return {}

    payload = json.loads(source.read_text(encoding="utf-8"))
    rows = payload.get("enemies")
    if not isinstance(rows, dict):
        raise ValueError(f"Enemy annotations file must contain an 'enemies' object: {source}")

    result: dict[str, dict[str, Any]] = {}
    for enemy_id, fields in rows.items():
        if not isinstance(fields, dict):
            raise ValueError(f"Enemy annotation for {enemy_id!r} must be an object")
        result[enemy_id] = dict(fields)
    return result


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_runtime_display_name(name: str) -> str:
    value = re.sub(r"#C\{[^}]+\}", "", name)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _make_enemy_id(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", name.casefold())
    return value.strip("_")


def _display_name_from_title(title: str) -> str:
    if ":" in title:
        return title.split(":", 1)[1].strip()
    return title.strip()


def _is_generic_section(title: str) -> bool:
    normalized = title.casefold().strip()
    if normalized in GENERIC_SECTION_NAMES:
        return True
    return bool(re.fullmatch(r"phase\s+\d+", normalized))


def _nodes_to_text(nodes: list[Any]) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            text = node.strip()
        else:
            text = node.get_text("\n", strip=True)
        if text:
            parts.append(text)
    return _normalize_text("\n\n".join(parts))


def _collect_h2_sections(soup: BeautifulSoup) -> tuple[list[Any], list[dict[str, Any]]]:
    lead_nodes: list[Any] = []
    sections: list[dict[str, Any]] = []

    current_heading = None
    current_nodes: list[Any] = []
    for node in soup.contents:
        node_name = getattr(node, "name", None)
        if node_name == "h2":
            if current_heading is None:
                if current_nodes:
                    lead_nodes = list(current_nodes)
            else:
                sections.append(
                    {
                        "heading": current_heading,
                        "nodes": list(current_nodes),
                    }
                )
            current_heading = node
            current_nodes = [node]
            continue
        current_nodes.append(node)

    if current_heading is None:
        lead_nodes = list(current_nodes)
    else:
        sections.append(
            {
                "heading": current_heading,
                "nodes": list(current_nodes),
            }
        )

    parsed_sections: list[dict[str, Any]] = []
    for section in sections:
        heading = section["heading"]
        heading_text = heading.get_text(" ", strip=True)
        anchor = heading.find("span", id=True)
        parsed_sections.append(
            {
                "heading_text": heading_text,
                "heading_id": anchor["id"] if anchor else None,
                "nodes": section["nodes"],
                "text": _nodes_to_text(section["nodes"]),
            }
        )

    return lead_nodes, parsed_sections


def _merge_source_context(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for record in records:
        context = record.get("target_context") or {}
        acts = context.get("source_acts") or []
        sections = context.get("source_sections") or []
        for act in acts:
            for section in sections:
                if act and section:
                    pairs.add((act, section))
    return [
        {"act": act, "encounter_type": encounter_type}
        for act, encounter_type in sorted(pairs)
    ]


def _load_runtime_enemy_ids(monsters_json_path: str | Path) -> dict[str, str]:
    payload = json.loads(Path(monsters_json_path).read_text(encoding="utf-8"))
    normalized_name_to_ids: dict[str, list[str]] = defaultdict(list)
    for key, value in payload.items():
        if key.endswith(".name"):
            normalized_name = _normalize_runtime_display_name(value)
            normalized_name_to_ids[normalized_name].append(key[:-5])

    result: dict[str, str] = {}
    for normalized_name, ids in normalized_name_to_ids.items():
        if len(ids) != 1:
            raise ValueError(
                f"Runtime monster name {normalized_name!r} is not unique: {ids}"
            )
        result[normalized_name] = ids[0]
    return result


def _resolve_runtime_enemy_id(
    *,
    name: str,
    runtime_enemy_ids: dict[str, str],
) -> str:
    runtime_id = runtime_enemy_ids.get(_normalize_runtime_display_name(name))
    if runtime_id is not None:
        return runtime_id
    raise ValueError(f"Could not find unique runtime id for wiki enemy {name!r}")


def _pick_representative_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    def score(record: dict[str, Any]) -> tuple[int, int]:
        requested_url = record.get("requested_url")
        canonical = int(requested_url == record.get("url"))
        page_name = record.get("page_name", "")
        exact_title = int(_make_enemy_id(_display_name_from_title(record.get("title", ""))) == _make_enemy_id(page_name.split(":", 1)[-1].replace("_", " ")))
        return (canonical, exact_title)

    return max(records, key=score)


def _build_entries_for_record(record: dict[str, Any], contexts: list[dict[str, str]]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(record["content_html"], "html.parser")
    main_name = _display_name_from_title(record["title"])
    main_name_key = _make_enemy_id(main_name)
    lead_nodes, sections = _collect_h2_sections(soup)
    lead_text = _nodes_to_text(lead_nodes)
    lead_has_stats = "HP" in lead_text

    candidate_sections = [section for section in sections if not _is_generic_section(section["heading_text"])]
    candidate_keys = {_make_enemy_id(section["heading_text"]) for section in candidate_sections}

    entries: list[dict[str, Any]] = []
    if not candidate_sections:
        content = _normalize_text(record["content_text"])
        if not content:
            return []
        return [
            {
                "id": main_name_key,
                "name": main_name,
                "contexts": contexts,
                "content": content,
            }
        ]

    if main_name_key in candidate_keys:
        for section in candidate_sections:
            section_content = section["text"]
            if _make_enemy_id(section["heading_text"]) == main_name_key and lead_text:
                section_content = _normalize_text(f"{lead_text}\n\n{section_content}")
            entries.append(
                {
                    "id": _make_enemy_id(section["heading_text"]),
                    "name": section["heading_text"],
                    "contexts": contexts,
                    "content": section_content,
                }
            )
        return entries

    if lead_has_stats:
        entries.append(
            {
                "id": main_name_key,
                "name": main_name,
                "contexts": contexts,
                "content": lead_text,
            }
        )

    for section in candidate_sections:
        entries.append(
            {
                "id": _make_enemy_id(section["heading_text"]),
                "name": section["heading_text"],
                "contexts": contexts,
                "content": section["text"],
            }
        )
    return entries


def build_enemy_pack(
    *,
    source_dir: str | Path,
    output_path: str | Path,
    runtime_monsters_path: str | Path = "data/raw/game_pck/localization/eng/monsters.json",
    enemy_annotations_path: str | Path | None = "data/manual/enemy_annotations.json",
) -> EnemyPackReport:
    source_path = Path(source_dir)
    jsonl_path = source_path / "pages.jsonl"
    if not jsonl_path.exists():
        raise FileNotFoundError(f"Could not find pages.jsonl under {source_path}")
    runtime_enemy_ids = _load_runtime_enemy_ids(runtime_monsters_path)
    enemy_annotations = _load_enemy_annotations(enemy_annotations_path)

    raw_records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    grouped_records: dict[str, list[dict[str, Any]]] = {}
    for record in raw_records:
        grouped_records.setdefault(record["url"], []).append(record)

    enemies_by_id: dict[str, dict[str, Any]] = {}
    for records in grouped_records.values():
        representative = _pick_representative_record(records)
        contexts = _merge_source_context(records)
        entries = _build_entries_for_record(representative, contexts)
        for entry in entries:
            entry["id"] = _resolve_runtime_enemy_id(
                name=entry["name"],
                runtime_enemy_ids=runtime_enemy_ids,
            )
            existing = enemies_by_id.get(entry["id"])
            if existing is None:
                enemies_by_id[entry["id"]] = entry
                continue

            existing_contexts = {
                (item["act"], item["encounter_type"])
                for item in existing["contexts"]
            }
            for item in entry["contexts"]:
                key = (item["act"], item["encounter_type"])
                if key not in existing_contexts:
                    existing["contexts"].append(item)
                    existing_contexts.add(key)
            existing["contexts"].sort(key=lambda item: (item["act"], item["encounter_type"]))

            if len(entry["content"]) > len(existing["content"]):
                existing["content"] = entry["content"]

    for enemy_id, entry in enemies_by_id.items():
        annotations = enemy_annotations.get(enemy_id)
        if annotations:
            entry.update(annotations)

    payload = {
        "enemies": sorted(enemies_by_id.values(), key=lambda item: item["id"]),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return EnemyPackReport(
        output_path=destination,
        page_count=len(grouped_records),
        enemy_count=len(payload["enemies"]),
    )
