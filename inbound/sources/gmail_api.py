"""Read-only Gmail source: the one networking exception (SPEC §13, Amendment 3a).

Scope is exactly gmail.readonly. Requests may only reach Google's OAuth token endpoint
(POST) and the Gmail API (GET). The token lives under the private data root, never in
the repository, and is never logged. Uzair opens the consent URL himself.
"""

import base64
import hashlib
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from inbound.sources.base import SourceError, provenance
from inbound.sources.eml_dir import parse_bytes

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
ALLOWED = {("POST", "oauth2.googleapis.com"), ("GET", "gmail.googleapis.com")}
MAX_RAW_BYTES = 25 * 1024 * 1024


class GmailError(RuntimeError):
    pass


class TooLarge(GmailError):
    """One message over the size cap; sync skips it instead of stopping."""


def gmail_dir(settings):
    return Path(settings.data_root) / "gmail"


def token_path(settings):
    return gmail_dir(settings) / "token.json"


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temporary name: two writers (poller and "Check now") never share one.
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def load_client_secret(path, settings):
    path = Path(path).resolve()
    if not path.is_relative_to(Path(settings.data_root).resolve()):
        raise GmailError("Client secret must be saved under the private data root")
    data = read_json(path) or {}
    client = data.get("installed")
    if not client or not client.get("client_id") or not client.get("client_secret"):
        raise GmailError("Expected a Desktop OAuth client JSON ('installed')")
    return {"client_id": client["client_id"], "client_secret": client["client_secret"]}


def error_reason(response):
    """Google's short machine reason (e.g. rateLimitExceeded); never message content."""
    try:
        error = response.json().get("error", {})
        reasons = [e.get("reason", "") for e in error.get("errors", [])]
        return ",".join(r for r in reasons if r) or str(error.get("status", ""))
    except ValueError:
        return ""


def rate_limited(response):
    return response.status_code == 403 and "ratelimitexceeded" in error_reason(response).lower()


class GmailClient:
    """Minimal REST client. `transport` lets tests use httpx.MockTransport (no sockets)."""

    def __init__(self, token, *, transport=None, on_refresh=None, before_request=None):
        self.token = dict(token)
        self.on_refresh = on_refresh
        self.before_request = before_request
        self.http = httpx.Client(transport=transport, timeout=30.0, follow_redirects=False)

    def close(self):
        self.http.close()

    def _send(self, method, url, **kwargs):
        host = urlsplit(url).hostname
        if (method, host) not in ALLOWED or urlsplit(url).scheme != "https":
            raise GmailError(f"Blocked request: {method} {host}")
        for attempt in range(6):
            if self.before_request:
                self.before_request()  # Pause is rechecked before every request and retry
            response = self.http.request(method, url, **kwargs)
            retry = response.status_code in {429, 500, 502, 503, 504} or rate_limited(response)
            if retry and attempt < 5:
                time.sleep(min(2 ** (attempt + 1), 32))
                continue
            return response
        return response

    def _access_token(self):
        if self.token.get("access_token") and self.token.get("expires_at", 0) > time.time() + 60:
            return self.token["access_token"]
        response = self._send("POST", TOKEN_URL, data={
            "client_id": self.token["client_id"],
            "client_secret": self.token["client_secret"],
            "refresh_token": self.token["refresh_token"],
            "grant_type": "refresh_token",
        })
        if response.status_code != 200:
            raise GmailError(f"Token refresh failed ({response.status_code}); reconnect Gmail")
        value = response.json()
        if value.get("scope", SCOPE).split() != [SCOPE]:
            raise GmailError("Token scope is not exactly gmail.readonly; reconnect Gmail")
        self.token["access_token"] = value["access_token"]
        self.token["expires_at"] = time.time() + int(value.get("expires_in", 3600))
        if self.on_refresh:
            self.on_refresh(self.token)
        return self.token["access_token"]

    def get(self, path, **params):
        response = self._send(
            "GET", f"{API}/{path}", params=params,
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )
        if response.status_code == 404:
            raise FileNotFoundError(path)
        if response.status_code != 200:
            raise GmailError(f"Gmail API {response.status_code} {error_reason(response)}".strip())
        return response.json()

    def profile(self):
        return self.get("profile")

    def list_ids(self, query, limit):
        ids, page = [], None
        while len(ids) < limit:
            params = {"q": query, "maxResults": min(100, limit - len(ids))}
            if page:
                params["pageToken"] = page
            value = self.get("messages", **params)
            ids += [m["id"] for m in value.get("messages", [])]
            page = value.get("nextPageToken")
            if not page:
                break
        return ids[:limit]

    def history_ids(self, start, max_pages=100):
        """Every message id added since `start` (all pages: none may be skipped, because the
        cursor then moves past them). FileNotFoundError when the history id has expired."""
        ids, page = [], None
        for _ in range(max_pages):
            params = {"startHistoryId": start, "historyTypes": "messageAdded", "maxResults": 500}
            if page:
                params["pageToken"] = page
            value = self.get("history", **params)
            for item in value.get("history", []):
                for added in item.get("messagesAdded", []):
                    if added["message"]["id"] not in ids:
                        ids.append(added["message"]["id"])
            page = value.get("nextPageToken")
            if not page:
                return ids
        raise FileNotFoundError("history too long; relist")  # fall back to a bounded listing

    def raw(self, message_id):
        value = self.get(f"messages/{message_id}", format="raw")
        data = base64.urlsafe_b64decode(value["raw"] + "=" * (-len(value["raw"]) % 4))
        if len(data) > MAX_RAW_BYTES:
            raise TooLarge("Message larger than the 25 MB cap")
        return data, {
            "id": value["id"],
            "threadId": value.get("threadId", value["id"]),
            "labelIds": value.get("labelIds", []),
            "historyId": value.get("historyId"),
        }


