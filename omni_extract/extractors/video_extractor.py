from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from typing import Any

from ..models import OmniExtractResult, PlatformType
from .douyin_extractor import clean_short_title


def extract_tiktok_stateless(url: str, title_hint: str | None = None, timeout: float = 12.0) -> OmniExtractResult | None:
    """
    Fast cookie-free TikTok extractor (TikWM + oEmbed) that works reliably on datacenter/cloud IPs
    where direct TikTok webpage scraping or yt-dlp might hit CAPTCHA/login walls.
    Extracts HD watermark-free MP4 or Photo Carousel images, engagement stats, and clean Markdown.
    """
    try:
        api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url, safe='')}&hd=1"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read(2_000_000).decode("utf-8", errors="replace"))
        if payload.get("code") == 0 and isinstance(payload.get("data"), dict):
            data = payload["data"]
            vid_id = str(data.get("id") or "tiktok")
            author_obj = data.get("author") or {}
            author = str(author_obj.get("nickname") or author_obj.get("unique_id") or "TikTok Creator")
            unique_id = str(author_obj.get("unique_id") or "")
            desc = str(data.get("title") or data.get("content_desc") or "").strip()
            title = clean_short_title(title_hint or desc or f"TikTok {vid_id}", author=author)
            duration = float(data.get("duration") or 0.0)
            cover_url = str(data.get("origin_cover") or data.get("cover") or "") or None

            images = data.get("images")
            media_urls: list[str] = []
            content_type = "video"
            if isinstance(images, list) and images:
                content_type = "gallery"
                media_urls = [str(img) for img in images if img]
            else:
                play_url = str(data.get("hdplay") or data.get("play") or data.get("wmplay") or "")
                if play_url:
                    media_urls.append(play_url)

            canonical_url = (
                f"https://www.tiktok.com/@{unique_id}/video/{vid_id}"
                if unique_id and vid_id.isdigit()
                else url
            )

            md_lines = [
                f"# {title}",
                "",
                "- **Platform**: TikTok",
                f"- **Author**: {author}" + (f" (`@{unique_id}`)" if unique_id else ""),
                f"- **URL**: {canonical_url}",
                f"- **Content Type**: {content_type}",
                f"- **Duration**: {duration:.1f}s",
                f"- **Stats**: ❤️ {data.get('digg_count', 0)} | 💬 {data.get('comment_count', 0)} | 🔄 {data.get('share_count', 0)} | ▶️ {data.get('play_count', 0)}",
                "",
                "---",
                "",
            ]
            if desc:
                md_lines.extend(["## Caption / Description", "", desc, ""])
            if media_urls:
                md_lines.append("## Watermark-Free Media URLs")
                md_lines.append("")
                for idx, m_url in enumerate(media_urls, 1):
                    md_lines.append(f"{idx}. {m_url}")

            return OmniExtractResult(
                url=url,
                canonical_url=canonical_url,
                platform="tiktok",
                content_type=content_type,  # type: ignore[arg-type]
                content_id=vid_id,
                title=title,
                author=author,
                text=desc or title,
                markdown="\n".join(md_lines).strip(),
                media_urls=media_urls,
                cover_url=cover_url,
                duration_seconds=duration,
                extraction_tier="tiktok_tikwm_stateless",
                credits_charged=1,
                metadata={
                    "region": data.get("region"),
                    "play_count": data.get("play_count"),
                    "digg_count": data.get("digg_count"),
                    "comment_count": data.get("comment_count"),
                    "share_count": data.get("share_count"),
                    "music_title": (data.get("music_info") or {}).get("title"),
                },
            )
    except Exception:
        pass
    return None


