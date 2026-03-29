from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

SOURCE_NAME = "wiki.gg"
DEFAULT_BROWSER_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_PROFILE_DIR = "/tmp/sts2llm-wikigg-profile"
BLOCKED_TITLES = {"请稍候…", "Just a second..."}
BLOCKED_NAMESPACES = {
    "Category",
    "File",
    "Help",
    "MediaWiki",
    "Module",
    "Special",
    "Template",
    "User",
}
BLOCKED_PAGE_NAMES = {
    "Editor_Portal",
}
DEFAULT_ACT_ENEMY_ACTS = ("Overgrowth", "Underdocks", "Hive", "Glory")
DEFAULT_ACT_ENEMY_SECTIONS = ("Monsters", "Elites", "Bosses")


@dataclass(slots=True)
class CrawlReport:
    base_dir: Path
    manifest_path: Path
    jsonl_path: Path
    discovered_count: int
    saved_count: int
    downloaded_count: int
    skipped_existing_count: int


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _page_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    if "/wiki/" not in parsed.path:
        return parsed.path.strip("/") or "index"
    return unquote(parsed.path.split("/wiki/", 1)[1])


def _normalize_wiki_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    path = unquote(parsed.path)
    return f"{scheme}://{parsed.netloc}{path}"


def _safe_name(value: str) -> str:
    value = value.strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return safe.strip("_") or "page"


def _safe_page_slug(url: str) -> str:
    return _safe_name(_page_name_from_url(url))


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _display_name_from_page_name(page_name: str) -> str:
    display_name = page_name.split(":", 1)[-1]
    return display_name.replace("_", " ").strip()


def _build_driver(*, browser_binary: str, profile_dir: str, headless: bool) -> webdriver.Chrome:
    options = Options()
    options.binary_location = browser_binary
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1600,2400")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")

    original_path = os.environ.get("PATH", "")
    filtered_parts = []
    for part in original_path.split(os.pathsep):
        if not part:
            continue
        if (Path(part) / "chromedriver").exists():
            continue
        filtered_parts.append(part)

    os.environ["PATH"] = os.pathsep.join(filtered_parts)
    try:
        driver = webdriver.Chrome(options=options)
    finally:
        os.environ["PATH"] = original_path

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
    )
    return driver


