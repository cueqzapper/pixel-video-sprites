"""Minimal ComfyUI HTTP client and workflow-template filler (standard library only).

Template format = normal ComfyUI *API* workflow JSON plus a "_template" key:

    {
      "_template": {"description": "...", "params": {"prompt": {"default": "..."}, "seed": {"default": 1}}},
      "3": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}", ...}},
      ...
    }

* A string that is exactly "{{name}}" is replaced by the typed value (int/float/str/list).
* "{{name}}" inside a longer string is replaced textually.
* Keys starting with "_" are removed before the workflow is queued.
* Image parameters: a value "@path/to/file.png" is uploaded first and replaced by the server-side name.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")


def _auth_header() -> dict:
    """Optional auth for a ComfyUI behind a reverse proxy: env COMFY_AUTH = 'Bearer <token>', 'Basic <b64>' or 'user:password'."""
    val = os.environ.get("COMFY_AUTH", "").strip()
    if not val:
        return {}
    if not val.lower().startswith(("bearer ", "basic ")):
        val = "Basic " + base64.b64encode(val.encode()).decode()
    return {"Authorization": val}


class ComfyClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 120.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex
        # an explicit User-Agent: Cloudflare-proxied servers reject the default "Python-urllib" agent (error 1010)
        self.headers = {"User-Agent": "pixel-video-sprites/0.1", **_auth_header()}

    # -- HTTP -----------------------------------------------------------------------------------------------------
    def _request(self, path: str, data: bytes | None = None, headers: dict | None = None, raw: bool = False, retries: int = 5):
        for attempt in range(retries):
            req = urllib.request.Request(self.url + path, data=data, headers={**self.headers, **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read()
                return body if raw else (json.loads(body) if body else {})
            except urllib.error.HTTPError as e:
                msg = e.read()[:4000].decode("utf-8", "replace")
                if e.code < 500 or attempt == retries - 1:
                    raise RuntimeError(f"{path} -> HTTP {e.code}: {msg}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == retries - 1:
                    raise
            time.sleep(min(30, 2 * 2 ** attempt))

    def get(self, path: str, raw: bool = False):
        return self._request(path, raw=raw)

    def post_json(self, path: str, payload):
        return self._request(path, json.dumps(payload).encode(), {"Content-Type": "application/json"})

    # -- server info ----------------------------------------------------------------------------------------------
    def stats(self):
        return self.get("/system_stats")

    def queue(self):
        return self.get("/queue")

    def free(self):
        """Unload models / free VRAM (be nice on a shared GPU)."""
        return self.post_json("/free", {"unload_models": True, "free_memory": True})

    def node_types(self) -> set[str]:
        return set(self.get("/object_info").keys())

    def models(self, folder: str) -> list[str] | None:
        """Files in a model folder (ComfyUI >= 0.3 exposes GET /models/<folder>); None if the endpoint is missing."""
        try:
            return self.get(f"/models/{folder}")
        except Exception:  # noqa: BLE001
            return None

    # -- upload / run ---------------------------------------------------------------------------------------------
    def upload_image(self, path: str | Path, subfolder: str = "pvs") -> str:
        """Upload an image (content-addressed name, so identical inputs are stored once). Returns the LoadImage name."""
        path = Path(path)
        data = path.read_bytes()
        name = hashlib.sha1(data).hexdigest()[:16] + path.suffix.lower()
        boundary = uuid.uuid4().hex
        parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                 for k, v in (("subfolder", subfolder), ("type", "input"), ("overwrite", "true"))]
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
                     f"Content-Type: image/png\r\n\r\n".encode() + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        info = self._request("/upload/image", b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        sub = info.get("subfolder") or ""
        return f"{sub}/{info['name']}" if sub else info["name"]

    def submit(self, workflow: dict) -> str:
        res = self.post_json("/prompt", {"prompt": workflow, "client_id": self.client_id})
        if res.get("node_errors"):
            raise RuntimeError("node errors: " + json.dumps(res["node_errors"], indent=1)[:4000])
        return res["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 3600.0, poll: float = 1.0, verbose: bool = True) -> dict:
        t0, last = time.time(), ""
        while True:
            hist = self.get(f"/history/{prompt_id}")
            if prompt_id in hist:
                entry = hist[prompt_id]
                st = entry.get("status", {})
                if st.get("status_str") == "error":
                    msgs = [m[1] for m in st.get("messages", []) if m[0] == "execution_error"]
                    d = msgs[0] if msgs else st
                    if isinstance(d, dict):
                        d = {k: d.get(k) for k in ("node_type", "node_id", "exception_message")}
                    raise RuntimeError(f"execution error: {d}")
                if st.get("completed") or st.get("status_str") == "success":
                    return entry
            if time.time() - t0 > timeout:
                raise TimeoutError(f"{prompt_id} not finished after {timeout:.0f} s")
            if verbose:
                q = self.queue()
                pos = "running" if any(i[1] == prompt_id for i in q.get("queue_running", [])) else \
                    f"queued ({len(q.get('queue_pending', []))} pending)"
                if pos != last:
                    print(f"  [{prompt_id[:8]}] {pos}", file=sys.stderr)
                    last = pos
            time.sleep(poll)

    @staticmethod
    def exec_seconds(entry: dict) -> float | None:
        ts = {n: d["timestamp"] for n, d in entry.get("status", {}).get("messages", []) if isinstance(d, dict) and "timestamp" in d}
        end = ts.get("execution_success", ts.get("execution_error"))
        return (end - ts["execution_start"]) / 1000.0 if "execution_start" in ts and end else None

    def download_outputs(self, entry: dict, dest: Path) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        files = []
        for node_id, out in entry.get("outputs", {}).items():
            for img in out.get("images", []):
                if img.get("type") == "temp":
                    continue
                q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                            "type": img.get("type", "output")})
                p = dest / f"{node_id}_{img['filename']}"
                p.write_bytes(self.get("/view?" + q, raw=True))
                files.append(p)
        return files


# ------------------------------------------------------------------------------------------------- templates
PH = re.compile(r"\{\{(\w+)\}\}")


def load_template(path: str | Path) -> tuple[dict, dict]:
    tpl = json.loads(Path(path).read_text(encoding="utf-8"))
    defaults = {k: (v.get("default") if isinstance(v, dict) else v) for k, v in tpl.get("_template", {}).get("params", {}).items()}
    return tpl, defaults


def fill(obj, params: dict):
    if isinstance(obj, dict):
        return {k: fill(v, params) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [fill(v, params) for v in obj]
    if isinstance(obj, str):
        m = PH.fullmatch(obj)
        if m:
            if m.group(1) not in params:
                raise KeyError(f"missing template parameter: {m.group(1)}")
            return params[m.group(1)]
        return PH.sub(lambda mm: str(params[mm.group(1)]), obj)
    return obj


def run(template: str | Path, params: dict, out_dir: str | Path, client: ComfyClient, verbose: bool = True) -> dict:
    """Fill a template, upload '@file' images, queue it, wait, download all saved images to out_dir."""
    tpl, p = load_template(template)
    p.update(params)
    for k, v in list(p.items()):
        if isinstance(v, str) and v.startswith("@"):
            p[k] = client.upload_image(v[1:])
    wf = fill(tpl, p)
    t0 = time.time()
    pid = client.submit(wf)
    try:
        entry = client.wait(pid, verbose=verbose)
    except RuntimeError as e:  # shared GPU: unload models once and retry on OOM
        if "out of memory" not in str(e).lower():
            raise
        client.free()
        time.sleep(3)
        pid = client.submit(wf)
        entry = client.wait(pid, verbose=verbose)
    files = client.download_outputs(entry, Path(out_dir))
    return {"prompt_id": pid, "wall_s": round(time.time() - t0, 1), "exec_s": client.exec_seconds(entry),
            "out_files": [str(f) for f in files]}
