from tripshots import watch


def test_parse_clamps_and_cleans():
    raw = {"moments": [{"peak": "0:05", "start": -1, "end": 99, "score": 12, "motion": "whatever"},
                       {"start": 2, "end": 2.2}],  # too short: dropped
           "transitions": [{"start": 3.0, "end": 3.4, "type": "whip_pan"}, {"start": 4, "end": 5, "type": "teleport"}]}
    p = watch.parse(raw, duration=8.0)
    (m,) = p["moments"]
    assert (m["start"], m["peak"], m["end"], m["score"]) == (0.0, 5.0, 8.0, 10.0)
    assert m["motion"] == ""  # unknown labels are dropped
    assert [t["type"] for t in p["transitions"]] == ["whip_pan"]


def test_local_whip_inside_a_shot():
    t = [i / 4 for i in range(24)]
    jit = [0.015] * 24
    sharp = [180.0] * 24
    jit[12], jit[13] = 0.12, 0.5  # the swing
    sharp[12] = 110.0
    shot = {"id": "S1", "kind": "video", "sig": "a", "t0": 0, "t1": 6, "samples": {"t": t, "jitter": jit, "sharp": sharp}}
    w = watch.local_whips([shot])
    assert w and 3.0 <= (w["a"][0]["start"] + w["a"][0]["end"]) / 2 <= 3.3


def test_apply_blends_gemini(monkeypatch):
    shot = {"id": "S1", "kind": "video", "sig": "a", "t0": 0, "t1": 6, "ai": {"score": 6.0, "tags": []},
            "samples": {"t": [], "jitter": [], "sharp": []}}
    log = {"a": {"moments": [{"start": 1, "end": 3, "peak": 2, "score": 9, "motion": "static", "framing": "level",
                              "stability": "steady", "exposure": "good", "audio": "ambient", "energy": "medium",
                              "subject": "waves"}], "transitions": [], "tags": ["sea"]}}
    assert watch.apply([shot], log) >= 1
    assert shot["ai"]["watch"]["peak"] == 2 and shot["ai"]["score"] > 6.0
