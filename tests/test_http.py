import threading

import httpx

from weather_vs_market import http


def test_pacer_spaces_requests_across_threads(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(http.time, "monotonic", lambda: clock["t"])
    slept = []
    monkeypatch.setattr(http.time, "sleep", lambda s: slept.append(round(s, 3)))
    pacer = http.Pacer(0.2)
    threads = [threading.Thread(target=pacer.wait) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(slept) == [0.2, 0.4, 0.6]       # four calls at one instant get distinct slots


def test_get_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    replies = iter([httpx.Response(429), httpx.Response(200, json={"ok": True})])
    with httpx.Client(transport=httpx.MockTransport(lambda req: next(replies))) as c:
        assert http.get(c, "https://example.test").json() == {"ok": True}
