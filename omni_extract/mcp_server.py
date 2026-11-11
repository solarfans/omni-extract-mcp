from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import urllib.parse
from typing import Any

from . import __version__
from .engine import OmniExtractEngine

MCP_PROTOCOL_VERSION = "2024-11-05"

MCP_TOOLS_SCHEMA = [
    {
        "name": "omni_extract_url",
        "description": (
            "Universal, cookie-free content & transcript extractor for AI Agents. "
            "Extracts full long-form X (Twitter) Articles/Tweets, watermark-free Douyin/TikTok videos & photo galleries, "
            "YouTube/Bilibili video subtitles/transcripts with timestamps, GitHub READMEs/code, and anti-bot web pages into clean Markdown."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target URL or share text containing a URL (X/Twitter, Douyin, TikTok, YouTube, Bilibili, GitHub, or any web page).",
                },
                "include_transcript": {
                    "type": "boolean",
                    "description": "Whether to extract full video subtitles/transcripts for video URLs (default: true).",
                    "default": True,
                },
                "output_format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Return formatted Markdown ('markdown') or full structured JSON metadata ('json'). Default: 'markdown'.",
                    "default": "markdown",
                },
                "api_key": {
                    "type": "string",
                    "description": "Optional OmniExtract API key (omni_live_...) for paid credit packs.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "omni_extract_batch",
        "description": (
            "Concurrently extract up to 10 URLs (X Articles, Douyin, TikTok, YouTube, GitHub, Web) in parallel."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of URLs to extract concurrently (max 10 per call).",
                },
                "include_transcript": {
                    "type": "boolean",
                    "default": True,
                },
                "api_key": {
                    "type": "string",
                    "description": "Optional OmniExtract API key (omni_live_...).",
                },
            },
            "required": ["urls"],
        },
    },
    {
        "name": "omni_check_quota",
        "description": "Check remaining API key credits or daily anonymous free quota.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "description": "Optional OmniExtract API key (omni_live_...).",
                }
            },
        },
    },
]


