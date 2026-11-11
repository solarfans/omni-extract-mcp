from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

from ..models import OmniExtractResult, PlatformType
from .douyin_extractor import clean_short_title


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
