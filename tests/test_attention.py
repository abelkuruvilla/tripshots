"""A learned style's attention profile: measured from its references, followed by the rhythm, casting and critic."""
import statistics

from tripshots import critic, learn, story
from tripshots.config import load_style

FAST = {"duration": 11.6, "shot_lens": [1.2, 0.8, 0.8, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 2.0, 0.8, 0.4, 0.4, 0.8, 1.2],
        "loop_likeness": 0.99}
SLOW = {"duration": 20.0, "shot_lens": [2.4, 2.6, 2.4, 2.6, 3.4, 2.2, 2.4, 2.0], "loop_likeness": 0.6}


def _grid(bl=0.5, n=90):
    beats = [round(i * bl, 3) for i in range(n)]
    return {"beats_all": beats, "energy_all": [0.3 if b < 8 else 0.85 for b in beats], "beat_len": bl, "beats": beats,
            "thresholds": (0.35, 0.7)}


def test_profiles_differ_by_reference():
    f, s = learn.attention_profile([FAST]), learn.attention_profile([SLOW])
    assert f["shot_sec"] == 0.4 and s["shot_sec"] > 2 and f["open"]["hold"] == 1.2
    assert f["variety"] > 2.5 > s["variety"] and f["loop"] and not s["loop"]
    assert 0.4 < f["peak_at"] < 0.7 and len(f["curve"]) == 8
    assert min(f["curve"][2:4]) < f["curve"][0]                    # the burst of short cuts after the opening
    assert learn.attention_profile([{"duration": 5, "shot_lens": [5]}]) == {}    # one continuous clip: nothing to learn
    both = learn.attention_profile([FAST, SLOW])                   # a style is what its examples have in common
    assert f["shot_sec"] < both["shot_sec"] < s["shot_sec"] and both["refs"] == 2
    assert "0.4s" in learn.describe_profile(f) and "re-learn" in learn.describe_profile({})


def test_rhythm_follows_the_learned_curve_on_the_beat():
    for prof, lo, hi in ((learn.attention_profile([FAST]), 0.5, 0.95), (learn.attention_profile([SLOW]), 2.0, 3.2)):
        st = load_style("beat-montage")
        st["attention"] = prof
        g = _grid()
        r = story.rhythm(g, st, 15)
        segs = r["segments"]
        ds = [s["dur"] for s in segs]
        assert lo <= statistics.mean(ds) <= hi and 0.6 <= statistics.mean(ds) / prof["shot_mean"] <= 1.7
        roles = [s["role"] for s in segs]
        assert roles[0] == "hook" and roles[-1] == "ending" and roles.count("peak") == 1
        assert all(min(abs(s["out_start"] - b) for b in g["beats_all"]) < 0.02 for s in segs)   # every cut on a beat
        assert abs(sum(ds) - r["duration"]) < 1e-3
        peak = next(s for s in segs if s["role"] == "peak")
        assert peak["dur"] >= max(0.8, prof["shot_sec"]) - 1e-6
    fast = story.rhythm(_grid(), {**load_style("beat-montage"), "attention": learn.attention_profile([FAST])}, 15)
    assert abs(fast["segments"][0]["dur"] - 1.0) < 0.3              # the reference's opening hold
    plain = story.rhythm(_grid(), load_style("beat-montage"), 15)   # no profile: the built-in story rhythm
    assert len(plain["segments"]) < len(fast["segments"])


def _shot(i, people=0, scene="landscape", score=7):
    return {"id": f"S{i:03d}", "kind": "video", "src": f"/x/{i}.mp4", "sig": f"g{i}", "t0": 0, "t1": 10, "w": 1920,
            "h": 1080, "fps": 30, "thumb": "", "metrics": {"pan": 0.0, "activity": 0.0},
            "ai": {"score": score, "mood": "calm", "scene": scene, "people": {"count": people, "activity": ""}}}


def test_cast_opens_like_the_reference_and_keeps_its_mix():
    shots = [_shot(0, score=8), _shot(1, score=7.5), _shot(2, scene="detail", score=7), _shot(3, scene="detail"),
             _shot(4), _shot(5, people=1, score=6.5), _shot(6, scene="food"), _shot(7)]
    segs = [{"role": r, "out_start": float(i), "dur": 1.0} for i, r in
            enumerate(("hook", "setup", "setup", "build", "peak", "release", "release", "ending"))]
    st = load_style("beat-montage")
    st["loop"] = False
    st["story"]["people_first"] = False
    st["attention"] = {"curve": [1] * 8, "shot_sec": 1.0, "open": {"hold": 1.0, "shot": "detail"},
                       "mix": {"wide": 0.4, "people": 0.1, "detail": 0.5}}
    order = story.cast(shots, segs, st)
    assert story.shot_kind(order[0]) == "detail"                    # opens on a detail, as the references do
    kinds = [story.shot_kind(s) for s in order]
    assert kinds.count("detail") == 3                               # all the details are used, spread through the reel
    st["attention"] = {}
    assert story.shot_kind(story.cast(shots, segs, st)[0]) == "wide"   # without a profile: the best shot opens


def test_critic_judges_pace_against_the_style_and_fixes_a_hook_about_a_later_shot():
    by_id = {"A": {"id": "A", "kind": "photo", "thumb": "", "ai": {"landmark": "Delicate Arch", "people": {"count": 0}}},
             "B": {"id": "B", "kind": "photo", "thumb": "", "ai": {"landmark": "Half Dome", "people": {"count": 0}}},
             "C": {"id": "C", "kind": "photo", "thumb": "", "ai": {"people": {"count": 0}}}}
    segs = [{"kind": "photo", "layout": "kenburns", "out_start": i * 3.0, "dur": 3.0, "shot_id": k, "src": k,
             "role": r} for i, (k, r) in enumerate((("A", "hook"), ("C", "peak"), ("B", "ending")))]
    plan = {"segments": segs, "duration": 9.0, "motion": {}, "loop": True,
            "overlays": [{"type": "hook", "text": "Stay for Half Dome at dusk", "start": 0.1, "duration": 2}],
            "attention": {"curve": [1] * 8, "shot_sec": 2.8}}
    cs = {c["check"]: c for c in critic.checks(plan, by_id, list(by_id.values()))}
    assert cs["rhythm"]["ok"]                                       # even 3 s shots are right for a slow style
    assert not cs["hook_matches"]["ok"]
    critic.fix(plan, by_id, list(by_id.values()), list(cs.values()))
    assert plan["segments"][0]["shot_id"] == "B"                    # now opens on Half Dome
    plan["attention"]["shot_sec"] = 0.6
    assert not {c["check"]: c for c in critic.checks(plan, by_id, list(by_id.values()))}["rhythm"]["ok"]
