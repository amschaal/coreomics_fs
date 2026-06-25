"""API helpers for the CLI.

This module provides a small `ApiClient` that loads `config.yaml` (must
contain `api_base_url` and `api_key`) and convenience helpers for adding
endpoints. It uses the standard library so no extra dependencies are
required.
"""

from pathlib import Path
import json
import urllib.parse
import urllib.request
import urllib.error
from typing import Any, Dict, Optional
from ..config import load_config


# Short, human-readable hints keyed by HTTP status. These explain the most
# common cause for each status against this API so the CLI message points the
# user at a fix instead of a bare "HTTP Error 403: Forbidden".
_STATUS_HINTS = {
    400: "the request was malformed (check query parameters / payload)",
    401: "the API token is missing or invalid (check [api] api_key in config)",
    403: "the API token is valid but not authorized for this resource "
         "(check [api] api_key and that the token's account may access this lab)",
    404: "the URL or resource was not found "
         "(check [api] api_base_url and any submission / lab id)",
    429: "rate limited by the server; retry after a short wait",
    500: "the server hit an internal error; retry later or contact the API admin",
    502: "bad gateway; the API server may be down or restarting",
    503: "the API service is unavailable; retry later",
}


def _extract_detail(body: Optional[str]) -> Optional[str]:
    """Pull a human-readable message out of an error response body.

    Django REST Framework errors are usually JSON like ``{"detail": "..."}`` or
    field-keyed lists; fall back to a trimmed snippet of the raw body otherwise.
    """
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        text = body.strip()
        return text[:500] if text else None
    if isinstance(parsed, dict):
        for key in ("detail", "error", "message", "non_field_errors"):
            val = parsed.get(key)
            if val:
                return val if isinstance(val, str) else json.dumps(val)
        return json.dumps(parsed)[:500]
    if isinstance(parsed, (list, tuple)):
        return json.dumps(list(parsed))[:500]
    return str(parsed)[:500]


class ApiError(Exception):
    """An API request failed.

    Carries the structured pieces (``status``, ``reason``, ``url``, ``body``,
    ``detail``) so callers can render JSON, while ``str(err)`` is a complete,
    human-readable message including the server's reason and a fix hint.
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        reason: Optional[str] = None,
        url: Optional[str] = None,
        body: Optional[str] = None,
        detail: Optional[str] = None,
    ):
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.url = url
        self.body = body
        self.detail = detail

    @classmethod
    def from_http_error(cls, exc: "urllib.error.HTTPError", url: str) -> "ApiError":
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        detail = _extract_detail(body)
        hint = _STATUS_HINTS.get(exc.code)
        parts = [f"HTTP {exc.code} {exc.reason} for {url}"]
        if detail:
            parts.append(f"server said: {detail}")
        if hint:
            parts.append(f"hint: {hint}")
        return cls(
            "; ".join(parts),
            status=exc.code,
            reason=str(exc.reason),
            url=url,
            body=body,
            detail=detail,
        )

    @classmethod
    def from_url_error(cls, exc: "urllib.error.URLError", url: str) -> "ApiError":
        reason = getattr(exc, "reason", exc)
        return cls(
            f"Could not reach the API at {url}: {reason} "
            f"(hint: check [api] api_base_url and network connectivity)",
            reason=str(reason),
            url=url,
        )

# def load_config(path: Optional[Path] = None) -> Dict[str, str]:
#     """Load configuration from `config.yaml` in the repo root by default.

#     Expected keys: `api_base_url`, `api_key`.
#     """
#     import yaml
    
#     if path:
#         cfg_path = Path(path or "../config.yaml")
#     else:
#         BASE_DIR = Path(__file__).resolve().parent
#         cfg_path = BASE_DIR.parent / "config.yaml"

#     if not cfg_path.is_file():
#         raise FileNotFoundError(f"Config file not found: {cfg_path}")

#     with cfg_path.open("r", encoding="utf-8") as fh:
#         cfg = yaml.safe_load(fh) or {}

#     if "api_base_url" not in cfg or "api_key" not in cfg:
#         raise KeyError("config.yaml must define 'api_base_url' and 'api_key'")

#     return cfg


