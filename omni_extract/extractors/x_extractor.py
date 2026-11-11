from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from typing import Any

from ..models import OmniExtractResult

USER_AGENT = "OmniExtract-MCP/1.0 (+https://github.com/solarfans/omni-extract-mcp)"


def _render_x_article_blocks(article_obj: dict[str, Any]) -> str:
    """
    Render an X (Twitter) long-form Article object (from FxTwitter GraphQL) into clean Markdown.
    Handles header-one, header-two, header-three, unordered-list-item, ordered-list-item,
    blockquote, code-block, and atomic media blocks.
    """
    content = article_obj.get("content") or {}
    blocks = content.get("blocks") or []
    if not blocks:
        plain = article_obj.get("preview_text") or article_obj.get("text") or ""
        return str(plain).strip()

    lines: list[str] = []
    ordered_idx = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "unstyled")
        text = str(block.get("text") or "").rstrip()
        if btype != "ordered-list-item":
            ordered_idx = 0

        if not text and btype == "atomic":
            continue

        if btype == "header-one":
            lines.append(f"\n# {text}\n")
        elif btype == "header-two":
            lines.append(f"\n## {text}\n")
        elif btype == "header-three":
            lines.append(f"\n### {text}\n")
        elif btype == "unordered-list-item":
            lines.append(f"- {text}")
        elif btype == "ordered-list-item":
            ordered_idx += 1
            lines.append(f"{ordered_idx}. {text}")
        elif btype == "blockquote":
            lines.append(f"> {text}")
        elif btype == "code-block":
            lines.append(f"```\n{text}\n```")
        else:
            if text:
                lines.append(text)
                lines.append("")

    rendered = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", rendered)


def _fetch_fxtwitter(tweet_id: str, timeout: float = 15.0) -> dict[str, Any] | None:
    """Tier 1: Cookie-free FxTwitter public GraphQL API (supports NoteTweets & full X Articles)."""
    url = f"https://api.fxtwitter.com/status/{tweet_id}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            tweet = payload.get("tweet")
            if isinstance(tweet, dict):
                return tweet
    except Exception:
        pass
    return None


def _fetch_vxtwitter(tweet_id: str, timeout: float = 15.0) -> dict[str, Any] | None:
    """Tier 2: Cookie-free VxTwitter public API fallback."""
    url = f"https://api.vxtwitter.com/Twitter/status/{tweet_id}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict) and (payload.get("text") or payload.get("article")):
                return payload
    except Exception:
        pass
    return None


def _compute_syndication_token(tweet_id: str) -> str:
    val = (int(tweet_id) / 1e15) * math.pi
    # Base-36 style token approximation accepted by syndication endpoint
    return re.sub(r"(0+|\.)", "", f"{val:.14f}")[:10] or "a"


def _fetch_syndication(tweet_id: str, timeout: float = 15.0) -> dict[str, Any] | None:
    """Tier 3: Official Twitter CDN Syndication JSON endpoint (cookie-free)."""
    token = _compute_syndication_token(tweet_id)
    url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=en&token={token}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict) and payload.get("text"):
                return payload
    except Exception:
        pass
    return None


