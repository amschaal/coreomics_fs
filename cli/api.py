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
from typing import Any, Dict, Optional


def load_config(path: Optional[Path] = None) -> Dict[str, str]:
    """Load configuration from `config.yaml` in the repo root by default.

    Expected keys: `api_base_url`, `api_key`.
    """
    import yaml

    cfg_path = Path(path or "../config.yaml")
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    if "api_base_url" not in cfg or "api_key" not in cfg:
        raise KeyError("config.yaml must define 'api_base_url' and 'api_key'")

    return cfg


class ApiClient:
    """Minimal API client using urllib.

    Example:
        cfg = load_config()
        api = ApiClient(cfg["api_base_url"], cfg["api_key"])
        api.get("/server/api/submissions/", params={"page": 1})
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

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, data: Optional[Any] = None, headers: Optional[Dict[str, str]] = None) -> Any:
        url = self._build_url(path, params)
        body = None
        hdrs = {"Authorization": f"Token {self.api_key}", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)

        if data is not None:
            body = json.dumps(data).encode("utf-8")
            hdrs["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, data: Any = None, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", path, params=params, data=data)

    def put(self, path: str, data: Any = None, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("PUT", path, params=params, data=data)

    def delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("DELETE", path, params=params)


class SubmissionAPI:
    """Helpers for submission-related endpoints.

    These are thin wrappers around `ApiClient` to keep CLI code tidy and
    make adding new endpoints straightforward.
    """

    def __init__(self, client: ApiClient):
        self.client = client

    def get_submission(self, submission_id: str) -> Dict[str, Any]:
        return self.client.get(f"/server/api/submissions/{submission_id}/")

    def list_submissions(self, query_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.client.get("/server/api/submissions/", params=query_params)


__all__ = ["load_config", "ApiClient", "SubmissionAPI"]

