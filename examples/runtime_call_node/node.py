"""Generic Runtime Call node. Uses only the Python standard library."""

import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def execute(self, input_data):
    config = self.config or {}
    runtime_id = input_data.get("runtime_id", config.get("runtime_id", ""))
    action = input_data.get("action", config.get("action", ""))
    params = input_data.get("params", config.get("params", {}))
    base_url = input_data.get(
        "runtime_url",
        config.get("runtime_url")
        or os.environ.get("MOZIKIT_RUNTIME_URL", "http://127.0.0.1:48765"),
    ).rstrip("/")

    if not runtime_id or not action:
        raise ValueError("runtime_id and action are required")
    if not isinstance(params, dict):
        raise TypeError("params must be an object")

    url = f"{base_url}/runtime/{quote(runtime_id, safe='')}/call"
    payload = json.dumps({"action": action, "params": params}).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"runtime call failed ({exc.code}): {detail}") from exc