def extract_bilibili_stateless(url: str, title_hint: str | None = None, timeout: float = 12.0) -> OmniExtractResult | None:
    """
    Fast cookie-free Bilibili SSR (__INITIAL_STATE__) extractor with automatic GZIP decompression.
    Extracts video title, UP author, description, duration, cover image, and engagement stats
    without hitting Bilibili API 412 blocks or requiring yt-dlp login cookies.
    """
    import gzip
    import zlib

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_500_000)
            enc = (resp.headers.get("Content-Encoding") or "").lower()
            if "gzip" in enc or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            elif "deflate" in enc:
                raw = zlib.decompress(raw)
            html_str = raw.decode("utf-8", errors="replace")

        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});\(function", html_str)
        if not m:
            return None
        state = json.loads(m.group(1))
        vd = state.get("videoData") or {}
        if not vd or not vd.get("title"):
            return None

        bvid = str(vd.get("bvid") or state.get("bvid") or "bilibili")
        author = str((vd.get("owner") or {}).get("name") or "Bilibili UP")
        raw_title = title_hint or vd.get("title") or f"Bilibili {bvid}"
        title = clean_short_title(str(raw_title), author=author)
        desc = str(vd.get("desc") or "").strip()
        duration = float(vd.get("duration") or 0.0)
        cover_url = str(vd.get("pic") or "") or None
        if cover_url and cover_url.startswith("http://"):
            cover_url = "https://" + cover_url[len("http://") :]
        canonical_url = f"https://www.bilibili.com/video/{bvid}" if bvid.startswith("BV") else url
        stat = vd.get("stat") or {}

        # Extract subtitle list if embedded in SSR videoData
        sub_list = ((vd.get("subtitle") or {}).get("list")) or []
        media_urls: list[str] = []
        if cover_url:
            media_urls.append(cover_url)

        md_lines = [
            f"# {title}",
            "",
            "- **Platform**: Bilibili (哔哩哔哩)",
            f"- **Author (UP主)**: {author}",
            f"- **URL**: {canonical_url}",
            f"- **BVID**: `{bvid}`",
            f"- **Duration**: {duration:.1f}s",
            f"- **Stats**: ▶️ {stat.get('view', 0)} | 👍 {stat.get('like', 0)} | 🪙 {stat.get('coin', 0)} | ⭐ {stat.get('favorite', 0)} | 💬 {stat.get('reply', 0)}",
            "",
            "---",
            "",
        ]
        if desc:
            md_lines.extend(["## Description (视频简介)", "", desc, ""])

        pages = vd.get("pages") or []
        if len(pages) > 1:
            md_lines.append("## Video Chapters / Parts (分P列表)")
            md_lines.append("")
            for p in pages[:25]:
                md_lines.append(f"- **P{p.get('page')}**: {p.get('part')} ({p.get('duration', 0)}s)")

        return OmniExtractResult(
            url=url,
            canonical_url=canonical_url,
            platform="bilibili",
            content_type="video",
            content_id=bvid,
            title=title,
            author=author,
            text=desc or title,
            markdown="\n".join(md_lines).strip(),
            media_urls=media_urls,
            cover_url=cover_url,
            duration_seconds=duration,
            extraction_tier="bilibili_ssr_initial_state",
            credits_charged=1,
            metadata={
                "bvid": bvid,
                "aid": vd.get("aid"),
                "view_count": stat.get("view"),
                "like_count": stat.get("like"),
                "coin_count": stat.get("coin"),
                "favorite_count": stat.get("favorite"),
                "danmaku_count": stat.get("danmaku"),
                "subtitle_tracks": len(sub_list),
            },
        )
    except Exception:
        pass
    return None


def _find_binary(name: str, env_var: str) -> str:
    env_val = os.environ.get(env_var, "").strip()
    if env_val and shutil.which(env_val):
        return env_val
    found = shutil.which(name)
    if found:
        return found
    for candidate in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}", f"/usr/bin/{name}"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return name


def _parse_timestamp_sec(ts: str) -> float:
    """Parse VTT/SRT timestamp '00:01:23.450' or '01:23,450' into seconds."""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except Exception:
        pass
    return 0.0


def parse_subtitle_content(raw_sub: str) -> tuple[str, list[dict[str, Any]]]:
    """
    Parse VTT or SRT subtitle file into deduplicated plain text + timestamped segments.
    """
    segments: list[dict[str, Any]] = []
    cleaned_lines: list[str] = []

    current_start = 0.0
    current_end = 0.0
    current_text_parts: list[str] = []

    def flush_segment() -> None:
        if not current_text_parts:
            return
        seg_text = " ".join(current_text_parts).strip()
        current_text_parts.clear()
        if not seg_text:
            return
        if not cleaned_lines or cleaned_lines[-1] != seg_text:
            cleaned_lines.append(seg_text)
            segments.append(
                {
                    "start": round(current_start, 2),
                    "end": round(current_end, 2),
                    "text": seg_text,
                }
            )

    for raw_line in raw_sub.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            flush_segment()
            arrow_parts = line.split("-->")
            current_start = _parse_timestamp_sec(arrow_parts[0].split()[0])
            current_end = _parse_timestamp_sec(arrow_parts[1].split()[0])
            continue
        line_clean = re.sub(r"<[^>]+>", "", line).strip()
        if line_clean:
            current_text_parts.append(line_clean)

    flush_segment()
    return "\n".join(cleaned_lines), segments


