"""Shelly CLI ``--ui-mode`` wire protocol.

The CLI writes frames of the form ``[JSON]<base64 json>[/JSON]`` to stdout.
Event frames carry a ``$kind`` key (``alpm.info``, ``alpm.progress``,
``q.transaction`` ...).  Data frames (query results) have no ``$kind``.
Answers to questions are written back to stdin in the same framing.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Iterator

PREFIX = "[JSON]"
SUFFIX = "[/JSON]"


def encode_frame(obj: Any) -> bytes:
    payload = base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()
    return f"{PREFIX}{payload}{SUFFIX}\n".encode()


def decode_payload(payload: str) -> Any | None:
    try:
        return json.loads(base64.b64decode(payload.strip(), validate=True))
    except Exception:
        return None


def iter_frames(text: str) -> Iterator[Any]:
    """Yield every decodable frame in a complete output buffer."""
    pos = 0
    while True:
        start = text.find(PREFIX, pos)
        if start < 0:
            return
        start += len(PREFIX)
        end = text.find(SUFFIX, start)
        if end < 0:
            return
        pos = end + len(SUFFIX)
        obj = decode_payload(text[start:end])
        if obj is not None:
            yield obj


class FrameParser:
    """Incremental parser for streamed stdout."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> list[Any]:
        self._buf += chunk
        out: list[Any] = []
        while True:
            start = self._buf.find(PREFIX)
            if start < 0:
                # keep a possible partial prefix at the tail
                self._buf = self._buf[-len(PREFIX):]
                break
            end = self._buf.find(SUFFIX, start + len(PREFIX))
            if end < 0:
                self._buf = self._buf[start:]
                break
            obj = decode_payload(self._buf[start + len(PREFIX):end])
            if obj is not None:
                out.append(obj)
            self._buf = self._buf[end + len(SUFFIX):]
        return out


def kind(obj: Any) -> str:
    return obj.get("$kind", "") if isinstance(obj, dict) else ""


def data_frames(text: str) -> list[Any]:
    return [f for f in iter_frames(text) if not kind(f)]


def last_data(text: str, default: Any = None) -> Any:
    frames = data_frames(text)
    return frames[-1] if frames else default


def failure_message(text: str) -> str | None:
    seen: list[str] = []
    for f in iter_frames(text):
        if (
            kind(f) == "alpm.error"
            and f.get("Level", "Error") == "Error"
            and not f.get("Recoverable", False)
            and f.get("ErrorMessage")
            and f["ErrorMessage"] not in seen
        ):
            seen.append(f["ErrorMessage"])
    return "\n\n".join(seen) or None


# ---- answers -------------------------------------------------------------

def answer_yesno(qid: str, accept: bool) -> dict:
    return {"$kind": "a.yesno", "QuestionId": qid, "Accept": accept}


def answer_transaction(qid: str, accept: bool) -> dict:
    return {"$kind": "a.transaction", "QuestionId": qid, "Accept": accept}


def answer_optdeps(qid: str, indices: list[int]) -> dict:
    return {"$kind": "a.optdeps", "QuestionId": qid, "SelectedIndices": list(indices)}


def answer_provider(qid: str, index: int) -> dict:
    return {"$kind": "a.provider", "QuestionId": qid, "SelectedIndex": index}


def answer_pkgbuild(qid: str, proceed: bool) -> dict:
    return {"$kind": "a.pkgbuilddiff", "QuestionId": qid, "ProceedWithUpdate": proceed}


QUESTION_KINDS = {"q.yesno", "q.transaction", "q.optdeps", "q.provider", "q.pkgbuilddiff"}


def human_size(n: int | float | None) -> str:
    if n is None:
        return ""
    n = float(n)
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{sign}{n:.0f} {unit}" if unit == "B" else f"{sign}{n:.2f} {unit}"
        n /= 1024
    return ""
