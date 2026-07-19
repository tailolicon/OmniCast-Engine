"""YouTube Policy Fetcher — weekly diff + human-gated rule update.

Sources:
  1. YouTube Creator Blog RSS (feedparser, no-block, XML)
  2. YouTube policy pages via Playwright headless (SPA, needs real browser)

Flow:
  fetch() → extract main_text → hash → diff vs last snapshot
         → changed? → Sonnet analysis → insert pending_approval rules
         → Telegram alert with /approve_rule <id> / /reject_rule <id>

NEVER overwrites active rules. Human must approve via Telegram before rules go live.
"""

from __future__ import annotations

import hashlib
import json
import re
import structlog
from datetime import datetime, UTC
from pathlib import Path

logger = structlog.get_logger()

# ── Sources ──────────────────────────────────────────────────────────────────

POLICY_SOURCES = [
    {
        "type": "rss",
        "url": "https://blog.youtube/rss/",
        "name": "YouTube Creator Blog",
        "keywords": ["policy", "monetization", "ai content", "terms", "guidelines",
                     "creator", "spam", "enforcement", "advertiser"],
    },
    {
        "type": "playwright",
        "url": "https://support.google.com/youtube/answer/2801973",
        "name": "YouTube Monetization Policy",
    },
    {
        "type": "playwright",
        "url": "https://support.google.com/youtube/answer/6162278",
        "name": "YouTube AdSense Policies",
    },
    {
        "type": "playwright",
        "url": "https://support.google.com/youtube/answer/1311392",
        "name": "YouTube Community Guidelines",
    },
    {
        "type": "playwright",
        "url": "https://support.google.com/youtube/answer/14328491",
        "name": "YouTube AI/Synthetic Content Disclosure Policy",
    },
    {
        "type": "playwright",
        "url": "https://support.google.com/youtube/answer/2801950",
        "name": "YouTube Spam & Deceptive Practices Policy",
    },
]

# ── Consecutive-failure tracking ──────────────────────────────────────────────
# Maps source URL → consecutive failure count. Reset on success.
_fail_counts: dict[str, int] = {}
_FAIL_ALERT_THRESHOLD = 3  # alert after 3 consecutive failures


async def _try_telegram_alert(message: str) -> None:
    """Fire-and-forget Telegram alert. Reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
    from environment. Silently swallows errors so policy check never blocks on alert."""
    import os
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            )
    except Exception as exc:
        logger.warning("Telegram alert send failed", error=str(exc))


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_main_text_html(html: str) -> str:
    """Extract main content text from HTML, strip nav/header/footer/scripts."""
    try:
        from readability import Document
        doc = Document(html)
        content_html = doc.summary()
        # Strip remaining tags
        text = re.sub(r"<[^>]+>", " ", content_html)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception:
        pass
    # Fallback: BeautifulSoup
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        return re.sub(r"\s+", " ", soup.get_text()).strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)[:5000]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Fetch: RSS ────────────────────────────────────────────────────────────────

def _fetch_rss(source: dict) -> list[dict]:
    """Fetch RSS feed, filter policy-related entries."""
    import feedparser
    feed = feedparser.parse(source["url"])
    keywords = [k.lower() for k in source.get("keywords", [])]
    results = []
    for entry in feed.entries[:20]:
        title = getattr(entry, "title", "").lower()
        summary = getattr(entry, "summary", "").lower()
        combined = title + " " + summary
        if any(kw in combined for kw in keywords):
            results.append({
                "title": getattr(entry, "title", ""),
                "url": getattr(entry, "link", source["url"]),
                "text": f"{entry.get('title', '')}. {entry.get('summary', '')}",
                "published": getattr(entry, "published", ""),
            })
    logger.info("RSS fetch complete", source=source["name"], policy_items=len(results))
    return results


# ── Fetch: Playwright (SPA) ───────────────────────────────────────────────────

async def _fetch_playwright(url: str, name: str) -> str | None:
    """Fetch SPA page via headless Chromium. Returns main_text or None.

    Tracks consecutive failures per URL and fires a Telegram alert when a source
    has failed _FAIL_ALERT_THRESHOLD times in a row.
    """
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2000)  # let JS render
            html = await page.content()
            await browser.close()
        text = _extract_main_text_html(html)
        logger.info("Playwright fetch complete", url=url, chars=len(text))
        # Reset failure counter on success
        _fail_counts.pop(url, None)
        return text
    except Exception as exc:
        _fail_counts[url] = _fail_counts.get(url, 0) + 1
        count = _fail_counts[url]
        logger.warning("Playwright fetch failed", url=url, error=str(exc),
                       consecutive_failures=count)
        if count >= _FAIL_ALERT_THRESHOLD:
            await _try_telegram_alert(
                f"⚠️ <b>OmniCast Policy Watcher</b>\n"
                f"Source <b>{name}</b> has failed {count} consecutive times.\n"
                f"URL: {url}\n"
                f"Last error: {str(exc)[:200]}\n"
                f"Policy rules may be stale — check network/Playwright."
            )
        return None