def extract_video_and_transcript(
    url: str,
    platform: PlatformType = "youtube",
    include_transcript: bool = True,
    title_hint: str | None = None,
) -> OmniExtractResult:
    """
    3-Layer Video & Subtitle Extractor using yt-dlp:
    Layer 1: Fast metadata & stream extraction (--dump-json)
    Layer 2: Native/Auto-caption VTT/SRT extraction (--write-subs / --write-auto-subs)
    Layer 3: Optional Whisper CLI fallback if configured via OMNI_WHISPER_BIN + OMNI_WHISPER_MODEL
    """
    ytdlp_bin = _find_binary("yt-dlp", "OMNI_YTDLP_BIN")

    cmd_meta = [
        ytdlp_bin,
        "--no-playlist",
        "--dump-json",
        "--no-warnings",
        url,
    ]
    proc_meta = subprocess.run(cmd_meta, capture_output=True, text=True, check=True, timeout=60)
    first_json_line = proc_meta.stdout.strip().splitlines()[0]
    info = json.loads(first_json_line)

    content_id = str(info.get("id") or "video")
    author = str(info.get("uploader") or info.get("channel") or info.get("creator") or "Creator")
    raw_title = title_hint or info.get("title") or info.get("description", "")[:60] or f"Video {content_id}"
    title = clean_short_title(str(raw_title), author=author)
    desc = str(info.get("description") or "").strip()
    duration = float(info.get("duration") or 0.0)
    canonical_url = str(info.get("webpage_url") or url)
    cover_url = str(info.get("thumbnail") or "") or None

    media_urls: list[str] = []
    if info.get("url"):
        media_urls.append(str(info["url"]))

    transcript: str | None = None
    segments: list[dict[str, Any]] = []
    tier_used = "ytdlp_metadata_only"
    credits_charged = 1

    if include_transcript:
        subs_info = info.get("subtitles") or {}
        auto_subs = info.get("automatic_captions") or {}

        target_sub_lang = None
        for lang in ("zh-Hans", "zh-CN", "zh", "zh-Hant", "en", "en-US", "en-orig"):
            if lang in subs_info or lang in auto_subs:
                target_sub_lang = lang
                break
        if not target_sub_lang:
            # Pick first available language if any
            if subs_info:
                target_sub_lang = next(iter(subs_info.keys()))
            elif auto_subs:
                target_sub_lang = next(iter(auto_subs.keys()))

        sandbox = Path(tempfile.mkdtemp(prefix="omni_vid_sub_"))
        try:
            if target_sub_lang:
                sub_out = str(sandbox / "subtitle.%(ext)s")
                cmd_sub = [
                    ytdlp_bin,
                    "--no-playlist",
                    "--skip-download",
                    "--write-subs",
                    "--write-auto-subs",
                    "--sub-lang",
                    target_sub_lang,
                    "--sub-format",
                    "vtt/srt/best",
                    "-o",
                    sub_out,
                    url,
                ]
                subprocess.run(cmd_sub, capture_output=True, timeout=35)
                for sub_file in sandbox.glob("subtitle.*"):
                    if sub_file.suffix.lower() in (".vtt", ".srt"):
                        raw_sub = sub_file.read_text(encoding="utf-8", errors="ignore")
                        parsed_text, parsed_segs = parse_subtitle_content(raw_sub)
                        if parsed_text:
                            transcript = parsed_text
                            segments = parsed_segs
                            tier_used = f"ytdlp_native_subtitles:{target_sub_lang}"
                            credits_charged = 2
                            break
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    body_text = transcript or desc
    md_lines = [
        f"# {title}",
        "",
        f"- **Platform**: {platform}",
        f"- **Author**: {author}",
        f"- **URL**: {canonical_url}",
        f"- **Duration**: {duration:.1f}s",
        "",
        "---",
        "",
    ]
    if desc:
        md_lines.extend(["## Description", "", desc, ""])
    if transcript:
        md_lines.extend(["## Full Transcript", "", transcript])

    return OmniExtractResult(
        url=url,
        canonical_url=canonical_url,
        platform=platform,
        content_type="video",
        content_id=content_id,
        title=title,
        author=author,
        text=body_text,
        markdown="\n".join(md_lines).strip(),
        transcript=transcript,
        segments=segments,
        media_urls=media_urls,
        cover_url=cover_url,
        duration_seconds=duration,
        extraction_tier=tier_used,
        credits_charged=credits_charged,
        metadata={
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "upload_date": info.get("upload_date"),
            "subtitle_segments_count": len(segments),
        },
    )
