from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PlatformType = Literal[
    "x",
    "douyin",
    "tiktok",
    "youtube",
    "bilibili",
    "xiaohongshu",
    "github",
    "zhihu",
    "wechat",
    "web",
]
ContentType = Literal["article", "video", "gallery"]


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class ResolvedTarget:
    original_input: str
    raw_url: str
    canonical_url: str
    platform: PlatformType
    content_type: ContentType
    content_id: str | None = None
    title_hint: str | None = None


@dataclass
class OmniExtractResult:
    url: str
    canonical_url: str
    platform: PlatformType
    content_type: ContentType
    content_id: str
    title: str
    author: str
    text: str
    markdown: str
    transcript: str | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    cover_url: str | None = None
    duration_seconds: float = 0.0
    extraction_tier: str = "direct"
    credits_charged: int = 1
    cache_hit: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
