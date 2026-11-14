"""Shown before: a series cut from the same footage doesn't repeat itself (history.py)."""
from tripshots import history, planner
from tripshots.config import load_style


def _shot(i, src=None, t0=0.0, t1=4.0, kind="video", score=7.0, sig=None):
    return {"id": f"S{i:03d}", "kind": kind, "src": src or f"/x/{i}.{'mp4' if kind == 'video' else 'jpg'}",
            "sig": sig or f"g{i}", "t0": t0, "t1": t1, "w": 1920, "h": 1080, "fps": 30, "thumb": "",
            "metrics": {"pan": 0.0, "activity": 0.3},
            "ai": {"score": score, "mood": "calm", "scene": "landscape", "people": {"count": 0, "activity": ""}}}


def _plan(*rows):
    """rows: (src, in, dur, role)"""
    segs, t = [], 0.0
    for src, t_in, dur, role in rows:
        segs.append({"src": src, "in": t_in, "dur": dur, "out_start": t, "role": role, "speed": 1.0,
                     "kind": "photo" if src.endswith(".jpg") else "video"})
        t += dur
    return {"style": "x", "duration": t, "segments": segs}


def _made(tmp_path, monkeypatch, name="one.mp4", plan=None):
    monkeypatch.setattr(history, "STORE", tmp_path / "history.json")
    out = tmp_path / name
    out.write_bytes(b"x")
    history.record(plan or _plan(("/x/0.mp4", 1.0, 2.0, "hook"), ("/x/1.mp4", 0.0, 1.0, "build"),
                                 ("/x/2.jpg", 0.0, 1.0, "build"), ("/x/3.mp4", 0.0, 2.0, "ending")), out)
    return out


def test_what_a_reel_showed_counts_against_the_same_stretch_only(tmp_path, monkeypatch):
    out = _made(tmp_path, monkeypatch)
    shots = [_shot(0, t0=0.0, t1=4.0), _shot(10, src="/x/0.mp4", t0=40.0, t1=44.0, sig="far"), _shot(1),
             _shot(2, kind="photo"), _shot(3), _shot(4)]
    seen = history.shown(shots)
    assert seen["reels"] == ["one.mp4"] and seen["n"] == 4
    assert seen["shot"]["S000"] == history.LEAD and seen["shot"]["S003"] == history.LEAD     # it opened, it ended
    assert seen["shot"]["S001"] == history.BODY and seen["shot"]["S002"] == history.BODY
    assert "S004" not in seen["shot"] and "S010" not in seen["shot"]        # another clip; a later stretch of one
    style = load_style("beat-montage")
    style["_shown"] = seen
    assert history.mark_down(style, shots[0]) == 1.0 and history.mark_down(style, shots[5]) == 0.0
    style["shots"]["fresh"] = 0                                             # --fresh off
    assert history.mark_down(style, shots[0]) == 0.0
    # the reel being made again doesn't count against itself, a deleted one is forgotten
    assert history.shown(shots, skip=[out])["shot"] == {}
    out.unlink()
    assert history.shown(shots)["shot"] == {}


def test_a_render_replaces_its_earlier_note_and_more_reels_add_up(tmp_path, monkeypatch):
    out = _made(tmp_path, monkeypatch)
    history.record(_plan(("/x/1.mp4", 0.0, 1.0, "hook"), ("/x/4.mp4", 0.0, 1.0, "ending")), out)   # rendered again
    shots = [_shot(i) for i in range(6)]
    seen = history.shown(shots)
    assert set(seen["shot"]) == {"S001", "S004"} and len(history.load()) == 1
    _made(tmp_path, monkeypatch, "two.mp4", _plan(("/x/1.mp4", 0.0, 1.0, "hook"), ("/x/5.mp4", 0.0, 1.0, "ending")))
    seen = history.shown(shots, places={s["id"]: "cape" if s["id"] in ("S001", "S002") else s["id"] for s in shots})
    assert seen["shot"]["S001"] == history.CAP and seen["place"]["cape"] == 2
    style = load_style("beat-montage")
    style["_shown"] = seen
    # an opening or ending slot also avoids the stop earlier reels opened on
    assert history.mark_down(style, shots[2]) == 0.0 and abs(history.mark_down(style, shots[2], lead=True) - 0.6) < 1e-9


