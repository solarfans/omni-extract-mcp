from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
from typing import Any

from ..models import OmniExtractResult

AID = 6383
DOUYIN_HOST = "https://www.douyin.com/"
SEC_SALT = "A96D855A08C0A9707F8BEF0D9A527E4E"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)


def detect_image_mime_ext(data: bytes) -> tuple[str, str]:
    """Sniff binary magic headers for WebP/JPEG/PNG."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    return "image/jpeg", "jpg"


def clean_short_title(raw_text: str, author: str = "", max_chars: int = 55) -> str:
    clean = unicodedata.normalize("NFC", raw_text or "")
    clean = re.sub(r"[\r\n\t]+", " ", clean)
    clean = re.sub(r"#\S+", "", clean)
    clean = re.sub(r'[\\/:*?"<>|]', " ", clean).strip()
    for delimiter in ["。", "！", "!", "\n", "｜", "|"]:
        if delimiter in clean:
            first_part = clean.split(delimiter)[0].strip()
            if 6 <= len(first_part) <= max_chars:
                return first_part
    if len(clean) > max_chars:
        clean = clean[:max_chars].rstrip(" ，。！!、—-")
    return clean or f"{author or 'Douyin'} Post"


def _get_ttwid(timeout: float = 8.0) -> str:
    try:
        req = urllib.request.Request(
            f"{DOUYIN_HOST}ttwid/register",
            data=json.dumps({"aid": AID, "service": "www.douyin.com"}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            set_cookie = resp.headers.get("Set-Cookie", "")
            for part in set_cookie.split(";"):
                if "ttwid=" in part:
                    return part.split("ttwid=")[1].strip()
    except Exception:
        pass
    return ""


def _get_uifid(timeout: float = 8.0) -> str:
    try:
        req = urllib.request.Request(DOUYIN_HOST, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.headers.get("x-tt-trace-host", "")
    except Exception:
        pass
    return ""


def fetch_douyin_detail_signed(aweme_id: str, timeout: float = 15.0) -> dict[str, Any]:
    """
    Pure-algorithm Cookie-free Douyin detail fetcher using ttwid + uifid + SEC_SALT MD5 web signature.
    """
    ttwid = _get_ttwid()
    uifid = _get_uifid()
    timestamp = str(int(time.time()))
    query = {
        "aweme_id": aweme_id,
        "aid": str(AID),
        "uifid": uifid,
        "timestamp": timestamp,
        "version_code": "190000",
        "version_name": "32.0.0",
        "device_platform": "webapp",
    }
    encoded = urllib.parse.urlencode(query)
    sig = hashlib.md5(f"{uifid}_{timestamp}_{SEC_SALT}_{encoded}".encode()).hexdigest()
    query["x-secsdk-web-signature"] = sig

    api_url = f"{DOUYIN_HOST}aweme/v1/web/aweme/detail/?{urllib.parse.urlencode(query)}"
    req_api = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": USER_AGENT,
            "Cookie": f"ttwid={ttwid}; passport_csrf_token={uuid.uuid4().hex}",
            "Referer": DOUYIN_HOST,
        },
    )
    with urllib.request.urlopen(req_api, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    return data.get("aweme_detail") or {}


def fetch_iesdouyin_ssr_fallback(aweme_id: str, timeout: float = 12.0) -> dict[str, Any]:
    """Fallback parser extracting _ROUTER_DATA JSON from mobile share page."""
    share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
    req = urllib.request.Request(share_url, headers={"User-Agent": MOBILE_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})</script>", html, re.S)
        if m:
            router_data = json.loads(m.group(1))
            loader = router_data.get("loaderData") or {}
            for val in loader.values():
                if isinstance(val, dict):
                    info_res = val.get("videoInfoRes") or {}
                    item_list = info_res.get("item_list") or []
                    if item_list and isinstance(item_list[0], dict):
                        return item_list[0]
    except Exception:
        pass
    return {}


def extract_douyin_stateless(
    url: str,
    aweme_id: str | None = None,
    title_hint: str | None = None,
) -> OmniExtractResult:
    """
    Stateless, cookie-free Douyin extractor returning watermark-free media URLs,
    gallery images, author metadata, engagement counts, and structured Markdown.
    """
    if not aweme_id:
        m = re.search(r"(?:video|note|modal_id=)(\d+)", url)
        if not m:
            raise ValueError(f"Could not locate Douyin aweme_id in URL: {url}")
        aweme_id = m.group(1)

    detail: dict[str, Any] = {}
    tier_used = "douyin_sec_salt_md5_signature"
    try:
        detail = fetch_douyin_detail_signed(aweme_id)
    except Exception:
        detail = {}

    if not detail:
        detail = fetch_iesdouyin_ssr_fallback(aweme_id)
        tier_used = "iesdouyin_mobile_ssr"

    if not detail:
        raise RuntimeError(f"Douyin extraction returned empty detail for aweme_id={aweme_id}")

    desc = str(detail.get("desc") or "").strip()
    author_info = detail.get("author") or {}
    author = str(author_info.get("nickname") or "Douyin Creator").strip()
    stats = detail.get("statistics") or {}

    title = clean_short_title(title_hint or desc, author=author)
    canonical_url = f"https://www.douyin.com/video/{aweme_id}"

    # Check if gallery / image note
    raw_images = detail.get("images") or []
    media_urls: list[str] = []
    cover_url: str | None = None
    duration_sec = 0.0

    if raw_images:
        content_type = "gallery"
        canonical_url = f"https://www.douyin.com/note/{aweme_id}"
        for img_info in raw_images:
            url_list = img_info.get("url_list") or []
            if not url_list:
                continue
            # Prefer non-webp or highest quality URL
            chosen = url_list[0]
            for u in url_list:
                if ".jpeg" in u or ".jpg" in u:
                    chosen = u
                    break
            media_urls.append(str(chosen))
        if media_urls:
            cover_url = media_urls[0]
    else:
        content_type = "video"
        video_info = detail.get("video") or {}
        duration_ms = float(video_info.get("duration") or detail.get("duration") or 0.0)
        duration_sec = duration_ms / 1000.0 if duration_ms > 1000 else duration_ms

        play_addr = video_info.get("play_addr") or {}
        url_list = play_addr.get("url_list") or []
        for u in url_list:
            # Ensure watermark-free play url
            clean_u = str(u).replace("playwm", "play")
            media_urls.append(clean_u)

        cover_info = video_info.get("cover") or video_info.get("origin_cover") or {}
        c_urls = cover_info.get("url_list") or []
        if c_urls:
            cover_url = str(c_urls[0])

    hashtags = [
        f"#{t.get('hashtag_name')}"
        for t in (detail.get("text_extra") or [])
        if isinstance(t, dict) and t.get("hashtag_name")
    ]

    metadata = {
        "aweme_id": aweme_id,
        "author_id": author_info.get("unique_id") or author_info.get("short_id"),
        "digg_count": stats.get("digg_count", 0),
        "comment_count": stats.get("comment_count", 0),
        "collect_count": stats.get("collect_count", 0),
        "share_count": stats.get("share_count", 0),
        "hashtags": hashtags,
        "image_count": len(raw_images),
    }

    md_lines = [
        f"# {title}",
        "",
        f"- **Platform**: Douyin ({content_type})",
        f"- **Author**: {author}",
        f"- **Canonical URL**: {canonical_url}",
        f"- **Engagement**: {metadata['digg_count']} Likes · {metadata['collect_count']} Saves · {metadata['comment_count']} Comments",
    ]
    if duration_sec > 0:
        md_lines.append(f"- **Duration**: {duration_sec:.1f}s")
    md_lines.extend(["", "---", "", "## Description / Caption", "", desc or "(No caption)"])
    if media_urls:
        label = "Gallery Images" if content_type == "gallery" else "Watermark-Free Video Streams"
        md_lines.extend(["", f"## {label}"] + [f"- {u}" for u in media_urls[:10]])

    return OmniExtractResult(
        url=url,
        canonical_url=canonical_url,
        platform="douyin",
        content_type=content_type,  # type: ignore[arg-type]
        content_id=aweme_id,
        title=title,
        author=author,
        text=desc,
        markdown="\n".join(md_lines),
        media_urls=media_urls,
        cover_url=cover_url,
        duration_seconds=duration_sec,
        extraction_tier=tier_used,
        credits_charged=1,
        metadata=metadata,
    )