def _wait_for_wiki_content(driver: webdriver.Chrome, *, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    last_title = ""
    while time.time() < deadline:
        last_title = driver.title
        if driver.title in BLOCKED_TITLES:
            time.sleep(2)
            continue
        if "blocked" in driver.page_source[:3000].lower():
            time.sleep(2)
            continue
        if driver.find_elements(By.ID, "mw-content-text"):
            return
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for wiki content. Last title: {last_title}")


def _is_allowed_article_link(url: str, *, host: str) -> bool:
    url = _normalize_wiki_url(url)
    parsed = urlparse(url)
    if parsed.netloc != host:
        return False
    if not parsed.path.startswith("/wiki/"):
        return False
    if parsed.query:
        return False
    if parsed.fragment:
        return False

    page_name = _page_name_from_url(url)
    if not page_name or page_name in BLOCKED_PAGE_NAMES:
        return False

    if ":" in page_name:
        namespace = page_name.split(":", 1)[0]
        if namespace in BLOCKED_NAMESPACES:
            return False

    return True


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _build_record(
    *,
    url: str,
    page_html: str,
    html_relative_path: str,
    depth: int,
    discovered_from: str | None,
) -> dict[str, Any]:
    soup = BeautifulSoup(page_html, "html.parser")
    parsed_url = urlparse(url)
    host = parsed_url.netloc

    heading = soup.select_one("#firstHeading")
    content_root = soup.select_one("#mw-content-text > .mw-parser-output")
    if content_root is None:
        content_root = soup.select_one("#mw-content-text")
    if content_root is None:
        raise RuntimeError(f"Could not find #mw-content-text for {url}")

    for selector in [
        ".mw-editsection",
        ".noprint",
        ".mw-empty-elt",
        ".reference",
        ".toc",
        "script",
        "style",
    ]:
        for node in content_root.select(selector):
            node.decompose()

    categories = [
        link.get_text(" ", strip=True)
        for link in soup.select("#mw-normal-catlinks ul li a")
    ]

    internal_links = []
    for link in content_root.select("a[href]"):
        full_url = _normalize_wiki_url(urljoin(url, link["href"]))
        if _is_allowed_article_link(full_url, host=host):
            internal_links.append(full_url)
    internal_links = _unique_preserve_order(internal_links)
    internal_links = [link for link in internal_links if link != url]

    content_html = "".join(str(child) for child in content_root.contents)
    content_text = _normalize_text(content_root.get_text("\n", strip=True))
    page_name = _page_name_from_url(url)
    title = heading.get_text(" ", strip=True) if heading else page_name
    title = re.sub(r"\s+:\s+", ": ", title)

    return {
        "source": SOURCE_NAME,
        "wiki_host": host,
        "url": url,
        "page_name": page_name,
        "slug": _safe_page_slug(url),
        "fetched_at": _utc_now_iso(),
        "title": title,
        "depth": depth,
        "discovered_from": discovered_from,
        "categories": categories,
        "internal_links": internal_links,
        "internal_link_count": len(internal_links),
        "content_html": content_html,
        "content_text": content_text,
        "word_count": len(content_text.split()),
        "html_path": html_relative_path,
    }


def _serialize_target_context(target_context: dict[str, set[str]]) -> dict[str, list[str]]:
    return {
        "source_acts": sorted(target_context["source_acts"]),
        "source_sections": sorted(target_context["source_sections"]),
        "source_fragments": sorted(target_context["source_fragments"]),
        "source_page_urls": sorted(target_context["source_page_urls"]),
        "source_page_titles": sorted(target_context["source_page_titles"]),
    }


def _extract_target_links_from_sections(
    *,
    record: dict[str, Any],
    sections: list[str],
) -> dict[str, dict[str, set[str]]]:
    soup = BeautifulSoup(record["content_html"], "html.parser")
    wanted_sections = {_normalize_key(section): section for section in sections}
    section_nodes = [
        node for node in soup.find_all("h2") if _normalize_key(node.get_text(" ", strip=True)) in wanted_sections
    ]
    host = record["wiki_host"]
    act_name = _display_name_from_page_name(record["page_name"])
    targets: dict[str, dict[str, set[str]]] = {}

    all_h2_nodes = list(soup.find_all("h2"))
    for index, heading in enumerate(all_h2_nodes):
        heading_text = heading.get_text(" ", strip=True)
        normalized_heading = _normalize_key(heading_text)
        if normalized_heading not in wanted_sections:
            continue

        stop_node = all_h2_nodes[index + 1] if index + 1 < len(all_h2_nodes) else None
        node = heading.find_next_sibling()
        while node is not None and node is not stop_node:
            if getattr(node, "select", None):
                for link in node.select("a[href]"):
                    href = link.get("href")
                    if not href:
                        continue
                    full_url = _normalize_wiki_url(urljoin(record["url"], href))
                    target_url, fragment = urldefrag(full_url)
                    if not _is_allowed_article_link(target_url, host=host):
                        continue
                    context = targets.setdefault(
                        target_url,
                        {
                            "source_acts": set(),
                            "source_sections": set(),
                            "source_fragments": set(),
                            "source_page_urls": set(),
                            "source_page_titles": set(),
                        },
                    )
                    context["source_acts"].add(act_name)
                    context["source_sections"].add(wanted_sections[normalized_heading])
                    context["source_page_urls"].add(record["url"])
                    context["source_page_titles"].add(record["title"])
                    if fragment:
                        context["source_fragments"].add(fragment)
            node = node.find_next_sibling()

    return targets


def _load_act_source_records(*, source_dir: str | Path, act_names: list[str]) -> list[dict[str, Any]]:
    source_path = Path(source_dir)
    articles_dir = source_path / "articles"
    if not articles_dir.exists():
        raise FileNotFoundError(f"Source crawl directory does not contain articles/: {source_path}")

    wanted = {_normalize_key(act_name): act_name for act_name in act_names}
    selected_records: list[dict[str, Any]] = []

    for article_path in sorted(articles_dir.glob("*.json")):
        record = json.loads(article_path.read_text(encoding="utf-8"))
        page_name = record.get("page_name")
        if not isinstance(page_name, str) or not page_name:
            continue
        act_display_name = _display_name_from_page_name(page_name)
        if _normalize_key(act_display_name) not in wanted:
            continue
        selected_records.append(record)

    found = {_normalize_key(_display_name_from_page_name(record["page_name"])) for record in selected_records}
    missing = [wanted[key] for key in wanted if key not in found]
    if missing:
        raise ValueError(f"Could not find act pages in {articles_dir}: {', '.join(missing)}")

    return selected_records


def _crawl_explicit_urls(
    *,
    target_map: dict[str, dict[str, set[str]]],
    output_dir: str | Path,
    crawl_root_name: str,
    skip_existing: bool,
    browser_binary: str,
    profile_dir: str,
    headless: bool,
    manifest_extra: dict[str, Any] | None = None,
) -> CrawlReport:
    if not target_map:
        raise ValueError("No target URLs to crawl.")

    ordered_urls = sorted(target_map)
    host = urlparse(ordered_urls[0]).netloc
    output_root = Path(output_dir)
    base_dir = output_root / host / crawl_root_name
    html_dir = base_dir / "html"
    articles_dir = base_dir / "articles"
    for directory in (base_dir, html_dir, articles_dir):
        directory.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    downloaded_count = 0
    skipped_existing_count = 0
    total = len(ordered_urls)

    driver = _build_driver(
        browser_binary=browser_binary,
        profile_dir=profile_dir,
        headless=headless,
    )
    try:
        for index, url in enumerate(ordered_urls, start=1):
            slug = _safe_page_slug(url)
            article_path = articles_dir / f"{slug}.json"
            html_path = html_dir / f"{slug}.html"

            if skip_existing and article_path.exists() and html_path.exists():
                record = json.loads(article_path.read_text(encoding="utf-8"))
                skipped_existing_count += 1
                print(f"[{index}/{total}] skip {slug}")
            else:
                print(f"[{index}/{total}] fetch {slug}")
                driver.get(url)
                _wait_for_wiki_content(driver)
                canonical_url = _normalize_wiki_url(driver.current_url)
                page_html = driver.page_source
                html_path.write_text(page_html, encoding="utf-8")
                record = _build_record(
                    url=canonical_url,
                    page_html=page_html,
                    html_relative_path=html_path.relative_to(base_dir).as_posix(),
                    depth=0,
                    discovered_from=None,
                )
                downloaded_count += 1

            record["requested_url"] = url
            record["target_context"] = _serialize_target_context(target_map[url])
            _write_json(article_path, record)
            records.append(record)
    finally:
        driver.quit()

    jsonl_path = base_dir / "pages.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")

    manifest = {
        "source": SOURCE_NAME,
        "wiki_host": host,
        "crawl_type": "explicit_targets",
        "crawled_at": _utc_now_iso(),
        "saved_record_count": len(records),
        "downloaded_count": downloaded_count,
        "skipped_existing_count": skipped_existing_count,
        "discovered_url_count": len(ordered_urls),
        "targets": [
            {
                "url": url,
                **_serialize_target_context(target_map[url]),
            }
            for url in ordered_urls
        ],
        "articles": [
            {
                "slug": record["slug"],
                "url": record["url"],
                "requested_url": record["requested_url"],
                "article_path": f"articles/{record['slug']}.json",
                "html_path": record["html_path"],
            }
            for record in records
        ],
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    manifest_path = base_dir / "manifest.json"
    _write_json(manifest_path, manifest)

    return CrawlReport(
        base_dir=base_dir,
        manifest_path=manifest_path,
        jsonl_path=jsonl_path,
        discovered_count=len(ordered_urls),
        saved_count=len(records),
        downloaded_count=downloaded_count,
        skipped_existing_count=skipped_existing_count,
    )


def crawl_wiki_gg(
    *,
    start_url: str,
    output_dir: str | Path,
    max_depth: int = 1,
    max_pages: int = 20,
    skip_existing: bool = False,
    browser_binary: str = DEFAULT_BROWSER_BINARY,
    profile_dir: str = DEFAULT_PROFILE_DIR,
    headless: bool = False,
) -> CrawlReport:
    start_url = _normalize_wiki_url(start_url)
    host = urlparse(start_url).netloc
    crawl_root_name = _safe_page_slug(start_url)
    output_root = Path(output_dir)
    base_dir = output_root / host / crawl_root_name
    html_dir = base_dir / "html"
    articles_dir = base_dir / "articles"
    for directory in (base_dir, html_dir, articles_dir):
        directory.mkdir(parents=True, exist_ok=True)

    queue: deque[tuple[str, int, str | None]] = deque([(start_url, 0, None)])
    visited: set[str] = set()
    discovered: set[str] = {start_url}
    records: list[dict[str, Any]] = []
    downloaded_count = 0
    skipped_existing_count = 0

    driver = _build_driver(
        browser_binary=browser_binary,
        profile_dir=profile_dir,
        headless=headless,
    )
    try:
        while queue and len(records) < max_pages:
            url, depth, discovered_from = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            slug = _safe_page_slug(url)
            article_path = articles_dir / f"{slug}.json"
            html_path = html_dir / f"{slug}.html"

            if skip_existing and article_path.exists() and html_path.exists():
                record = json.loads(article_path.read_text(encoding="utf-8"))
                records.append(record)
                skipped_existing_count += 1
                print(f"[{len(records)}/{max_pages}] skip {slug}")
            else:
                print(f"[{len(records) + 1}/{max_pages}] fetch {slug}")
                driver.get(url)
                _wait_for_wiki_content(driver)
                canonical_url = _normalize_wiki_url(driver.current_url)
                page_html = driver.page_source
                html_path.write_text(page_html, encoding="utf-8")
                record = _build_record(
                    url=canonical_url,
                    page_html=page_html,
                    html_relative_path=html_path.relative_to(base_dir).as_posix(),
                    depth=depth,
                    discovered_from=discovered_from,
                )
                _write_json(article_path, record)
                records.append(record)
                downloaded_count += 1

            if depth >= max_depth:
                continue

            for child_url in record.get("internal_links", []):
                child_url = _normalize_wiki_url(child_url)
                if child_url in discovered:
                    continue
                discovered.add(child_url)
                queue.append((child_url, depth + 1, url))
    finally:
        driver.quit()

    jsonl_path = base_dir / "pages.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")

    manifest = {
        "source": SOURCE_NAME,
        "wiki_host": host,
        "start_url": start_url,
        "crawled_at": _utc_now_iso(),
        "max_depth": max_depth,
        "max_pages": max_pages,
        "saved_record_count": len(records),
        "downloaded_count": downloaded_count,
        "skipped_existing_count": skipped_existing_count,
        "discovered_url_count": len(discovered),
        "articles": [
            {
                "slug": record["slug"],
                "url": record["url"],
                "depth": record["depth"],
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
        discovered_count=len(discovered),
        saved_count=len(records),
        downloaded_count=downloaded_count,
        skipped_existing_count=skipped_existing_count,
    )


def crawl_wiki_gg_act_enemies(
    *,
    source_dir: str | Path,
    output_dir: str | Path,
    act_names: list[str] | None = None,
    sections: list[str] | None = None,
    crawl_name: str = "Slay_the_Spire_2_Act_Enemies",
    skip_existing: bool = False,
    browser_binary: str = DEFAULT_BROWSER_BINARY,
    profile_dir: str = DEFAULT_PROFILE_DIR,
    headless: bool = False,
) -> CrawlReport:
    selected_acts = act_names or list(DEFAULT_ACT_ENEMY_ACTS)
    selected_sections = sections or list(DEFAULT_ACT_ENEMY_SECTIONS)
    source_records = _load_act_source_records(source_dir=source_dir, act_names=selected_acts)

    target_map: dict[str, dict[str, set[str]]] = {}
    for record in source_records:
        extracted = _extract_target_links_from_sections(record=record, sections=selected_sections)
        for url, context in extracted.items():
            merged = target_map.setdefault(
                url,
                {
                    "source_acts": set(),
                    "source_sections": set(),
                    "source_fragments": set(),
                    "source_page_urls": set(),
                    "source_page_titles": set(),
                },
            )
            for key, values in context.items():
                merged[key].update(values)

    manifest_extra = {
        "crawl_type": "act_enemies",
        "source_dir": str(Path(source_dir)),
        "selected_acts": selected_acts,
        "selected_sections": selected_sections,
    }
    return _crawl_explicit_urls(
        target_map=target_map,
        output_dir=output_dir,
        crawl_root_name=crawl_name,
        skip_existing=skip_existing,
        browser_binary=browser_binary,
        profile_dir=profile_dir,
        headless=headless,
        manifest_extra=manifest_extra,
    )
