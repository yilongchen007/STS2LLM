from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


@dataclass(slots=True)
class ReferencePacksReport:
    output_dir: Path
    card_count: int
    relic_count: int
    keyword_count: int
    buff_count: int
    debuff_count: int


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _make_id(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", name.casefold())
    return value.strip("_")


def _strip_leading_name(text: str, name: str) -> str:
    pattern = re.compile(rf"^{re.escape(name)}\s*[:.\-]?\s*", flags=re.IGNORECASE)
    value = pattern.sub("", text, count=1).strip()
    if value and value[0].islower():
        value = value[0].upper() + value[1:]
    return value


def _root_from_html(path: Path) -> BeautifulSoup:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    root = soup.select_one("#mw-content-text > .mw-parser-output") or soup.select_one("#mw-content-text")
    if root is None:
        raise ValueError(f"Could not find wiki content root in {path}")
    return root


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_CARD_INTERNAL_NAME_RUNTIME_ID_OVERRIDES = {
    "IAmInvincible": "I_AM_INVINCIBLE",
    "ExpectAFight": "EXPECT_A_FIGHT",
    "BansheeCry": "BANSHEES_CRY",
}


def _camel_to_runtime_id(value: str) -> str:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized)
    return normalized.upper().strip("_")


def _parse_percent(value: str) -> float:
    return float(value.strip())


def _load_card_win_rate_rows(path: str | Path) -> dict[str, dict[str, Any]]:
    rows_by_card_id: dict[str, dict[str, Any]] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            internal_name = (row.get("InternalName") or "").strip()
            if not internal_name:
                continue
            runtime_id = _CARD_INTERNAL_NAME_RUNTIME_ID_OVERRIDES.get(internal_name) or _camel_to_runtime_id(internal_name)
            if runtime_id in rows_by_card_id:
                raise ValueError(f"Duplicate winning-rate row for card id {runtime_id}")
            rows_by_card_id[runtime_id] = {
                "internal_name": internal_name,
                "name_zh": (row.get("卡牌名称") or "").strip(),
                "win_rate": _parse_percent(row["胜率"]),
                "pick_rate": _parse_percent(row["选取率"]),
                "skip_rate": _parse_percent(row["略过率"]),
            }
    return rows_by_card_id


def _load_card_stat_overrides(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}

    source = Path(path)
    if not source.exists():
        return {}

    rows_by_card_id: dict[str, dict[str, Any]] = {}
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            runtime_id = (row.get("runtime_id") or "").strip().upper()
            if not runtime_id:
                continue
            if runtime_id in rows_by_card_id:
                raise ValueError(f"Duplicate card stat override row for card id {runtime_id}")

            item: dict[str, Any] = {}
            if row.get("name_zh"):
                item["name_zh"] = row["name_zh"].strip()
            if row.get("win_rate"):
                item["win_rate"] = _parse_percent(row["win_rate"])
            if row.get("pick_rate"):
                item["pick_rate"] = _parse_percent(row["pick_rate"])
            if row.get("skip_rate"):
                item["skip_rate"] = _parse_percent(row["skip_rate"])
            rows_by_card_id[runtime_id] = item
    return rows_by_card_id


def _load_card_annotations(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}

    source = Path(path)
    if not source.exists():
        return {}

    payload = json.loads(source.read_text(encoding="utf-8"))
    rows = payload.get("cards")
    if not isinstance(rows, dict):
        raise ValueError(f"Card annotations file must contain a 'cards' object: {source}")

    result: dict[str, dict[str, Any]] = {}
    for card_id, fields in rows.items():
        if not isinstance(fields, dict):
            raise ValueError(f"Card annotation for {card_id!r} must be an object")
        result[card_id] = dict(fields)
    return result