# ── Diff analysis via LLM ─────────────────────────────────────────────────────

async def _analyze_diff(old_text: str, new_text: str, source_name: str, llm) -> list[dict]:
    """Sonnet analyzes policy diff → returns list of rule change dicts."""
    # Only send a window of changed context, not full pages (cost control)
    old_words = set(old_text.split())
    new_words = set(new_text.split())
    added = " ".join(list(new_words - old_words)[:200])
    removed = " ".join(list(old_words - new_words)[:200])

    prompt = (
        f"Source: {source_name}\n\n"
        f"NEW WORDS (added to policy):\n{added}\n\n"
        f"REMOVED WORDS (deleted from policy):\n{removed}\n\n"
        "Analyze this YouTube policy change. Extract specific, actionable compliance rules "
        "that affect YouTube content creators. Focus on: content restrictions, AI disclosure "
        "requirements, monetization eligibility, duplicate content, spam.\n\n"
        "Return ONLY valid JSON array:\n"
        '[{"rule_text": "Creators must...", "diff_context": "specific changed phrase"}]\n'
        "Return [] if no meaningful policy change detected (ignore cosmetic changes)."
    )
    try:
        response = await llm.complete(
            system=(
                "You are a YouTube policy analyst. Extract precise, enforceable rules "
                "from policy diffs. Be conservative — only flag real policy changes, "
                "not formatting or minor wording."
            ),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
        )
        text = response.content.strip()
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as exc:
        logger.warning("Policy diff analysis failed", error=str(exc))
    return []


# ── Main runner ───────────────────────────────────────────────────────────────

async def run_policy_check(llm, db_path: Path | None = None) -> int:
    """Full policy check cycle. Returns count of new pending rules inserted.

    Args:
        llm: LLMClient instance (should use Sonnet for accuracy)
        db_path: optional path to vault.db

    Flow:
        For each source → fetch → extract text → hash → diff vs last snapshot
        → if changed → Sonnet analyze → insert pending_approval rules
    """
    from omnicast.vault.db import (
        get_last_snapshot, save_snapshot,
        insert_pending_rules, init_db,
    )

    init_db(db_path)
    now = datetime.now(UTC).isoformat()
    total_new_rules = 0

    for source in POLICY_SOURCES:
        try:
            if source["type"] == "rss":
                items = _fetch_rss(source)
                if not items:
                    continue
                # Combine all policy item texts as the "page"
                combined_text = "\n\n".join(
                    f"{it['title']}: {it['text']}" for it in items
                )
                url = source["url"]
                new_hash = _hash(combined_text)
                last = get_last_snapshot(url, db_path)

                if last and last["content_hash"] == new_hash:
                    logger.info("No change", source=source["name"])
                    continue

                save_snapshot(url, new_hash, combined_text, now, db_path)
                old_text = last["main_text"] if last else ""
                rules = await _analyze_diff(old_text, combined_text, source["name"], llm)

            elif source["type"] == "playwright":
                url = source["url"]
                new_text = await _fetch_playwright(url, source["name"])
                if not new_text:
                    continue
                new_hash = _hash(new_text)
                last = get_last_snapshot(url, db_path)

                if last and last["content_hash"] == new_hash:
                    logger.info("No change", source=source["name"])
                    continue

                save_snapshot(url, new_hash, new_text, now, db_path)
                old_text = last["main_text"] if last else ""
                rules = await _analyze_diff(old_text, new_text, source["name"], llm)
            else:
                continue

            if not rules:
                logger.info("No policy changes detected", source=source["name"])
                continue

            # Attach metadata before inserting
            for r in rules:
                r["source_url"] = source.get("url", "")
                r["created_at"] = now

            ids = insert_pending_rules(rules, db_path)
            total_new_rules += len(ids)
            logger.info(
                "Policy rules pending approval",
                source=source["name"],
                count=len(ids),
                rule_ids=ids,
            )

        except Exception as exc:
            logger.error("Policy check failed for source", source=source.get("name"), error=str(exc))
            continue

    return total_new_rules
