"""Step 1: obtain a DocuSign Demo OAuth access token for MCP testing.

Run this only after creating an Integration Key + Secret Key in your
DocuSign developer account and adding the redirect URI:
    http://localhost:8765/callback

The script opens the DocuSign authorization URL manually in your browser,
receives the localhost callback, and exchanges the authorization code for
an access token.
"""
from __future__ import annotations

import os
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx2
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("DOCUSIGN_CLIENT_ID")
CLIENT_SECRET = os.getenv("DOCUSIGN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DOCUSIGN_REDIRECT_URI", "http://localhost:8765/callback")
AUTH_BASE = "https://account-d.docusign.com"
TOKEN_URL = f"{AUTH_BASE}/oauth/token"

if not CLIENT_ID or not CLIENT_SECRET:
    raise SystemExit(
        "Missing DOCUSIGN_CLIENT_ID / DOCUSIGN_CLIENT_SECRET in .env"
    )

callback_result: dict[str, str] = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        callback_result["code"] = params.get("code", [""])[0]
        callback_result["state"] = params.get("state", [""])[0]
        callback_result["error"] = params.get("error", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"DocuSign authorization received. You can close this tab.")

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "scope": "signature",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    auth_url = f"{AUTH_BASE}/oauth/auth?{urllib.parse.urlencode(params)}"

    server = HTTPServer(("localhost", 8765), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print("\n1) Open this URL in your browser:\n")
    print(auth_url)
    print("\nWaiting for the DocuSign callback on http://localhost:8765/callback ...")
    webbrowser.open(auth_url)

    while not callback_result:
        thread.join(timeout=0.2)

    server.shutdown()

    if callback_result.get("error"):
        raise SystemExit(f"DocuSign OAuth error: {callback_result['error']}")
    if not callback_result.get("code"):
        raise SystemExit("No authorization code received.")
    if callback_result.get("state") != state:
        raise SystemExit("OAuth state mismatch; refusing the callback.")

    code = callback_result["code"]
    async def exchange() -> None:
        async with httpx2.AsyncClient(timeout=30) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                auth=(CLIENT_ID, CLIENT_SECRET),
            )
            response.raise_for_status()
            payload = response.json()
            token = payload["access_token"]
            env_path = ".env"
            lines = []
            if os.path.exists(env_path):
                lines = [line for line in open(env_path, encoding="utf-8").read().splitlines() if not line.startswith("DOCUSIGN_ACCESS_TOKEN=")]
            lines.append(f"DOCUSIGN_ACCESS_TOKEN={token}")
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print("\nSUCCESS: DocuSign OAuth access token obtained and saved to .env.")
            print("The token itself is not printed to the terminal.")
            print(f"Token prefix: {token[:12]}...\n")

    import asyncio
    asyncio.run(exchange())


if __name__ == "__main__":
    main()