def _load_runtime_card_ids(cards_json_path: str | Path) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    payload = json.loads(Path(cards_json_path).read_text(encoding="utf-8"))
    title_to_ids: dict[str, list[str]] = defaultdict(list)
    for key, value in payload.items():
        if key.endswith(".title"):
            title_to_ids[value].append(key[:-6])

    unique_by_name: dict[str, str] = {}
    for title, ids in title_to_ids.items():
        if len(ids) == 1:
            unique_by_name[title] = ids[0]

    by_name_and_color = {
        ("Defend (Ironclad)", "Ironclad"): "DEFEND_IRONCLAD",
        ("Strike (Ironclad)", "Ironclad"): "STRIKE_IRONCLAD",
        ("Defend (Silent)", "Silent"): "DEFEND_SILENT",
        ("Strike (Silent)", "Silent"): "STRIKE_SILENT",
        ("Defend (Regent)", "Regent"): "DEFEND_REGENT",
        ("Strike (Regent)", "Regent"): "STRIKE_REGENT",
        ("Defend (Necrobinder)", "Necrobinder"): "DEFEND_NECROBINDER",
        ("Strike (Necrobinder)", "Necrobinder"): "STRIKE_NECROBINDER",
        ("Defend (Defect)", "Defect"): "DEFEND_DEFECT",
        ("Strike (Defect)", "Defect"): "STRIKE_DEFECT",
    }
    return unique_by_name, by_name_and_color


def _resolve_runtime_card_id(
    *,
    name: str,
    color: str,
    runtime_card_ids: dict[str, str],
    runtime_card_ids_by_name_and_color: dict[tuple[str, str], str],
) -> str:
    runtime_id = runtime_card_ids.get(name)
    if runtime_id is not None:
        return runtime_id

    runtime_id = runtime_card_ids_by_name_and_color.get((name, color))
    if runtime_id is not None:
        return runtime_id

    raise ValueError(f"Could not find unique runtime id for wiki card {name!r} ({color!r})")


def _load_runtime_relic_ids(relics_json_path: str | Path) -> dict[str, str]:
    payload = json.loads(Path(relics_json_path).read_text(encoding="utf-8"))
    title_to_ids: dict[str, list[str]] = defaultdict(list)
    for key, value in payload.items():
        if key.endswith(".title"):
            title_to_ids[value].append(key[:-6])

    result: dict[str, str] = {}
    for title, ids in title_to_ids.items():
        if len(ids) != 1:
            raise ValueError(f"Runtime relic title {title!r} is not unique: {ids}")
        result[title] = ids[0]
    return result


def _card_content(card_box: Any) -> str:
    base_node = card_box.select_one(".desc-base")
    upgrade_node = card_box.select_one(".desc-upg")
    base_text = _normalize_text(base_node.get_text(" ", strip=True) if base_node else "")
    upgrade_text = _normalize_text(upgrade_node.get_text(" ", strip=True) if upgrade_node else "")

    if upgrade_text and upgrade_text != base_text:
        return _normalize_text(f"Base: {base_text}\nUpgrade: {upgrade_text}")
    return base_text or upgrade_text