def test_the_next_reel_is_cut_from_other_shots(tmp_path, monkeypatch):
    shots = [_shot(i, score=9.0 - 0.2 * i) for i in range(12)]
    style = load_style("beat-montage")
    first = planner.select_shots(shots, 4, style)
    plan = _plan(*[(s["src"], 0.0, 1.0, "hook" if i == 0 else "build") for i, s in enumerate(first)])
    _made(tmp_path, monkeypatch, plan=plan)
    style["_shown"] = history.shown(shots)
    second = planner.select_shots(shots, 4, style)
    assert first[0]["id"] not in {s["id"] for s in second}                  # never the same opening again
    assert len({s["id"] for s in first} & {s["id"] for s in second}) <= 1
    style["shots"]["fresh"] = 0
    assert {s["id"] for s in planner.select_shots(shots, 4, style)} == {s["id"] for s in first}


def test_a_new_shot_carries_the_reel_only_when_it_is_about_as_good(tmp_path, monkeypatch):
    from tripshots import story
    shots = [_shot(0, score=9.0), _shot(1, score=8.4), _shot(2, score=6.5), _shot(3, score=6.4), _shot(4, score=6.0)]
    _made(tmp_path, monkeypatch, plan=_plan(("/x/0.mp4", 0.0, 1.0, "build"), ("/x/9.mp4", 0.0, 1.0, "ending")))
    style = load_style("beat-montage")
    style["loop"] = False
    style["_shown"] = history.shown(shots)
    assert history.mark_down(style, shots[0]) > 0 and not history.mark_down(style, shots[1])
    segs = [{"role": r, "out_start": float(i), "dur": 1.0} for i, r in enumerate(("hook", "release", "peak", "ending"))]
    order = story.cast(shots, segs, style)
    assert order[0]["id"] == "S001"                # nearly as good and not shown yet: it opens this reel
    shots[1]["ai"]["score"] = 6.0                  # nothing new comes close: the best opens again
    assert story.cast(shots, segs, style)[0]["id"] == "S000"


def test_the_payoff_of_a_tease_and_the_long_slots_get_the_best_shots():
    from tripshots import story
    lively = _shot(0, score=8.4)
    lively["metrics"] = {"pan": 0.02, "activity": 0.3}
    lively["ai"].update(mood="dynamic", people={"count": 2, "activity": "walking"})
    best = _shot(1, kind="photo", score=9.0)
    opener = _shot(6, score=8.0)
    opener["metrics"] = {"pan": 0.02, "activity": 0.3}
    opener["ai"].update(role="hook", people={"count": 1, "activity": "walking"})
    shots = [lively, best, opener] + [_shot(i, kind="photo", score=6.0) for i in range(2, 6)]
    style = load_style("beat-montage")
    style["loop"] = False
    style["story"]["people_first"] = False
    segs = [{"role": r, "out_start": float(i), "dur": 1.0} for i, r in enumerate(("hook", "peak", "release", "ending"))]
    assert story.cast(shots, segs, style)[1]["id"] == "S000"       # a montage peaks on the liveliest of its best
    assert story.cast(shots, segs, style, tease=True)[1]["id"] == "S001"     # a reveal pays off with its best one
    lively["ai"]["score"] = 7.2
    assert story.cast(shots, segs, style)[1]["id"] == "S001"       # lively, but not one of the best: not the turn
    # a slot that lasts three times as long doesn't show the lesser shot
    order = [None, {"id": "a", "ai": {"score": 7.0}}, {"id": "b", "ai": {"score": 8.6}}, {"id": "c", "ai": {"score": 8.5}}]
    slots = [{"role": "hook", "dur": 2.0}, {"role": "release", "dur": 1.2}, {"role": "release", "dur": 0.4},
             {"role": "build", "dur": 0.3}]
    story._long_slots_first(order, [1, 2, 3], slots)
    assert [o and o["id"] for o in order] == [None, "b", "a", "c"]            # (another part of the story stays)
