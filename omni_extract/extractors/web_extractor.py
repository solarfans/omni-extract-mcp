from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

from ..models import OmniExtractResult, PlatformType
from .douyin_extractor import clean_short_title

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BOT_WALL_PATTERNS = (
    "just a moment...",
    "attention required! | cloudflare",
    "verify you are human",
    "enable javascript and cookies to continue",
    "access denied",
    "403 forbidden",
    "环境异常",
    "完成验证后即可继续访问",
    "安全验证",
)


class _SemanticMarkdownHTMLParser(HTMLParser):
    """Converts clean article HTML into structured Markdown without external dependencies."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.in_title = False
        self.in_pre = False
        self.title_parts: list[str] = []
        self.md_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg", "nav", "footer", "aside", "iframe"}:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if t == "title":
            self.in_title = True
        elif t == "h1":
            self.md_parts.append("\n\n# ")
        elif t == "h2":
            self.md_parts.append("\n\n## ")
        elif t == "h3":
            self.md_parts.append("\n\n### ")
        elif t in {"h4", "h5", "h6"}:
            self.md_parts.append("\n\n#### ")
        elif t in {"p", "div", "section", "article", "tr"}:
            self.md_parts.append("\n\n")
        elif t == "br":
            self.md_parts.append("\n")
        elif t == "li":
            self.md_parts.append("\n- ")
        elif t == "blockquote":
            self.md_parts.append("\n\n> ")
        elif t == "pre":
            self.in_pre = True
            self.md_parts.append("\n\n```\n")
        elif t == "code" and not self.in_pre:
            self.md_parts.append("`")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg", "nav", "footer", "aside", "iframe"}:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if t == "title":
            self.in_title = False
        elif t == "pre":
            self.in_pre = False
            self.md_parts.append("\n```\n\n")
        elif t == "code" and not self.in_pre:
            self.md_parts.append("`")
        elif t in {"h1", "h2", "h3", "h4", "p"}:
            self.md_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        if self._skip_depth > 0:
            return
        if self.in_pre:
            self.md_parts.append(data)
        else:
            s = re.sub(r"[ \t\r\f]+", " ", data).strip()
            if s:
                self.md_parts.append(s + " ")


def is_valid_article_body(text: str, min_chars: int = 120) -> bool:
    if not text:
        return False
    cleaned = text.strip()
    if len(cleaned) < min_chars:
        return False
    lower = cleaned[:1500].lower()
    for pat in BOT_WALL_PATTERNS:
        if pat in lower and len(cleaned) < 900:
            return False
    return True


def _try_xiaohongshu_extract(url: str, timeout: float = 12.0) -> tuple[str, str, str, str, list[str]] | None:
    """Cookie-free Xiaohongshu (RedNote) SSR meta & initial state extractor."""
    parsed = urllib.parse.urlsplit(url)
    if "xiaohongshu.com" not in parsed.netloc.lower() and "xhslink.com" not in parsed.netloc.lower():
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html_str = resp.read(2_000_000).decode("utf-8", errors="replace")

        og_title = re.search(r'<meta\s+name="og:title"\s+content="([^"]+)"', html_str)
        og_desc = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html_str)
        og_imgs = re.findall(r'<meta\s+name="og:image"\s+content="([^"]+)"', html_str)

        title = (og_title.group(1).replace(" - 小红书", "").strip() if og_title else "") or "Xiaohongshu Note"
        desc = (og_desc.group(1).strip() if og_desc else "")
        if len(desc) >= 20 or og_imgs:
            body = desc or title
            if og_imgs:
                body += "\n\n## Note Images\n" + "\n".join(f"- {u}" for u in og_imgs[:12])
            return clean_short_title(title, author="Xiaohongshu"), "xiaohongshu.com", body, "xhs_ssr_meta", og_imgs[:12]
    except Exception:
        pass
    return None


def _try_github_extract(url: str, timeout: float = 12.0) -> tuple[str, str, str, str] | None:
    """Specialized fast extractor for GitHub repositories and blob files."""
    parsed = urllib.parse.urlsplit(url)
    if "github.com" not in parsed.netloc.lower():
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]

    # Case 1: Specific file blob URL -> fetch raw file
    if len(parts) >= 5 and parts[2] == "blob":
        branch = parts[3]
        file_path = "/".join(parts[4:])
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
        try:
            req = urllib.request.Request(raw_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read(1_000_000).decode("utf-8", errors="replace")
                return f"{owner}/{repo}:{file_path}", owner, content, "github_raw_blob"
        except Exception:
            pass

    # Case 2: Repository root -> fetch README via GitHub REST API or raw main/master
    for branch in ("main", "master"):
        for readme_name in ("README.md", "readme.md", "README.rst"):
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{readme_name}"
            try:
                req = urllib.request.Request(raw_url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        content = resp.read(1_000_000).decode("utf-8", errors="replace")
                        if len(content.strip()) > 60:
                            return f"{owner}/{repo}", owner, content, "github_raw_readme"
            except Exception:
                continue
    return None


def _try_direct_http_markdown(url: str, timeout: float = 12.0) -> tuple[str, str, str, str] | None:
    """Tier 1: Fast direct HTTP fetch with semantic HTML-to-Markdown conversion."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain,text/markdown;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            content_type = (resp.headers.get("Content-Type") or "").lower()
            raw_bytes = resp.read(2_000_000)
            charset = resp.headers.get_content_charset() or "utf-8"
            text_str = raw_bytes.decode(charset, errors="replace")

        if "application/json" in content_type or "text/plain" in content_type or "text/markdown" in content_type:
            if is_valid_article_body(text_str, min_chars=60):
                return clean_short_title(url, author=host), host, text_str.strip(), "direct_raw"

        parser = _SemanticMarkdownHTMLParser()
        parser.feed(text_str)
        title_raw = "".join(parser.title_parts).strip()
        body = re.sub(r"\n{3,}", "\n\n", "".join(parser.md_parts)).strip()
        if is_valid_article_body(body, min_chars=180):
            title = clean_short_title(title_raw or body.splitlines()[0], author=host)
            return title, host, body, "direct_semantic_html"
    except Exception:
        pass
    return None