def build_card_pack(
    *,
    source_dir: str | Path,
    output_path: str | Path,
    runtime_cards_path: str | Path,
    winning_rate_csv_path: str | Path | None = "data/raw/winning_rate.csv",
    card_stat_overrides_path: str | Path | None = "data/raw/xhh/ironclad_latest.csv",
    card_annotations_path: str | Path | None = "data/manual/card_annotations.json",
) -> int:
    html_path = Path(source_dir) / "html" / "Slay_the_Spire_2_Cards_List.html"
    root = _root_from_html(html_path)
    runtime_card_ids, runtime_card_ids_by_name_and_color = _load_runtime_card_ids(runtime_cards_path)
    card_win_rates = _load_card_win_rate_rows(winning_rate_csv_path) if winning_rate_csv_path is not None else {}
    card_stat_overrides = _load_card_stat_overrides(card_stat_overrides_path)
    card_annotations = _load_card_annotations(card_annotations_path)

    cards = []
    for card_box in root.select(".card-box"):
        title_node = card_box.select_one(".card-title")
        if title_node is None:
            continue
        name = title_node.get_text(" ", strip=True)
        color = (card_box.get("data-color") or "").strip()
        content = _card_content(card_box)
        if not content:
            continue
        runtime_id = _resolve_runtime_card_id(
            name=name,
            color=color,
            runtime_card_ids=runtime_card_ids,
            runtime_card_ids_by_name_and_color=runtime_card_ids_by_name_and_color,
        )
        card = {
            "id": runtime_id,
            "name": name,
            "color": color,
            "type": (card_box.get("data-type") or "").strip(),
            "rarity": (card_box.get("data-rarity") or "").strip(),
            "content": content,
        }
        stats = card_win_rates.get(runtime_id)
        if stats is not None:
            card.update(stats)
        stat_overrides = card_stat_overrides.get(runtime_id)
        if stat_overrides is not None:
            card.update(stat_overrides)
        annotations = card_annotations.get(runtime_id)
        if annotations is not None:
            card.update(annotations)
        cards.append(card)

    card_ids_in_pack = {card["id"] for card in cards}
    unmatched_stat_ids = set(card_win_rates) - card_ids_in_pack - {"DEPRECATED_CARD"}
    if unmatched_stat_ids:
        raise ValueError(f"Winning-rate rows could not be matched to card pack ids: {sorted(unmatched_stat_ids)}")
    unmatched_override_ids = set(card_stat_overrides) - card_ids_in_pack
    if unmatched_override_ids:
        raise ValueError(f"Card stat overrides could not be matched to card pack ids: {sorted(unmatched_override_ids)}")
    unmatched_annotation_ids = set(card_annotations) - card_ids_in_pack
    if unmatched_annotation_ids:
        raise ValueError(f"Card annotations could not be matched to card pack ids: {sorted(unmatched_annotation_ids)}")

    _write_json(Path(output_path), {"cards": cards})
    return len(cards)


def build_relic_pack(
    *,
    source_dir: str | Path,
    output_path: str | Path,
    runtime_relics_path: str | Path,
) -> int:
    html_path = Path(source_dir) / "html" / "Slay_the_Spire_2_Relics_List.html"
    root = _root_from_html(html_path)
    runtime_relic_ids = _load_runtime_relic_ids(runtime_relics_path)

    relics = []
    for relic_box in root.select(".relic-box"):
        title_node = relic_box.select_one(".relic-title")
        if title_node is None:
            continue
        name = title_node.get_text(" ", strip=True)
        runtime_id = runtime_relic_ids.get(name)
        if runtime_id is None:
            raise ValueError(f"Could not find unique runtime id for wiki relic {name!r}")

        desc_node = relic_box.select_one(".relic-desc .relic-desc") or relic_box.select_one(".relic-desc")
        flavor_node = relic_box.select_one(".relic-flavor")
        requirements_node = relic_box.select_one(".relic-requirements")

        description = _normalize_text(desc_node.get_text(" ", strip=True) if desc_node else "")
        flavor = _normalize_text(flavor_node.get_text(" ", strip=True) if flavor_node else "")
        requirements = _normalize_text(requirements_node.get_text(" ", strip=True) if requirements_node else "")

        parts = [part for part in [description, f"Flavor: {flavor}" if flavor else "", f"Requirements: {requirements}" if requirements else ""] if part]
        content = _normalize_text("\n".join(parts))
        if not content:
            continue

        relics.append(
            {
                "id": runtime_id,
                "name": name,
                "rarity": (relic_box.get("data-rarity") or "").strip(),
                "character": (relic_box.get("data-character") or "").strip(),
                "content": content,
            }
        )

    _write_json(Path(output_path), {"relics": relics})
    return len(relics)