def handle_mcp_jsonrpc(
    engine: OmniExtractEngine,
    request_obj: dict[str, Any],
    default_api_key: str | None = None,
    client_id: str = "local_stdio",
) -> dict[str, Any] | None:
    """Process a single MCP JSON-RPC 2.0 request and return the response dict (or None for notifications)."""
    method = str(request_obj.get("method") or "")
    req_id = request_obj.get("id")
    params = request_obj.get("params") or {}

    # Notifications have no 'id' and expect no response
    if req_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "omni-extract-mcp",
                    "version": __version__,
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS_SCHEMA},
        }

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        api_key = str(args.get("api_key") or default_api_key or "").strip() or None

        try:
            if tool_name == "omni_extract_url":
                url = str(args.get("url") or "").strip()
                if not url:
                    raise ValueError("Missing required parameter: 'url'")
                include_transcript = bool(args.get("include_transcript", True))
                output_format = str(args.get("output_format") or "markdown").lower()

                res = engine.extract(
                    url_or_text=url,
                    include_transcript=include_transcript,
                    api_key=api_key,
                    client_id=client_id,
                )
                text_out = (
                    json.dumps(res.to_dict(), ensure_ascii=False, indent=2)
                    if output_format == "json"
                    else res.markdown
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": text_out}],
                        "isError": False,
                    },
                }

            if tool_name == "omni_extract_batch":
                urls = args.get("urls") or []
                if not isinstance(urls, list) or not urls:
                    raise ValueError("Parameter 'urls' must be a non-empty list of URLs.")
                include_transcript = bool(args.get("include_transcript", True))
                batch_res = engine.extract_batch(
                    urls=[str(u) for u in urls],
                    include_transcript=include_transcript,
                    api_key=api_key,
                    client_id=client_id,
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(batch_res, ensure_ascii=False, indent=2),
                            }
                        ],
                        "isError": False,
                    },
                }

            if tool_name == "omni_check_quota":
                quota = engine.store.check_quota(api_key=api_key, client_id=client_id)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(quota, ensure_ascii=False, indent=2),
                            }
                        ],
                        "isError": False,
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"OmniExtract Error: {e}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_stdio_server(engine: OmniExtractEngine) -> int:
    """Run MCP server over standard input/output (for Claude Desktop, Cursor, Windsurf, OpenClaw)."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        resp = handle_mcp_jsonrpc(engine, req, client_id="local_stdio")
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


def make_http_handler(engine: OmniExtractEngine) -> type[BaseHTTPRequestHandler]:
    class OmniHTTPHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Quiet clean logging
            pass

        def _client_ip(self) -> str:
            forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            return forwarded or self.client_address[0] or "http_client"

        def _extract_api_key(self) -> str | None:
            auth = self.headers.get("Authorization", "").strip()
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
            header_key = self.headers.get("X-Omni-Api-Key", "").strip()
            if header_key:
                return header_key
            parsed = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            if "apiKey" in q and q["apiKey"]:
                return q["apiKey"][0].strip()
            return None

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Omni-Api-Key")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self._send_json(200, {"ok": True})

        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path in {"/", "/v1/health", "/health"}:
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "service": "omni-extract-mcp",
                        "version": __version__,
                        "protocols": ["mcp-jsonrpc-2.0", "rest-v1"],
                        "tools": [t["name"] for t in MCP_TOOLS_SCHEMA],
                    },
                )
                return

            if parsed.path == "/v1/quota":
                quota = engine.store.check_quota(api_key=self._extract_api_key(), client_id=self._client_ip())
                self._send_json(200, {"ok": True, "quota": quota})
                return

            self._send_json(404, {"ok": False, "error": f"Unknown route: {parsed.path}"})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(min(length, 2_000_000)) if length > 0 else b"{}"
            try:
                body = json.loads(raw_body.decode("utf-8", errors="replace"))
            except Exception:
                self._send_json(400, {"ok": False, "error": "Invalid JSON body"})
                return

            api_key = self._extract_api_key()
            client_id = self._client_ip()

            # 1. Streamable HTTP MCP Endpoint
            if parsed.path in {"/mcp", "/v1/mcp"}:
                resp = handle_mcp_jsonrpc(engine, body, default_api_key=api_key, client_id=client_id)
                self._send_json(200, resp or {"ok": True})
                return

            # 2. Direct REST Single URL Extraction
            if parsed.path == "/v1/extract":
                url = str(body.get("url") or "").strip()
                if not url:
                    self._send_json(400, {"ok": False, "error": "Missing required field 'url'"})
                    return
                include_transcript = bool(body.get("include_transcript", True))
                try:
                    res = engine.extract(
                        url_or_text=url,
                        include_transcript=include_transcript,
                        api_key=api_key or body.get("api_key"),
                        client_id=client_id,
                    )
                    self._send_json(200, {"ok": True, **res.to_dict()})
                except PermissionError as pe:
                    self._send_json(402, {"ok": False, "error": str(pe), "code": "PAYMENT_REQUIRED"})
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
                return

            # 3. Direct REST Batch Extraction
            if parsed.path == "/v1/extract/batch":
                urls = body.get("urls") or []
                if not isinstance(urls, list) or not urls:
                    self._send_json(400, {"ok": False, "error": "Field 'urls' must be a non-empty array"})
                    return
                include_transcript = bool(body.get("include_transcript", True))
                batch = engine.extract_batch(
                    urls=[str(u) for u in urls],
                    include_transcript=include_transcript,
                    api_key=api_key or body.get("api_key"),
                    client_id=client_id,
                )
                self._send_json(200, {"ok": True, "results": batch})
                return

            self._send_json(404, {"ok": False, "error": f"Unknown POST route: {parsed.path}"})

    return OmniHTTPHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OmniExtract MCP Server & REST Gateway")
    parser.add_argument(
        "--mode",
        choices=["stdio", "http"],
        default=os.environ.get("OMNI_SERVER_MODE", "stdio"),
        help="Server transport mode: 'stdio' (default for local MCP) or 'http' (for Cloud Run / Remote MCP)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "0.0.0.0"),
        help="Bind host for HTTP mode (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8080")),
        help="Bind port for HTTP mode (default: 8080)",
    )
    parser.add_argument(
        "--enforce-billing",
        action="store_true",
        default=os.environ.get("OMNI_ENFORCE_BILLING", "0") == "1",
        help="Enforce API key credit checks and daily anonymous free limits",
    )
    parser.add_argument(
        "--mint-key",
        type=int,
        metavar="CREDITS",
        default=None,
        help="Mint a new paid API key with the specified number of credits and exit",
    )
    parser.add_argument(
        "--email",
        default="",
        help="Customer email when using --mint-key",
    )
    args = parser.parse_args(argv)

    engine = OmniExtractEngine(enforce_billing=args.enforce_billing)

    if args.mint_key is not None:
        key = engine.store.mint_api_key(credits=args.mint_key, owner_email=args.email)
        print(json.dumps({"api_key": key, "credits": args.mint_key, "owner_email": args.email}, indent=2))
        return 0

    if args.mode == "stdio":
        return run_stdio_server(engine)

    handler_cls = make_http_handler(engine)
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)
    print(f"OmniExtract MCP & REST Gateway listening on http://{args.host}:{args.port} (enforce_billing={args.enforce_billing})", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