def consent_url(client_id, redirect_uri, state, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge.decode(),
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    })


def wait_for_code(server, state, timeout=600):
    """Serve exactly one loopback redirect and return its authorization code."""
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            ok = query.get("state", [""])[0] == state and "code" in query
            if ok:
                result["code"] = query["code"][0]
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"Inbound received read-only Gmail access. You can close this tab."
                if ok else b"Inbound did not accept this response."
            )

        def log_message(self, *args):
            return

    server.RequestHandlerClass = Handler
    server.timeout = timeout
    server.handle_request()
    if "code" not in result:
        raise GmailError("No authorization code received")
    return result["code"]


def connect_account(settings, client_secret_path, *, transport=None, announce=print):
    client = load_client_secret(client_secret_path, settings)
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    announce("Open this URL in your browser and allow read-only Gmail access:")
    announce(consent_url(client["client_id"], redirect, state, verifier))
    try:
        code = wait_for_code(server, state)
    finally:
        server.server_close()
    with httpx.Client(transport=transport, timeout=30.0) as http:
        if ("POST", urlsplit(TOKEN_URL).hostname) not in ALLOWED:
            raise GmailError("Blocked token endpoint")
        response = http.post(TOKEN_URL, data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        })
    if response.status_code != 200:
        raise GmailError(f"Token exchange failed ({response.status_code})")
    value = response.json()
    if value.get("scope", SCOPE).split() != [SCOPE]:
        raise GmailError("Google granted a different scope; only gmail.readonly is accepted")
    if not value.get("refresh_token"):
        raise GmailError("No refresh token returned; remove Inbound's access and retry")
    token = {
        **client,
        "refresh_token": value["refresh_token"],
        "access_token": value["access_token"],
        "expires_at": time.time() + int(value.get("expires_in", 3600)),
    }
    gmail = GmailClient(token, transport=transport)
    try:
        token["email"] = gmail.profile().get("emailAddress", "")
    finally:
        gmail.close()
    write_json(token_path(settings), token)
    return token["email"]


def disconnect(settings):
    path = token_path(settings)
    if path.exists():
        path.unlink()


def load(root, source):
    """Import loader for messages Gmail sync saved as <id>.eml + <id>.json under `root`."""
    provenance(source)
    root = Path(root)
    for meta_path in sorted(root.glob("*.json")):
        meta = read_json(meta_path)
        data = (root / f"{meta['id']}.eml").read_bytes()
        try:
            yield parse_bytes(
                data, root, source,
                identity=meta["id"], thread_id=meta["threadId"],
                labels=", ".join(meta.get("labelIds", [])), keep_oversized=True,
            )
        except SourceError as exc:
            # One unparseable message (no date, unsafe name) must not stop every later
            # sync: it stays on disk, is marked once, and is not retried on every check.
            (root / f"{meta['id']}.rejected").write_text(str(exc)[:80], encoding="utf-8")
            continue
