#!/usr/bin/env python3
"""Minimal Godot .pck inspector/extractor for local STS2 research."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


PCK_HEADER_MAGIC = 0x43504447
PACK_DIR_ENCRYPTED = 1 << 0
PCK_FILE_RELATIVE_BASE = 1 << 1
PCK_FILE_SPARSE_BUNDLE = 1 << 2


@dataclass(frozen=True)
class PckEntry:
    path: str
    offset: int
    size: int
    md5: str
    flags: int


class GodotPck:
    def __init__(self, path: Path):
        self.path = path
        self.format_version = 0
        self.godot_version = "0.0.0"
        self.flags = 0
        self.file_offset_base = 0
        self.directory_offset = 0
        self.entries: list[PckEntry] = []

    def load(self) -> "GodotPck":
        with self.path.open("rb") as fh:
            magic = self._read_u32(fh)
            if magic != PCK_HEADER_MAGIC:
                raise ValueError(f"invalid magic: 0x{magic:08x}")

            self.format_version = self._read_u32(fh)
            major = self._read_u32(fh)
            minor = self._read_u32(fh)
            patch = self._read_u32(fh)
            self.godot_version = f"{major}.{minor}.{patch}"

            if self.format_version >= 2:
                self.flags = self._read_u32(fh)
                self.file_offset_base = self._read_u64(fh)
            else:
                self.flags = 0
                self.file_offset_base = 0

            if self.flags & PACK_DIR_ENCRYPTED:
                raise ValueError("encrypted pck directories are not supported")

            if self.format_version >= 3 or (
                self.format_version == 2 and self.flags & PCK_FILE_RELATIVE_BASE
            ):
                self.file_offset_base += 0

            if self.format_version >= 3:
                self.directory_offset = self._read_u64(fh)
                fh.seek(self.directory_offset)
            else:
                fh.seek(fh.tell() + 16 * 4)

            file_count = self._read_u32(fh)
            self.entries = []
            for _ in range(file_count):
                path_length = self._read_u32(fh)
                raw_path = fh.read(path_length)
                if len(raw_path) != path_length:
                    raise EOFError("unexpected EOF while reading pck path")
                path = raw_path.rstrip(b"\0").decode("utf-8", errors="replace")
                offset = self.file_offset_base + self._read_u64(fh)
                size = self._read_u64(fh)
                md5 = fh.read(16)
                if len(md5) != 16:
                    raise EOFError("unexpected EOF while reading pck md5")
                flags = self._read_u32(fh) if self.format_version >= 2 else 0
                self.entries.append(
                    PckEntry(
                        path=path,
                        offset=offset,
                        size=size,
                        md5=md5.hex(),
                        flags=flags,
                    )
                )
        return self

    def read_bytes(self, entry: PckEntry) -> bytes:
        with self.path.open("rb") as fh:
            fh.seek(entry.offset)
            data = fh.read(entry.size)
        if len(data) != entry.size:
            raise EOFError(f"short read for {entry.path}")
        return data

    @staticmethod
    def _read_u32(fh) -> int:
        data = fh.read(4)
        if len(data) != 4:
            raise EOFError("unexpected EOF while reading u32")
        return struct.unpack("<I", data)[0]

    @staticmethod
    def _read_u64(fh) -> int:
        data = fh.read(8)
        if len(data) != 8:
            raise EOFError("unexpected EOF while reading u64")
        return struct.unpack("<Q", data)[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or extract a Godot .pck file.")
    parser.add_argument("pck", type=Path, help="Path to the .pck file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List entries")
    add_filter_args(list_parser)
    list_parser.add_argument("--limit", type=int, default=0, help="Max matching entries to print")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")

    extract_parser = subparsers.add_parser("extract", help="Extract matching entries")
    add_filter_args(extract_parser)
    extract_parser.add_argument("output", type=Path, help="Output directory")
    extract_parser.add_argument(
        "--strip-prefix",
        default="",
        help="Remove this leading prefix from extracted relative paths",
    )
    extract_parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing files if present"
    )
    extract_parser.add_argument("--dry-run", action="store_true", help="Show what would be extracted")

    return parser


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prefix",
        action="append",
        default=[],
        help="Only include entries whose path starts with this prefix",
    )
    parser.add_argument(
        "--regex",
        action="append",
        default=[],
        help="Only include entries whose path matches this regex",
    )


def iter_filtered(entries: Iterable[PckEntry], prefixes: list[str], regexes: list[str]) -> Iterator[PckEntry]:
    compiled = [re.compile(pattern) for pattern in regexes]
    for entry in entries:
        if prefixes and not any(entry.path.startswith(prefix) for prefix in prefixes):
            continue
        if compiled and not any(pattern.search(entry.path) for pattern in compiled):
            continue
        yield entry


def safe_output_path(output_dir: Path, entry_path: str, strip_prefix: str) -> Path:
    relative = entry_path
    if strip_prefix:
        if not relative.startswith(strip_prefix):
            raise ValueError(f"{entry_path!r} does not start with strip prefix {strip_prefix!r}")
        relative = relative[len(strip_prefix) :]
    relative = relative.lstrip("/")
    target = (output_dir / relative).resolve()
    output_root = output_dir.resolve()
    if not str(target).startswith(str(output_root) + "/") and target != output_root:
        raise ValueError(f"unsafe output path for {entry_path!r}")
    return target


def cmd_list(pck: GodotPck, args: argparse.Namespace) -> int:
    matches = list(iter_filtered(pck.entries, args.prefix, args.regex))
    if args.limit > 0:
        matches = matches[: args.limit]

    if args.json:
        payload = {
            "pck": str(pck.path),
            "format_version": pck.format_version,
            "godot_version": pck.godot_version,
            "flags": pck.flags,
            "directory_offset": pck.directory_offset,
            "file_offset_base": pck.file_offset_base,
            "match_count": len(matches),
            "entries": [entry.__dict__ for entry in matches],
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print(
        f"pck={pck.path} format={pck.format_version} godot={pck.godot_version} "
        f"flags={pck.flags} total_entries={len(pck.entries)} matched={len(matches)}"
    )
    for entry in matches:
        print(f"{entry.size:>10}  {entry.path}")
    return 0


def cmd_extract(pck: GodotPck, args: argparse.Namespace) -> int:
    matches = list(iter_filtered(pck.entries, args.prefix, args.regex))
    if not matches:
        print("no matching entries", file=sys.stderr)
        return 1

    extracted = 0
    for entry in matches:
        target = safe_output_path(args.output, entry.path, args.strip_prefix)
        if target.exists() and not args.overwrite:
            print(f"skip exists: {target}")
            continue
        print(f"{'would extract' if args.dry_run else 'extract'}: {entry.path} -> {target}")
        if args.dry_run:
            extracted += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pck.read_bytes(entry))
        extracted += 1

    print(f"done: extracted={extracted} matched={len(matches)} output={args.output}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    pck = GodotPck(args.pck).load()
    if args.command == "list":
        return cmd_list(pck, args)
    if args.command == "extract":
        return cmd_extract(pck, args)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
