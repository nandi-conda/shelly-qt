import base64
import json

from shelly_qt import protocol


def enc(obj):
    return "[JSON]" + base64.b64encode(json.dumps(obj).encode()).decode() + "[/JSON]"


def test_roundtrip_answer_frame():
    raw = protocol.encode_frame(protocol.answer_transaction("q1", True)).decode()
    assert raw.endswith("\n")
    assert list(protocol.iter_frames(raw)) == [{"$kind": "a.transaction", "QuestionId": "q1", "Accept": True}]


def test_last_data_skips_event_frames():
    out = enc({"$kind": "alpm.info", "Message": "hi"}) + "noise" + enc([1]) + enc([2]) + enc({"$kind": "x"})
    assert protocol.last_data(out) == [2]


def test_incremental_parser_handles_split_chunks():
    text = enc({"a": 1}) + enc({"b": 2})
    p = protocol.FrameParser()
    got = []
    for i in range(0, len(text), 5):
        got += p.feed(text[i:i + 5])
    assert got == [{"a": 1}, {"b": 2}]


def test_failure_message_only_fatal_unique():
    out = (enc({"$kind": "alpm.error", "ErrorMessage": "warn", "Level": "Warning"})
           + enc({"$kind": "alpm.error", "ErrorMessage": "boom", "Level": "Error"})
           + enc({"$kind": "alpm.error", "ErrorMessage": "boom", "Level": "Error"})
           + enc({"$kind": "alpm.error", "ErrorMessage": "soft", "Recoverable": True}))
    assert protocol.failure_message(out) == "boom"


def test_human_size():
    assert protocol.human_size(512) == "512 B"
    assert protocol.human_size(1536) == "1.50 KiB"
    assert protocol.human_size(-1048576) == "-1.00 MiB"
