from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

SOURCE_NAME = "games.gg"
ROOT_SITEMAP_URL = "https://games.gg/sitemap.xml"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
NEXT_DATA_PATTERN = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)


@dataclass(slots=True)
class CrawlReport:
    base_dir: Path
    manifest_path: Path
    jsonl_path: Path
    discovered_count: int
    saved_count: int
    downloaded_count: int
    skipped_existing_count: int


class _HTMLTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "blockquote",
        "br",
        "div",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "ol",
        "p",
        "section",
        "table",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_tag_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_tag_depth += 1
            return
        if self._ignored_tag_depth:
            return
        if tag == "li":
            self._parts.append("\n- ")
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_tag_depth:
            self._ignored_tag_depth -= 1
            return
        if self._ignored_tag_depth:
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_tag_depth:
            return
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def _fetch_text(client: httpx.Client, url: str, *, retries: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            return response.text
        except (httpx.HTTPError, httpx.NetworkError) as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(0.5 * attempt)
    raise RuntimeError(f"Failed to fetch {url}") from last_error


def _extract_guide_sitemap_urls(sitemap_index_xml: str) -> list[str]:
    urls = re.findall(r"<loc>(https://games\.gg/guides/sitemap-\d+\.xml)</loc>", sitemap_index_xml)
    return sorted(set(urls))


def _extract_guide_urls(sitemap_xml: str, game_slug: str) -> list[str]:
    pattern = re.compile(rf"<loc>(https://games\.gg/{re.escape(game_slug)}/guides/[^<]+)</loc>")
    return sorted(set(pattern.findall(sitemap_xml)))


def _extract_next_data(page_html: str) -> dict[str, Any]:
    match = NEXT_DATA_PATTERN.search(page_html)
    if not match:
        raise RuntimeError("Could not locate __NEXT_DATA__ in guide page.")
    return json.loads(match.group(1))


def _slug_from_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def _build_record(
    *,
    game_slug: str,
    url: str,
    guide: dict[str, Any],
    seo: dict[str, Any],
    html_relative_path: str,
) -> dict[str, Any]:
    content_html = guide.get("content") or ""
    content_text = _html_to_text(content_html)
    return {
        "source": SOURCE_NAME,
        "game_slug": game_slug,
        "url": url,
        "slug": guide.get("slug") or _slug_from_url(url),
        "fetched_at": _utc_now_iso(),
        "title": guide.get("title"),
        "short_description": guide.get("shortDescription"),
        "reading_time_minutes": guide.get("readingTime"),
        "complexity": guide.get("complexity"),
        "guide_type": guide.get("type"),
        "document_id": guide.get("documentId"),
        "locale": guide.get("locale"),
        "author": guide.get("author"),
        "image": guide.get("image"),
        "category": guide.get("category"),
        "published_at": guide.get("publishedAt"),
        "updated_at": guide.get("updatedAt"),
        "game": guide.get("game"),
        "localizations": guide.get("localizations"),
        "seo": seo,
        "content_html": content_html,
        "content_text": content_text,
        "word_count": len(content_text.split()),
        "html_path": html_relative_path,
    }


def crawl_games_gg_guides(
    *,
    game_slug: str,
    output_dir: str | Path,
    limit: int | None = None,
    skip_existing: bool = False,
) -> CrawlReport:
    output_root = Path(output_dir)
    base_dir = output_root / game_slug
    sitemaps_dir = base_dir / "sitemaps"
    html_dir = base_dir / "html"
    articles_dir = base_dir / "articles"
    for directory in (base_dir, sitemaps_dir, html_dir, articles_dir):
        directory.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    with httpx.Client(headers=headers, follow_redirects=True, timeout=30.0) as client:
        sitemap_index_xml = _fetch_text(client, ROOT_SITEMAP_URL)
        (sitemaps_dir / "sitemap-index.xml").write_text(sitemap_index_xml, encoding="utf-8")

        sitemap_urls = _extract_guide_sitemap_urls(sitemap_index_xml)
        discovered_urls: list[str] = []
        for sitemap_url in sitemap_urls:
            sitemap_xml = _fetch_text(client, sitemap_url)
            sitemap_name = urlparse(sitemap_url).path.rstrip("/").split("/")[-1]
            (sitemaps_dir / sitemap_name).write_text(sitemap_xml, encoding="utf-8")
            discovered_urls.extend(_extract_guide_urls(sitemap_xml, game_slug))

        unique_urls = sorted(set(discovered_urls))
        if limit is not None:
            unique_urls = unique_urls[:limit]

        records: list[dict[str, Any]] = []
        downloaded_count = 0
        skipped_existing_count = 0

        for index, url in enumerate(unique_urls, start=1):
            slug = _slug_from_url(url)
            article_path = articles_dir / f"{slug}.json"
            html_path = html_dir / f"{slug}.html"
            if skip_existing and article_path.exists() and html_path.exists():
                records.append(json.loads(article_path.read_text(encoding="utf-8")))
                skipped_existing_count += 1
                print(f"[{index}/{len(unique_urls)}] skip {slug}")
                continue

            print(f"[{index}/{len(unique_urls)}] fetch {slug}")
            page_html = _fetch_text(client, url)
            html_path.write_text(page_html, encoding="utf-8")

            next_data = _extract_next_data(page_html)
            page_props = next_data.get("props", {}).get("pageProps", {})
            guide = page_props.get("guide")
            if not isinstance(guide, dict):
                raise RuntimeError(f"Guide payload missing for {url}")
            seo = page_props.get("seo", {})
            record = _build_record(
                game_slug=game_slug,
                url=url,
                guide=guide,
                seo=seo if isinstance(seo, dict) else {},
                html_relative_path=html_path.relative_to(base_dir).as_posix(),
            )
            _write_json(article_path, record)
            records.append(record)
            downloaded_count += 1

    jsonl_path = base_dir / "guides.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")

    manifest = {
        "source": SOURCE_NAME,
        "game_slug": game_slug,
        "crawled_at": _utc_now_iso(),
        "root_sitemap_url": ROOT_SITEMAP_URL,
        "guide_sitemap_count": len(sitemap_urls),
        "discovered_url_count": len(sorted(set(discovered_urls))),
        "saved_record_count": len(records),
        "downloaded_count": downloaded_count,
        "skipped_existing_count": skipped_existing_count,
        "article_urls": unique_urls,
        "articles": [
            {
                "slug": record["slug"],
                "url": record["url"],
                "article_path": f"articles/{record['slug']}.json",
                "html_path": record["html_path"],
            }
            for record in records
        ],
    }
    manifest_path = base_dir / "manifest.json"
    _write_json(manifest_path, manifest)

    return CrawlReport(
        base_dir=base_dir,
        manifest_path=manifest_path,
        jsonl_path=jsonl_path,
        discovered_count=len(sorted(set(discovered_urls))),
        saved_count=len(records),
        downloaded_count=downloaded_count,
        skipped_existing_count=skipped_existing_count,
    )
