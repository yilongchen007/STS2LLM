from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_pack(path: Path, top_key: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: item for item in payload[top_key]}


class ReferenceIndex:
    def __init__(
        self,
        *,
        card_pack_path: str | Path | None = None,
        enemy_pack_path: str | Path | None = None,
        relic_pack_path: str | Path | None = None,
    ) -> None:
        root = _repo_root()
        self._card_pack_path = Path(card_pack_path or root / "data/processed/wiki_gg/card_pack.json")
        self._enemy_pack_path = Path(enemy_pack_path or root / "data/processed/wiki_gg/enemy_pack.json")
        self._relic_pack_path = Path(relic_pack_path or root / "data/processed/wiki_gg/relic_pack.json")

        self._cards_by_id: dict[str, dict[str, Any]] | None = None
        self._enemies_by_id: dict[str, dict[str, Any]] | None = None
        self._relics_by_id: dict[str, dict[str, Any]] | None = None

    def get_card(self, card_id: str) -> dict[str, Any]:
        normalized_id = self._normalize_program_id(card_id)
        record = self._cards().get(normalized_id)
        if record is None:
            raise KeyError(f"Unknown card id: {card_id}")
        return dict(record)

    def get_enemy(self, *, entity_id: str | None = None, monster_id: str | None = None) -> dict[str, Any]:
        if not entity_id and not monster_id:
            raise ValueError("Provide either entity_id or monster_id.")

        source_entity_id = entity_id
        normalized_monster_id = self._normalize_enemy_lookup_id(entity_id or monster_id or "")
        record = self._enemies().get(normalized_monster_id)
        if record is None:
            raise KeyError(f"Unknown enemy id: {entity_id or monster_id}")

        result = dict(record)
        result["monster_id"] = normalized_monster_id
        if source_entity_id is not None:
            result["entity_id"] = source_entity_id
        return result

    def get_relic(self, relic_id: str) -> dict[str, Any]:
        normalized_id = self._normalize_program_id(relic_id)
        record = self._relics().get(normalized_id)
        if record is None:
            raise KeyError(f"Unknown relic id: {relic_id}")
        return dict(record)

    def _cards(self) -> dict[str, dict[str, Any]]:
        if self._cards_by_id is None:
            self._cards_by_id = _load_pack(self._card_pack_path, "cards")
        return self._cards_by_id

    def _enemies(self) -> dict[str, dict[str, Any]]:
        if self._enemies_by_id is None:
            self._enemies_by_id = _load_pack(self._enemy_pack_path, "enemies")
        return self._enemies_by_id

    def _relics(self) -> dict[str, dict[str, Any]]:
        if self._relics_by_id is None:
            self._relics_by_id = _load_pack(self._relic_pack_path, "relics")
        return self._relics_by_id

    @staticmethod
    def _normalize_program_id(value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("Id cannot be empty.")
        return normalized

    @classmethod
    def _normalize_enemy_lookup_id(cls, value: str) -> str:
        normalized = cls._normalize_program_id(value)
        return re.sub(r"_[0-9]+$", "", normalized)