class ApiClient:
    """Minimal API client using urllib.

    Example:
        cfg = load_config()
        api = ApiClient(cfg["api_base_url"], cfg["api_key"])
        api.get("/api/submissions/", params={"page": 1})
    """

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        path = path.lstrip("/")
        url = f"https://{self.base_url}/{path}" if not self.base_url.startswith("http") else f"{self.base_url.rstrip('/')}/{path}"
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}?{query}"
        return url

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, data: Optional[Any] = None, headers: Optional[Dict[str, str]] = None, raw: bool = False) -> Any:
        url = self._build_url(path, params)
        body = None
        hdrs = {"Authorization": f"Token {self.api_key}", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)

        if data is not None:
            body = json.dumps(data).encode("utf-8")
            hdrs["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
        try:
            with urllib.request.urlopen(req) as resp:
                raw_resp = resp.read()
        except urllib.error.HTTPError as e:
            raise ApiError.from_http_error(e, url) from None
        except urllib.error.URLError as e:
            raise ApiError.from_url_error(e, url) from None
        if not raw_resp:
            return None
        if raw:
            return raw_resp.decode("utf-8")
        return json.loads(raw_resp.decode("utf-8"))
                

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, raw: bool = False) -> Any:
        return self._request("GET", path, params=params, raw=raw)

    def post(self, path: str, data: Any = None, params: Optional[Dict[str, Any]] = None, raw: bool = False) -> Any:
        return self._request("POST", path, params=params, data=data, raw=raw)

    def put(self, path: str, data: Any = None, params: Optional[Dict[str, Any]] = None, raw: bool = False) -> Any:
        return self._request("PUT", path, params=params, data=data, raw=raw)

    def delete(self, path: str, params: Optional[Dict[str, Any]] = None, raw: bool = False) -> Any:
        return self._request("DELETE", path, params=params, raw=raw)


class SubmissionAPI:
    """Helpers for submission-related endpoints.

    These are thin wrappers around `ApiClient` to keep CLI code tidy and
    make adding new endpoints straightforward.
    """
    @staticmethod
    def create():
        cfg = load_config()
        api = ApiClient(cfg["api"]["api_base_url"], cfg["api"]["api_key"])
        return SubmissionAPI(api)

    def __init__(self, client: ApiClient):
        self.client = client

    def get_submission(self, submission_id: str, raw: bool = False) -> Dict[str, Any] | str:
        return self.client.get(f"/api/submissions/{submission_id}/", raw=raw)

    def list_submissions(self, query_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.client.get("/api/submissions/", params=query_params)
    
    def list_submission_shares(self, submission_id: str) -> list:
        """GET all shares for a submission, paginating through `results`."""
        results: list = []
        path = f"/api/plugins/bioshare/submissions/{submission_id}/submission_shares/"
        while path:
            resp = self.client.get(path)
            results.extend(resp.get("results") or [])
            next_url = resp.get("next")
            if not next_url:
                break
            parsed = urllib.parse.urlparse(next_url)
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return results

    def list_all_shares(self, lab_id: str) -> list:
        """GET all shares across submissions for a lab, paginating through `results`."""
        if not lab_id:
            raise ValueError("lab_id is required")
        results: list = []
        path = "/api/plugins/bioshare/shares/"
        params: Optional[Dict[str, Any]] = {"lab_id": lab_id}
        while path:
            resp = self.client.get(path, params=params)
            results.extend(resp.get("results") or [])
            next_url = resp.get("next")
            if not next_url:
                break
            parsed = urllib.parse.urlparse(next_url)
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            params = None  # next URL already includes the query string
        return results

    def create_submission_share(self, submission_id: str, name: str, notes: str, link_to_path: str) -> Dict[str, Any]:
        payload = {
            "submission": submission_id,
            "name": name,
            "notes": notes,
            "link_to_path": link_to_path,
        }
        return self.client.post(
            f"/api/plugins/bioshare/submissions/{submission_id}/submission_shares/",
            data=payload,
        )

    def download(self, submission_id: str, format: str = 'tsv') -> bytes:
        if format == 'json':
            submission = self.get_submission(submission_id)
            return json.dumps(submission, indent=2).encode('utf-8')
        elif format == 'xlsx':
            url = self.client._build_url(f"/api/submissions/{submission_id}/download/?format=xlsx&data=all")
        else:
            url = self.client._build_url(f"/api/submissions/{submission_id}/download/?format={format}&data=submission")
        req = urllib.request.Request(url, headers={"Authorization": f"Token {self.client.api_key}"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise ApiError.from_http_error(e, url) from None
        except urllib.error.URLError as e:
            raise ApiError.from_url_error(e, url) from None
__all__ = ["load_config", "ApiClient", "SubmissionAPI", "ApiError"]

