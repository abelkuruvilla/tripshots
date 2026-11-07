import numpy as np

from tripshots import sound


def cue(t, role, pri=None, group=None):
    return {"t": t, "role": role, "why": "", "run": 0, "gain_db": 0.0,
            "pri": sound.ROLES[role]["pri"] if pri is None else pri, "group": group or f"{role}@{t}"}


def test_restrain_density():
    cues = [cue(i * 0.5, "whoosh") for i in range(20)]  # 20 whooshes in 10 s
    assert len(sound.restrain(cues)) <= sound.DENSITY_PER_10S


def test_restrain_keeps_runs_whole():
    run = [cue(1 + i * 0.1, "pop", group="hook") for i in range(5)]
    out = sound.restrain(run + [cue(5, "whoosh")])
    assert sum(c["role"] == "pop" for c in out) in (0, 5)


def test_nothing_steps_on_an_impact():
    out = sound.restrain([cue(2.0, "impact"), cue(2.2, "whoosh")])
    assert [c["role"] for c in out] == ["impact"]


def test_cues_follow_the_plan():
    plan = {"duration": 6.0, "segments": [
        {"out_start": 0.0, "dur": 2.0, "trans_out": "whip", "trans_dur": 0.3},
        {"out_start": 2.0, "dur": 2.0, "trans_out": None, "incam_out": {"type": "whip_pan", "at": 3.9}},
        {"out_start": 4.0, "dur": 2.0, "trans_out": None}]}
    roles = {(round(c["t"]), c["role"]) for c in sound.build_cues(plan, [])}
    assert any(r.startswith("whoosh") and t == 2 for t, r in roles)
    assert any(r.startswith("whoosh") and t == 4 for t, r in roles)


def test_clip_audio_judge():
    sr = sound.SR
    rng = np.random.default_rng(0)
    surf = rng.normal(0, 0.02, (sr * 2, 2)).astype(np.float32)
    assert sound.judge_clip_audio(surf)[0]
    assert sound.judge_clip_audio(np.zeros((sr * 2, 2), np.float32))[1] == "near silent"
    t = np.arange(sr * 2) / sr
    rumble = np.repeat((0.3 * np.sin(2 * np.pi * 40 * t))[:, None], 2, axis=1).astype(np.float32)
    assert sound.judge_clip_audio(rumble)[1].startswith("wind")