def extract_x_content(url: str, tweet_id: str | None = None) -> OmniExtractResult:
    """
    Extract X (Twitter) tweet, long-form X Article, or media post without any personal cookies.
    Cascade: FxTwitter GraphQL -> VxTwitter API -> Twitter CDN Syndication.
    """
    if not tweet_id:
        m = re.search(r"/(?:status|article)/(\d+)", url)
        if not m:
            raise ValueError(f"Could not parse X status/article ID from URL: {url}")
        tweet_id = m.group(1)

    canonical_url = f"https://x.com/i/status/{tweet_id}"

    # 1. Try FxTwitter (best support for full X Articles + NoteTweets)
    fx = _fetch_fxtwitter(tweet_id)
    if fx:
        author_obj = fx.get("author") or {}
        screen_name = str(author_obj.get("screen_name") or "x_user")
        author_name = str(author_obj.get("name") or screen_name)
        author_display = f"{author_name} (@{screen_name})"

        article_obj = fx.get("article")
        is_x_article = isinstance(article_obj, dict) and bool(article_obj)

        if is_x_article:
            title = str(article_obj.get("title") or f"X Article by @{screen_name}").strip()
            body_text = _render_x_article_blocks(article_obj)
            cover_media = ((article_obj.get("cover_media") or {}).get("media_info") or {})
            cover_url = cover_media.get("original_img_url")
        else:
            raw_text = str(fx.get("text") or fx.get("raw_text", {}).get("text") or "").strip()
            first_line = raw_text.splitlines()[0][:70].strip() if raw_text else f"Post by @{screen_name}"
            title = first_line
            body_text = raw_text
            cover_url = None

        # Append quoted tweet context if present
        quote = fx.get("quote")
        if isinstance(quote, dict) and quote.get("text"):
            q_author = (quote.get("author") or {}).get("screen_name") or "user"
            q_text = str(quote.get("text") or "").strip()
            body_text = f"{body_text}\n\n> **Quoted @{q_author}**:\n> {q_text}"

        # Extract media URLs (photos & watermark-free MP4 videos)
        media_urls: list[str] = []
        duration_sec = 0.0
        media_container = fx.get("media") or {}
        for item in media_container.get("all") or []:
            if not isinstance(item, dict):
                continue
            m_url = item.get("url")
            if m_url:
                media_urls.append(str(m_url))
            if item.get("type") in {"video", "gif"}:
                duration_sec = max(duration_sec, float(item.get("duration") or 0.0))
                if not cover_url and item.get("thumbnail_url"):
                    cover_url = str(item.get("thumbnail_url"))

        if not cover_url and media_urls:
            cover_url = media_urls[0]

        metrics = {
            "likes": fx.get("likes", 0),
            "retweets": fx.get("retweets", 0),
            "replies": fx.get("replies", 0),
            "views": fx.get("views", 0),
            "bookmarks": fx.get("bookmarks", 0),
            "created_at": fx.get("created_at"),
            "is_x_article": is_x_article,
        }

        md_lines = [
            f"# {title}",
            "",
            f"- **Author**: {author_display}",
            f"- **Source**: {canonical_url}",
            f"- **Published**: {fx.get('created_at') or 'Unknown'}",
            f"- **Engagement**: {metrics['likes']} Likes · {metrics['retweets']} Reposts · {metrics['views']} Views",
            "",
            "---",
            "",
            body_text,
        ]
        if media_urls:
            md_lines.extend(["", "## Media Attachments"] + [f"- {u}" for u in media_urls])

        return OmniExtractResult(
            url=url,
            canonical_url=canonical_url,
            platform="x",
            content_type="video" if duration_sec > 0 else "article",
            content_id=tweet_id,
            title=title,
            author=author_display,
            text=body_text,
            markdown="\n".join(md_lines),
            media_urls=media_urls,
            cover_url=cover_url,
            duration_seconds=duration_sec,
            extraction_tier="fxtwitter_graphql_cookie_free",
            credits_charged=1,
            metadata=metrics,
        )

    # 2. Try VxTwitter fallback
    vx = _fetch_vxtwitter(tweet_id)
    if vx:
        screen_name = str(vx.get("user_screen_name") or "x_user")
        author_name = str(vx.get("user_name") or screen_name)
        author_display = f"{author_name} (@{screen_name})"
        body_text = str(vx.get("text") or "").strip()
        title = body_text.splitlines()[0][:70].strip() if body_text else f"Post by @{screen_name}"
        media_urls = [str(u) for u in (vx.get("mediaURLs") or []) if u]
        md = f"# {title}\n\n- **Author**: {author_display}\n- **Source**: {canonical_url}\n\n---\n\n{body_text}"
        return OmniExtractResult(
            url=url,
            canonical_url=canonical_url,
            platform="x",
            content_type="article",
            content_id=tweet_id,
            title=title,
            author=author_display,
            text=body_text,
            markdown=md,
            media_urls=media_urls,
            cover_url=media_urls[0] if media_urls else None,
            extraction_tier="vxtwitter_api_cookie_free",
            credits_charged=1,
            metadata={
                "likes": vx.get("likes", 0),
                "retweets": vx.get("retweets", 0),
                "replies": vx.get("replies", 0),
                "created_at": vx.get("date"),
            },
        )

    # 3. Try Twitter Syndication CDN
    syn = _fetch_syndication(tweet_id)
    if syn:
        user_obj = syn.get("user") or {}
        screen_name = str(user_obj.get("screen_name") or "x_user")
        author_name = str(user_obj.get("name") or screen_name)
        author_display = f"{author_name} (@{screen_name})"
        body_text = str(syn.get("text") or "").strip()
        title = body_text.splitlines()[0][:70].strip() if body_text else f"Post by @{screen_name}"
        md = f"# {title}\n\n- **Author**: {author_display}\n- **Source**: {canonical_url}\n\n---\n\n{body_text}"
        return OmniExtractResult(
            url=url,
            canonical_url=canonical_url,
            platform="x",
            content_type="article",
            content_id=tweet_id,
            title=title,
            author=author_display,
            text=body_text,
            markdown=md,
            extraction_tier="twimg_syndication_cookie_free",
            credits_charged=1,
            metadata={"likes": syn.get("favorite_count", 0), "created_at": syn.get("created_at")},
        )

    raise RuntimeError(f"Unable to extract X post {tweet_id} via cookie-free tiers.")
