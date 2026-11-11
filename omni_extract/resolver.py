from __future__ import annotations

import re
import urllib.parse
import urllib.request

from .models import ContentType, PlatformType, ResolvedTarget

URL_REGEX = re.compile(r'https?://[^\s<>"\'{}|\\^`\])}]+')

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

SHORTLINK_HOSTS = {
    "v.douyin.com",
    "vt.tiktok.com",
    "vm.tiktok.com",
    "b23.tv",
    "youtu.be",
    "t.co",
    "xhslink.com",
    "bit.ly",
    "tinyurl.com",
}

STRIP_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm_id_from",
    "vd_source",
    "share_source",
    "share_medium",
    "share_plat",
    "share_from",
    "sec_uid",
    "u_code",
    "did",
    "iid",
    "with_sec_did",
    "titleType",
    "bc_params",
    " s",
}


def extract_url(text: str) -> str | None:
    match = URL_REGEX.search(text.strip())
    if not match:
        return None
    return match.group(0).rstrip(".,;!?，。；！？")


def _clean_tracking_params(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower()
    if "douyin.com" in host or "iesdouyin.com" in host:
        # Keep modal_id if present, strip noisy tracking query params
        q = urllib.parse.parse_qs(parsed.query)
        if "modal_id" in q and q["modal_id"]:
            return urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, f"modal_id={q['modal_id'][0]}", "")
            )
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if "x.com" in host or "twitter.com" in host:
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return url


def resolve_redirect(url: str, timeout: float = 10.0) -> str:
    """Follow HTTP 301/302 redirects for shortlinks and strip tracking clutter."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.netloc.lower() in SHORTLINK_HOSTS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                target = resp.geturl()
                return _clean_tracking_params(target)
        except urllib.error.HTTPError as e:
            # Even if final page returns 403/302, e.url often contains the resolved destination
            if getattr(e, "url", None) and e.url != url:
                return _clean_tracking_params(e.url)
        except Exception:
            pass
    return _clean_tracking_params(url)


def identify_target(text_or_url: str, resolve_shortlinks: bool = True) -> ResolvedTarget:
    url = extract_url(text_or_url)
    if not url:
        raise ValueError(f"No valid HTTP/HTTPS URL found in input: {text_or_url[:100]!r}")

    canonical = resolve_redirect(url) if resolve_shortlinks else _clean_tracking_params(url)
    parsed = urllib.parse.urlsplit(canonical)
    host = parsed.netloc.lower()
    path = parsed.path
    query_map = urllib.parse.parse_qs(parsed.query)

    platform: PlatformType = "web"
    content_type: ContentType = "article"
    content_id: str | None = None

    # 1. X / Twitter
    if "x.com" in host or "twitter.com" in host or "fxtwitter.com" in host or "vxtwitter.com" in host:
        platform = "x"
        content_type = "article"
        m = re.search(r"/(?:status|article)/(\d+)", path)
        if m:
            content_id = m.group(1)

    # 2. Douyin / iesdouyin
    elif "douyin.com" in host or "iesdouyin.com" in host:
        platform = "douyin"
        if "modal_id" in query_map and query_map["modal_id"]:
            content_id = query_map["modal_id"][0]
            content_type = "video"
        elif "/note/" in path:
            content_type = "gallery"
            m = re.search(r"/note/(\d+)", path)
            if m:
                content_id = m.group(1)
        elif "/video/" in path:
            content_type = "video"
            m = re.search(r"/video/(\d+)", path)
            if m:
                content_id = m.group(1)
        else:
            m = re.search(r"/(?:video|note)/(\d+)", canonical)
            if m:
                content_id = m.group(1)
                content_type = "gallery" if "/note/" in canonical else "video"

    # 3. TikTok
    elif "tiktok.com" in host:
        platform = "tiktok"
        if "/photo/" in path:
            content_type = "gallery"
            m = re.search(r"/photo/(\d+)", path)
            if m:
                content_id = m.group(1)
        else:
            content_type = "video"
            m = re.search(r"/video/(\d+)", path)
            if m:
                content_id = m.group(1)

    # 4. YouTube
    elif "youtube.com" in host or "youtu.be" in host:
        platform = "youtube"
        content_type = "video"
        if "youtu.be" in host:
            content_id = path.strip("/").split("/")[0]
        elif "/shorts/" in path:
            m = re.search(r"/shorts/([A-Za-z0-9_-]+)", path)
            if m:
                content_id = m.group(1)
        elif "v" in query_map and query_map["v"]:
            content_id = query_map["v"][0]

    # 5. Bilibili
    elif "bilibili.com" in host or "b23.tv" in host:
        platform = "bilibili"
        content_type = "video"
        m = re.search(r"/(BV[A-Za-z0-9]+|av\d+)", canonical)
        if m:
            content_id = m.group(1)

    # 6. Xiaohongshu
    elif "xiaohongshu.com" in host or "xhslink.com" in host:
        platform = "xiaohongshu"
        content_type = "article"
        m = re.search(r"/(?:explore|item)/([a-zA-Z0-9]+)", path)
        if m:
            content_id = m.group(1)

    # 7. GitHub / Zhihu / WeChat / Web
    elif "github.com" in host:
        platform = "github"
        content_type = "article"
    elif "zhihu.com" in host:
        platform = "zhihu"
        content_type = "article"
    elif "mp.weixin.qq.com" in host:
        platform = "wechat"
        content_type = "article"
    else:
        platform = "web"
        content_type = "article"

    title_hint = None
    if text_or_url.strip() != url:
        cleaned = text_or_url.replace(url, "").strip()
        m = re.search(r"【(.*?)】", cleaned)
        if m:
            title_hint = m.group(1).strip()
        elif len(cleaned) > 4:
            title_hint = cleaned[:80].strip()

    return ResolvedTarget(
        original_input=text_or_url,
        raw_url=url,
        canonical_url=canonical,
        platform=platform,
        content_type=content_type,
        content_id=content_id,
        title_hint=title_hint,
    )
