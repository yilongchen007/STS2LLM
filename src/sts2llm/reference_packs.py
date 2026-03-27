from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


@dataclass(slots=True)
class ReferencePacksReport:
    output_dir: Path
    card_count: int
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


def _card_content(card_box: Any) -> str:
    base_node = card_box.select_one(".desc-base")
    upgrade_node = card_box.select_one(".desc-upg")
    base_text = _normalize_text(base_node.get_text(" ", strip=True) if base_node else "")
    upgrade_text = _normalize_text(upgrade_node.get_text(" ", strip=True) if upgrade_node else "")

    if upgrade_text and upgrade_text != base_text:
        return _normalize_text(f"Base: {base_text}\nUpgrade: {upgrade_text}")
    return base_text or upgrade_text


def build_card_pack(*, source_dir: str | Path, output_path: str | Path) -> int:
    html_path = Path(source_dir) / "html" / "Slay_the_Spire_2_Cards_List.html"
    root = _root_from_html(html_path)

    cards = []
    for card_box in root.select(".card-box"):
        title_node = card_box.select_one(".card-title")
        if title_node is None:
            continue
        name = title_node.get_text(" ", strip=True)
        content = _card_content(card_box)
        if not content:
            continue
        cards.append(
            {
                "id": _make_id(name),
                "name": name,
                "color": (card_box.get("data-color") or "").strip(),
                "type": (card_box.get("data-type") or "").strip(),
                "rarity": (card_box.get("data-rarity") or "").strip(),
                "content": content,
            }
        )

    _write_json(Path(output_path), {"cards": cards})
    return len(cards)


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
) -> ReferencePacksReport:
    destination = Path(output_dir)
    card_count = build_card_pack(
        source_dir=source_dir,
        output_path=destination / "card_pack.json",
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
        keyword_count=keyword_count,
        buff_count=buff_count,
        debuff_count=debuff_count,
    )
