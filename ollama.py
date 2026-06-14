"""ollama.py — minimal local Ollama JSON client (urllib only, no SDK).

Adapted from ../daily-lookback/coach.py: forces JSON output, strips accidental
``` fences, salvages an object embedded in prose, and retries a few times.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request

from config import (
    DEFAULT_MODEL,
    OLLAMA_MAX_RETRIES,
    OLLAMA_NUM_CTX,
    OLLAMA_READY_TIMEOUT,
    OLLAMA_TAGS_URL,
    OLLAMA_URL,
)


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


# The `ollama serve` process THIS run started (None = server was already up,
# i.e. the user runs it themselves — we must not touch that one).
# Mirrors ../daily-lookback/coach.py so both projects manage Ollama the same way.
_managed_ollama: subprocess.Popen | None = None


def wait_for_ollama(timeout: int = OLLAMA_READY_TIMEOUT) -> None:
    """Make Ollama available for this run, starting a managed instance if needed.

    Ollama should NOT sit resident eating RAM all day: if the server is already
    up (the user started it themselves), use it and leave it alone afterward. If
    it's down, start it as a tracked child process — never detached, so
    shutdown_ollama() can stop it when the run finishes.
    """
    global _managed_ollama
    if ollama_up():
        return
    print("Ollama not running — starting a managed instance for this run…")
    try:
        _managed_ollama = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("`ollama` binary not on PATH; will keep polling in case it's booting.")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ollama_up():
            print("Ollama is up.")
            time.sleep(2)
            return
        time.sleep(3)
    shutdown_ollama()
    raise SystemExit(
        f"Ollama did not become ready within {timeout}s at {OLLAMA_URL}. "
        "Run `ollama serve` and try again."
    )


def shutdown_ollama() -> None:
    """Stop the Ollama instance this run started; free the RAM.

    A user-started server (_managed_ollama is None) is left untouched.
    """
    global _managed_ollama
    if _managed_ollama is None:
        return
    print("Stopping managed Ollama (freeing RAM)…")
    _managed_ollama.terminate()
    try:
        _managed_ollama.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _managed_ollama.kill()
        _managed_ollama.wait(timeout=5)
    _managed_ollama = None


def _parse(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def generate_json(
    prompt: str,
    system: str,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    num_ctx: int = OLLAMA_NUM_CTX,
) -> dict:
    """Call Ollama and return a parsed JSON object.

    Raises RuntimeError if Ollama is unreachable or never returns valid JSON.
    Low default temperature — receipt parsing wants determinism, not creativity.
    """
    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    last_err: Exception | None = None
    for attempt in range(1, OLLAMA_MAX_RETRIES + 1):
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read())
        except urllib.error.URLError as e:
            last_err = e
            print(f"Ollama call failed (attempt {attempt}/{OLLAMA_MAX_RETRIES}): {e}")
            continue
        parsed = _parse(body.get("response", ""))
        if isinstance(parsed, dict):
            return parsed
        print(f"Ollama returned non-JSON (attempt {attempt}/{OLLAMA_MAX_RETRIES}) — retrying…")

    raise RuntimeError(
        f"Could not get valid JSON from Ollama at {OLLAMA_URL}: {last_err}\n"
        "Is `ollama serve` running and the model pulled?"
    )