def _try_jina_reader_fallback(url: str, timeout: float = 20.0) -> tuple[str, str, str, str] | None:
    """Tier 2: Jina Reader clean Markdown gateway (keyless public tier)."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain",
        "X-Return-Format": "markdown",
    }
    jina_key = os.environ.get("JINA_API_KEY", "").strip()
    if jina_key:
        headers["Authorization"] = f"Bearer {jina_key}"
    try:
        req = urllib.request.Request(jina_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            md = resp.read(2_000_000).decode("utf-8", errors="replace").strip()
        if is_valid_article_body(md, min_chars=150):
            title = clean_short_title(md.splitlines()[0].lstrip("# "), author=host)
            return title, host, md, "jina_reader_markdown"
    except Exception:
        pass
    return None


def _try_byok_firecrawl(url: str, timeout: float = 25.0) -> tuple[str, str, str, str] | None:
    """Tier 3 (Optional BYOK): Uses FIRECRAWL_API_KEY only if explicitly provided in environment."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not api_key:
        return None
    host = urllib.parse.urlsplit(url).netloc.lower()
    try:
        payload = json.dumps({"url": url, "formats": ["markdown"], "onlyMainContent": True}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.firecrawl.dev/v2/scrape",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read(3_000_000))
        if obj.get("success") is True:
            data = obj.get("data") or {}
            md = str(data.get("markdown") or "").strip()
            meta = data.get("metadata") or {}
            title_raw = str(meta.get("title") or meta.get("ogTitle") or "").strip()
            if is_valid_article_body(md, min_chars=120):
                return clean_short_title(title_raw or md.splitlines()[0], author=host), host, md, "byok_firecrawl"
    except Exception:
        pass
    return None


def extract_web_markdown(
    url: str,
    platform: PlatformType = "web",
    title_hint: str | None = None,
) -> OmniExtractResult:
    """
    Stateless anti-bot web article extractor.
    Cascade: GitHub Fast-Path -> Direct Semantic HTML -> Jina Reader Markdown -> Optional BYOK Firecrawl.
    """
    content_id = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]

    xhs_res = _try_xiaohongshu_extract(url)
    if xhs_res:
        extracted_title, author, md_body, tier_used, xhs_imgs = xhs_res
        title = clean_short_title(title_hint or extracted_title, author=author)
        full_md = f"# {title}\n\n- **Source**: {url}\n- **Platform**: Xiaohongshu (RedNote)\n- **Extractor**: `{tier_used}`\n\n---\n\n{md_body}"
        return OmniExtractResult(
            url=url,
            canonical_url=url,
            platform="xiaohongshu",
            content_type="gallery" if xhs_imgs else "article",
            content_id=content_id,
            title=title,
            author=author,
            text=md_body,
            markdown=full_md,
            media_urls=xhs_imgs,
            cover_url=xhs_imgs[0] if xhs_imgs else None,
            extraction_tier=tier_used,
            credits_charged=1,
            metadata={"char_count": len(md_body), "image_count": len(xhs_imgs)},
        )

    res = (
        _try_github_extract(url)
        or _try_direct_http_markdown(url)
        or _try_jina_reader_fallback(url)
        or _try_byok_firecrawl(url)
    )
    if not res:
        raise RuntimeError(f"Unable to extract clean article body from URL: {url}")

    extracted_title, author, md_body, tier_used = res
    title = clean_short_title(title_hint or extracted_title, author=author)

    full_md = f"# {title}\n\n- **Source**: {url}\n- **Domain**: {author}\n- **Extractor**: `{tier_used}`\n\n---\n\n{md_body}"
    return OmniExtractResult(
        url=url,
        canonical_url=url,
        platform=platform,
        content_type="article",
        content_id=content_id,
        title=title,
        author=author,
        text=md_body,
        markdown=full_md,
        extraction_tier=tier_used,
        credits_charged=1,
        metadata={"char_count": len(md_body)},
    )
