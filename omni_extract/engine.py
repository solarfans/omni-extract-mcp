from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .cache_and_billing import CacheAndBillingStore
from .extractors.douyin_extractor import extract_douyin_stateless
from .extractors.video_extractor import extract_video_and_transcript
from .extractors.web_extractor import extract_web_markdown
from .extractors.x_extractor import extract_x_content
from .models import OmniExtractResult
from .resolver import identify_target


class OmniExtractEngine:
    """
    Stateless, multi-platform content & transcript extraction engine.
    Supports X (Tweets/Articles), Douyin, TikTok, YouTube, Bilibili, GitHub, and anti-bot web pages.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        cache_ttl_seconds: int = 86400,
        free_daily_limit: int = 5,
        enforce_billing: bool = False,
    ):
        self.store = CacheAndBillingStore(
            db_path=db_path,
            cache_ttl_seconds=cache_ttl_seconds,
            free_daily_limit=free_daily_limit,
        )
        self.enforce_billing = enforce_billing

    def extract(
        self,
        url_or_text: str,
        include_transcript: bool = True,
        use_cache: bool = True,
        api_key: str | None = None,
        client_id: str = "local_stdio",
    ) -> OmniExtractResult:
        target = identify_target(url_or_text)

        # 1. Check 24h SHA-256 Cache first
        if use_cache:
            cached = self.store.get_cached(target.canonical_url, include_transcript=include_transcript)
            if cached:
                return OmniExtractResult(**cached)

        # 2. Pre-check quota if billing enforcement is active
        if self.enforce_billing:
            quota = self.store.check_quota(api_key=api_key, client_id=client_id)
            if not quota.get("valid"):
                raise PermissionError(
                    quota.get("message")
                    or f"Daily free quota ({self.store.free_daily_limit}/{self.store.free_daily_limit}) reached. "
                    "Provide a valid OMNI_API_KEY ($9 = 500 permanent credits) or run via Apify Store."
                )

        # 3. Route to specialized stateless extractor
        result: OmniExtractResult
        if target.platform == "x":
            result = extract_x_content(url=target.canonical_url, tweet_id=target.content_id)
        elif target.platform == "douyin":
            try:
                result = extract_douyin_stateless(
                    url=target.canonical_url,
                    aweme_id=target.content_id,
                    title_hint=target.title_hint,
                )
            except Exception:
                # Fallback to video/web extractor if Douyin signature route encounters an edge case
                result = extract_video_and_transcript(
                    url=target.canonical_url,
                    platform="douyin",
                    include_transcript=include_transcript,
                    title_hint=target.title_hint,
                )
        elif target.platform in {"youtube", "bilibili", "tiktok"}:
            try:
                result = extract_video_and_transcript(
                    url=target.canonical_url,
                    platform=target.platform,
                    include_transcript=include_transcript,
                    title_hint=target.title_hint,
                )
            except Exception:
                result = extract_web_markdown(
                    url=target.canonical_url,
                    platform=target.platform,
                    title_hint=target.title_hint,
                )
        else:
            result = extract_web_markdown(
                url=target.canonical_url,
                platform=target.platform,
                title_hint=target.title_hint,
            )

        # 4. Record billing / credit consumption
        billing_receipt = self.store.consume_credits(
            credits=result.credits_charged,
            api_key=api_key,
            client_id=client_id,
            enforce=self.enforce_billing,
        )
        result.metadata["billing"] = billing_receipt

        # 5. Always persist fresh extraction into 24h cache
        self.store.set_cached(
            canonical_url=target.canonical_url,
            platform=result.platform,
            payload=result.to_dict(),
            include_transcript=include_transcript,
        )

        return result

    def extract_batch(
        self,
        urls: list[str],
        include_transcript: bool = True,
        use_cache: bool = True,
        api_key: str | None = None,
        client_id: str = "local_stdio",
        max_workers: int = 4,
    ) -> list[dict[str, Any]]:
        bounded_urls = [u.strip() for u in urls if u and u.strip()][:10]
        results: list[dict[str, Any]] = [{}] * len(bounded_urls)

        def _worker(idx: int, u: str) -> tuple[int, dict[str, Any]]:
            try:
                res = self.extract(
                    url_or_text=u,
                    include_transcript=include_transcript,
                    use_cache=use_cache,
                    api_key=api_key,
                    client_id=client_id,
                )
                return idx, {"ok": True, **res.to_dict()}
            except Exception as e:
                return idx, {"ok": False, "url": u, "error": str(e)}

        with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(bounded_urls)))) as pool:
            futures = [pool.submit(_worker, i, u) for i, u in enumerate(bounded_urls)]
            for fut in as_completed(futures):
                idx, payload = fut.result()
                results[idx] = payload

        return results
