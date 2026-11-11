from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any


class CacheAndBillingStore:
    """
    Lightweight SQLite WAL store for:
    1. 24-hour SHA-256 URL extraction result caching (0ms repeat responses, $0 marginal cost)
    2. API Key credit metering ($9 = 500 credits) & daily anonymous free quota (5 calls/day/client)
    """

    def __init__(self, db_path: Path | str | None = None, cache_ttl_seconds: int = 86400, free_daily_limit: int = 5):
        if db_path is None:
            env_db = os.environ.get("OMNI_DB_PATH", "").strip()
            if env_db:
                db_path = Path(env_db)
            else:
                db_path = Path(__file__).resolve().parent.parent / "data" / "omni_extract_state.sqlite3"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.free_daily_limit = free_daily_limit
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS extraction_cache (
                    cache_key TEXT PRIMARY KEY,
                    canonical_url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    api_key TEXT PRIMARY KEY,
                    owner_email TEXT DEFAULT '',
                    tier TEXT DEFAULT 'credits_pack',
                    credits_remaining INTEGER NOT NULL DEFAULT 0,
                    total_credits_used INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS daily_free_quota (
                    client_id TEXT NOT NULL,
                    day_bucket TEXT NOT NULL,
                    calls_used INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (client_id, day_bucket)
                );
                """
            )

    @staticmethod
    def make_cache_key(canonical_url: str, include_transcript: bool = True) -> str:
        raw = f"{canonical_url.strip()}|sub={int(bool(include_transcript))}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_cached(self, canonical_url: str, include_transcript: bool = True) -> dict[str, Any] | None:
        if self.cache_ttl_seconds <= 0:
            return None
        key = self.make_cache_key(canonical_url, include_transcript)
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, created_at FROM extraction_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            if now - float(row["created_at"]) > self.cache_ttl_seconds:
                conn.execute("DELETE FROM extraction_cache WHERE cache_key = ?", (key,))
                return None
            data = json.loads(row["payload_json"])
            data["cache_hit"] = True
            return data

    def set_cached(self, canonical_url: str, platform: str, payload: dict[str, Any], include_transcript: bool = True) -> None:
        if self.cache_ttl_seconds <= 0:
            return
        key = self.make_cache_key(canonical_url, include_transcript)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO extraction_cache (cache_key, canonical_url, platform, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (key, canonical_url, platform, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def mint_api_key(self, credits: int = 500, owner_email: str = "", custom_key: str | None = None) -> str:
        api_key = custom_key or f"omni_live_{secrets.token_hex(16)}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (api_key, owner_email, tier, credits_remaining, total_credits_used, created_at, updated_at, is_active)
                VALUES (?, ?, 'credits_pack', ?, 0, ?, ?, 1)
                ON CONFLICT(api_key) DO UPDATE SET
                    credits_remaining = api_keys.credits_remaining + excluded.credits_remaining,
                    updated_at = excluded.updated_at,
                    is_active = 1
                """,
                (api_key, owner_email, int(credits), now, now),
            )
        return api_key

    def check_quota(self, api_key: str | None = None, client_id: str = "local_stdio") -> dict[str, Any]:
        clean_key = (api_key or os.environ.get("OMNI_API_KEY") or "").strip()
        if clean_key:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT api_key, owner_email, tier, credits_remaining, total_credits_used, is_active FROM api_keys WHERE api_key = ?",
                    (clean_key,),
                ).fetchone()
                if not row or not row["is_active"]:
                    return {
                        "valid": False,
                        "tier": "invalid_key",
                        "credits_remaining": 0,
                        "message": "Invalid or inactive OMNI_API_KEY.",
                    }
                return {
                    "valid": row["credits_remaining"] > 0,
                    "tier": row["tier"],
                    "owner_email": row["owner_email"],
                    "credits_remaining": int(row["credits_remaining"]),
                    "total_credits_used": int(row["total_credits_used"]),
                }

        day_bucket = time.strftime("%Y-%m-%d", time.gmtime())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT calls_used FROM daily_free_quota WHERE client_id = ? AND day_bucket = ?",
                (client_id, day_bucket),
            ).fetchone()
            used = int(row["calls_used"]) if row else 0
            remaining = max(0, self.free_daily_limit - used)
            return {
                "valid": remaining > 0,
                "tier": "free_daily",
                "client_id": client_id,
                "day_bucket": day_bucket,
                "free_calls_used": used,
                "free_calls_remaining": remaining,
                "free_daily_limit": self.free_daily_limit,
            }

    def consume_credits(
        self,
        credits: int = 1,
        api_key: str | None = None,
        client_id: str = "local_stdio",
        enforce: bool = False,
    ) -> dict[str, Any]:
        """
        Atomically deduct credits from an API key or increment daily free quota.
        When enforce=False (e.g. local stdio or Apify Actor where Apify bills PPE directly),
        it records usage without blocking.
        """
        clean_key = (api_key or os.environ.get("OMNI_API_KEY") or "").strip()
        now = time.time()
        if clean_key:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT credits_remaining, is_active FROM api_keys WHERE api_key = ?",
                    (clean_key,),
                ).fetchone()
                if not row or not row["is_active"]:
                    if enforce:
                        raise PermissionError("Invalid OMNI_API_KEY. Purchase a 500-credit pack ($9) to continue.")
                    return {"tier": "unverified", "credits_remaining": 0}
                rem = int(row["credits_remaining"])
                if rem < credits and enforce:
                    raise PermissionError(
                        f"Insufficient credits ({rem} remaining, {credits} needed). Top up at Polar.sh / Apify Store."
                    )
                new_rem = max(0, rem - credits)
                conn.execute(
                    """
                    UPDATE api_keys
                    SET credits_remaining = ?, total_credits_used = total_credits_used + ?, updated_at = ?
                    WHERE api_key = ?
                    """,
                    (new_rem, credits, now, clean_key),
                )
                return {"tier": "paid_api_key", "credits_charged": credits, "credits_remaining": new_rem}

        day_bucket = time.strftime("%Y-%m-%d", time.gmtime())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT calls_used FROM daily_free_quota WHERE client_id = ? AND day_bucket = ?",
                (client_id, day_bucket),
            ).fetchone()
            used = int(row["calls_used"]) if row else 0
            if enforce and used >= self.free_daily_limit:
                raise PermissionError(
                    f"Daily free quota ({self.free_daily_limit}/{self.free_daily_limit}) reached for {client_id}. "
                    "Pass an OMNI_API_KEY ($9 = 500 permanent credits) or call via Apify Store."
                )
            conn.execute(
                """
                INSERT INTO daily_free_quota (client_id, day_bucket, calls_used)
                VALUES (?, ?, 1)
                ON CONFLICT(client_id, day_bucket) DO UPDATE SET
                    calls_used = daily_free_quota.calls_used + 1
                """,
                (client_id, day_bucket),
            )
            return {
                "tier": "free_daily",
                "credits_charged": credits,
                "free_calls_remaining": max(0, self.free_daily_limit - (used + 1)),
            }