def build_keyword_pack(*, source_dir: str | Path, output_path: str | Path) -> int:
    html_path = Path(source_dir) / "html" / "Slay_the_Spire_2_Keywords.html"
    root = _root_from_html(html_path)

    keywords = []
    for heading in root.find_all("h3"):
        name = heading.get_text(" ", strip=True)
        parts = []
        node = heading.find_next_sibling()
        while node is not None and getattr(node, "name", None) not in {"h2", "h3"}:
            if getattr(node, "get_text", None):
                text = node.get_text(" ", strip=True)
                if text:
                    parts.append(text)
            node = node.find_next_sibling()
        content = _normalize_text("\n\n".join(parts))
        if not name or not content:
            continue
        content = _strip_leading_name(content, name)
        keywords.append(
            {
                "id": _make_id(name),
                "name": name,
                "content": content,
            }
        )

    _write_json(Path(output_path), {"keywords": keywords})
    return len(keywords)


def _status_content(cells: list[Any], *, kind: str) -> str:
    if kind == "buff":
        description = _normalize_text(cells[3].get_text(" ", strip=True))
        notes = _normalize_text(cells[4].get_text(" ", strip=True))
    else:
        description = _normalize_text(cells[4].get_text(" ", strip=True))
        notes = _normalize_text(cells[5].get_text(" ", strip=True))

    if description and notes:
        return _normalize_text(f"{description}\nNotes: {notes}")
    return description or notes


def _build_status_pack(*, source_dir: str | Path, output_path: str | Path, page_slug: str, top_key: str, kind: str) -> int:
    html_path = Path(source_dir) / "html" / f"{page_slug}.html"
    root = _root_from_html(html_path)
    rows = root.select("table tr[id]")

    items = []
    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue
        name = cells[1].get_text(" ", strip=True)
        content = _status_content(cells, kind=kind)
        if not name or not content:
            continue
        items.append(
            {
                "id": _make_id(name),
                "name": name,
                "content": content,
            }
        )

    _write_json(Path(output_path), {top_key: items})
    return len(items)


def build_buff_pack(*, source_dir: str | Path, output_path: str | Path) -> int:
    return _build_status_pack(
        source_dir=source_dir,
        output_path=output_path,
        page_slug="Slay_the_Spire_2_Buffs",
        top_key="buffs",
        kind="buff",
    )


def build_debuff_pack(*, source_dir: str | Path, output_path: str | Path) -> int:
    return _build_status_pack(
        source_dir=source_dir,
        output_path=output_path,
        page_slug="Slay_the_Spire_2_Debuffs",
        top_key="debuffs",
        kind="debuff",
    )


def build_reference_packs(
    *,
    source_dir: str | Path,
    output_dir: str | Path,
    runtime_cards_path: str | Path = "data/raw/game_pck/localization/eng/cards.json",
    runtime_relics_path: str | Path = "data/raw/game_pck/localization/eng/relics.json",
    winning_rate_csv_path: str | Path | None = "data/raw/winning_rate.csv",
    card_stat_overrides_path: str | Path | None = "data/raw/xhh/ironclad_latest.csv",
    card_annotations_path: str | Path | None = "data/manual/card_annotations.json",
) -> ReferencePacksReport:
    destination = Path(output_dir)
    card_count = build_card_pack(
        source_dir=source_dir,
        output_path=destination / "card_pack.json",
        runtime_cards_path=runtime_cards_path,
        winning_rate_csv_path=winning_rate_csv_path,
        card_stat_overrides_path=card_stat_overrides_path,
        card_annotations_path=card_annotations_path,
    )
    relic_count = build_relic_pack(
        source_dir=source_dir,
        output_path=destination / "relic_pack.json",
        runtime_relics_path=runtime_relics_path,
    )
    keyword_count = build_keyword_pack(
        source_dir=source_dir,
        output_path=destination / "keyword_pack.json",
    )
    buff_count = build_buff_pack(
        source_dir=source_dir,
        output_path=destination / "buffs_pack.json",
    )
    debuff_count = build_debuff_pack(
        source_dir=source_dir,
        output_path=destination / "debuffs_pack.json",
    )

    return ReferencePacksReport(
        output_dir=destination,
        card_count=card_count,
        relic_count=relic_count,
        keyword_count=keyword_count,
        buff_count=buff_count,
        debuff_count=debuff_count,
    )
