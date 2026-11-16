"""Beat, downbeat and energy analysis with librosa, plus picking the best window of a song, which stretches have
a beat to cut on (`sections`) and where the climaxes are (`peaks`)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import librosa
import numpy as np

from .util import ReelError, file_sig, log, read_json, write_json

SR = 22050
HOP = 512


def _refine(y: np.ndarray, sr: int, beats: np.ndarray, win: float = 0.05) -> np.ndarray:
    """Snap each beat to the sharpest nearby transient using a ~3 ms resolution onset envelope
    (the beat tracker works on a coarse 23 ms grid and tends to land a frame late)."""
    hop = 64
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, center=True)
    t = librosa.frames_to_time(np.arange(len(env)), sr=sr, hop_length=hop)
    out = []
    for b in beats:
        sel = np.nonzero((t >= b - win) & (t <= b + win))[0]
        if len(sel) == 0:
            out.append(b)
            continue
        seg = env[sel]
        if seg.max() <= 1.5 * np.median(env[max(0, sel[0] - 40): sel[-1] + 40] + 1e-9):
            out.append(b)  # no clear transient: keep tracker's estimate
            continue
        # first point that reaches half of the local peak = attack onset
        k = int(np.argmax(seg >= 0.5 * seg.max()))
        out.append(float(t[sel[k]]))
    return np.array(out)


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    """Decode any audio/video file (m4a, aac, mp3, mp4, mov, wav...) with ffmpeg to mono float32."""
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                           "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise ReelError(f"could not read music file {path}: {proc.stderr.decode(errors='ignore')[-300:]}")
    y = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    if len(y) < SR:
        raise ReelError(f"music file {path.name} is shorter than 1 second")
    return y, SR


VERSION = 2  # 2: sections (cut on the beat, or let it flow) and peaks (climaxes with their breath)


def sections(y: np.ndarray, sr: int, beat_t: np.ndarray, energy: np.ndarray) -> list[dict]:
    """Where the beat grid can be trusted. A section with a clear drum pulse is cut on its beats ("beat"); a
    calm, beatless stretch (pads, a piano intro, an ambient bridge) is not: shots there are held longer and
    flow into each other ("flow"), instead of being cut to a metronome the music doesn't have.

    Pulse = the percussive part's onset strength on the beat against its level between beats, per bar; a bar
    is "flow" when the pulse is weak and the music is not loud. Runs shorter than two bars join their neighbours.
    Returns [{"t0", "t1", "mode": "beat"|"flow", "pulse"}] covering the song."""
    dur = len(y) / sr
    if len(beat_t) < 8:
        return [{"t0": 0.0, "t1": round(dur, 3), "mode": "flow", "pulse": 0.0}]
    lead = []
    if beat_t[0] > 2.0:  # no beat found before the drums come in: that intro flows
        lead = [{"t0": 0.0, "t1": round(float(beat_t[0]), 3), "mode": "flow", "pulse": 0.0}]
    perc = librosa.effects.percussive(y, margin=2.0)
    env = librosa.onset.onset_strength(y=perc, sr=sr, hop_length=HOP)
    fr = np.clip(librosa.time_to_frames(beat_t, sr=sr, hop_length=HOP), 0, len(env) - 1)
    on = np.array([env[max(0, f - 2): f + 3].max() for f in fr])
    between = np.array([np.median(env[a + 3: b - 2]) if b - a > 6 else np.median(env[a:b + 1])
                        for a, b in zip(fr, list(fr[1:]) + [min(len(env) - 1, fr[-1] + int(np.median(np.diff(fr))))])])
    ratio = on / (between + 0.05 * float(np.median(env) + 1e-6) + 1e-6)
    level = on / (np.percentile(on, 90) + 1e-6)
    pulse = np.minimum(ratio / 3.0, 1.0) * np.minimum(level * 1.6, 1.0)  # a clear hit, and a hit that is heard
    bars = []
    for i in range(0, len(beat_t), 4):
        p = float(np.mean(pulse[i:i + 4]))
        e = float(np.mean(energy[i:i + 4])) if len(energy) else 0.5
        bars.append((i, p, e))
    ps = np.array([b[1] for b in bars])
    ps = np.convolve(np.pad(ps, 1, mode="edge"), np.ones(3) / 3, mode="valid")  # over about three bars
    modes = ["flow" if p < 0.42 and e < 0.6 else "beat" for p, (_, _, e) in zip(ps, bars)]
    for _ in range(2):  # a lone bar is the music breathing, not a section
        for k in range(len(modes)):
            run = [k]
            while run[-1] + 1 < len(modes) and modes[run[-1] + 1] == modes[k]:
                run.append(run[-1] + 1)
            if len(run) < 2 and 0 < k < len(modes) - 1 and modes[k - 1] == modes[k + 1]:
                modes[k] = modes[k - 1]
    out = []
    for k, (i, _, _) in enumerate(bars):
        t0 = 0.0 if k == 0 else float(beat_t[i])
        if out and out[-1]["mode"] == modes[k]:
            out[-1]["_p"].append(float(ps[k]))
            continue
        if out:
            out[-1]["t1"] = round(t0, 3)
        out.append({"t0": round(t0, 3), "t1": round(dur, 3), "mode": modes[k], "_p": [float(ps[k])]})
    for s in out:
        s["pulse"] = round(float(np.mean(s.pop("_p"))), 3)
    if lead:
        out[0]["t0"] = lead[0]["t1"]
        out = lead + out if out[0]["mode"] != "flow" else [{**out[0], "t0": 0.0}] + out[1:]
    return out


def peaks(y: np.ndarray, sr: int, beat_t: np.ndarray) -> list[dict]:
    """The song's climaxes: where loudness, attack and brightness rise together (z-scored, summed on a 0.25 s
    grid), the next second against the two before. A short dip just before the hit ("the breath", the held
    note before a drop) makes a peak hit harder and is measured: `breath` is how long the quiet lasts (0 when
    the music runs straight in). Peaks sit on a beat and at least 6 s apart; a big rise is a "drop", a
    smaller one a "lift". Returns [{"t", "rise", "kind", "breath"}] by time."""
    step = 0.25
    hop = int(sr * step)
    if len(y) < hop * 16:
        return []
    rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
    loud = librosa.amplitude_to_db(rms + 1e-6)
    ons = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    bw = librosa.feature.spectral_bandwidth(y=y, sr=sr, hop_length=hop)[0]
    n = min(len(loud), len(ons), len(bw))

    def z(a):
        a = a[:n]
        return (a - a.mean()) / (a.std() + 1e-6)
    raw = z(loud)
    c = raw + 0.8 * z(ons) + 0.6 * z(bw)
    c = np.convolve(c, np.ones(2) / 2, mode="same")

    def breath_at(k: int) -> float:
        """How long it goes quiet just before frame k (up to 0.75 s): louder before that, then a hush."""
        if k < 6:
            return 0.0
        before = float(np.median(raw[max(0, k - 10):k - 3]))
        b = 0.0
        for j in range(k - 1, max(0, k - 4), -1):
            if raw[j] < before - 0.5:
                b += step
            elif b:
                break
        return b
    cands = []
    for k in range(8, n - 4):
        before, after = c[k - 8:k].mean(), c[k:k + 4].mean()
        rise = float(after - before)
        if rise < 0.8:
            continue
        breath = max(breath_at(k), breath_at(k - 1))
        cands.append((rise + 0.5 * min(breath, 0.75) / 0.75, k * step, rise, breath))
    cands.sort(reverse=True)
    out: list[dict] = []
    for score, t, rise, breath in cands:
        if len(beat_t):
            t = float(beat_t[int(np.argmin(np.abs(beat_t - t)))])
            k = int(round(t / step))
            breath = max(breath, breath_at(k), breath_at(k + 1))  # measured at the beat it lands on
        if t < 1.0 or any(abs(t - p["t"]) < 6.0 for p in out):
            continue
        out.append({"t": round(t, 3), "rise": round(rise, 2), "kind": "drop" if rise >= 2.5 else "lift",
                    "breath": round(breath, 2)})
        if len(out) >= 8:
            break
    return sorted(out, key=lambda p: p["t"])


def section_at(music_sections: list[dict] | None, t: float) -> str:
    for s in music_sections or []:
        if s["t0"] - 1e-3 <= t < s["t1"]:
            return s["mode"]
    return "beat"


def analyze_music(path: Path, work: Path) -> dict:
    cache_p = work / f"music_{file_sig(path)}.json"
    cached = read_json(cache_p)
    if cached and cached.get("v", 1) >= VERSION:
        return cached
    log(f"analyzing music: {path.name}")
    y, sr = load_audio(path)
    dur = len(y) / sr
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=HOP, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])
    beat_t = librosa.frames_to_time(beats, sr=sr, hop_length=HOP)
    if len(beat_t) < 8:  # ambient/beatless track: make a soft grid
        step = 60.0 / (tempo if tempo > 40 else 80.0)
        beat_t = np.arange(0.0, dur, step)
    beat_t = _refine(y, sr, beat_t.astype(float))
    if len(beat_t) > 8:  # tempo from the actual beat spacing is more precise than the estimate
        tempo = 60.0 / float(np.median(np.diff(beat_t)))

    # downbeat phase: which beat in each bar of 4 carries the most onset energy
    strength = onset[np.clip(librosa.time_to_frames(beat_t, sr=sr, hop_length=HOP), 0, len(onset) - 1)]
    phase = int(np.argmax([strength[p::4].mean() if len(strength[p::4]) else 0 for p in range(4)]))

    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    rms_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP)
    # loudness per beat interval, normalized to 0..1 (robust percentiles)
    edges = list(beat_t) + [dur]
    e = []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (rms_t >= a) & (rms_t < b)
        e.append(float(rms[sel].mean()) if sel.any() else 0.0)
    e = np.array(e)
    lo, hi = np.percentile(e, 10), np.percentile(e, 95)
    energy = np.clip((e - lo) / (hi - lo + 1e-9), 0, 1)
    energy = np.convolve(energy, np.ones(4) / 4, mode="same")  # smooth over ~a bar

    # simple "drop" candidates: biggest positive jumps of bar energy
    bar_e = np.array([energy[i:i + 4].mean() for i in range(0, len(energy), 4)])
    jumps = np.diff(bar_e, prepend=bar_e[0])
    drops = [float(beat_t[min(i * 4, len(beat_t) - 1)]) for i in np.argsort(jumps)[::-1][:3] if jumps[i] > 0.15]

    secs = sections(y, sr, beat_t, energy)
    pk = peaks(y, sr, beat_t)
    res = {"v": VERSION, "path": str(path), "duration": float(dur), "tempo": round(tempo, 1),
           "beats": [round(t, 4) for t in beat_t],
           "downbeat_phase": phase, "energy": [round(float(v), 3) for v in energy], "drops": sorted(drops),
           "sections": secs, "peaks": pk}
    write_json(cache_p, res)
    flow = sum(s["t1"] - s["t0"] for s in secs if s["mode"] == "flow")
    log(f"  tempo {tempo:.0f} BPM, {len(beat_t)} beats, {dur:.1f}s"
        + (f", {flow:.0f}s without a beat to cut on" if flow >= 2 else "")
        + (", climaxes at " + ", ".join("%.1fs" % p["t"] for p in pk[:4]) if pk else ""))
    return res


def choose_window(music: dict, target: float, mode="auto") -> float:
    """Return the song start time so a `target`-second reel uses the best part of the song."""
    beats = np.array(music["beats"])
    dur = music["duration"]
    if mode not in ("auto", None):
        try:
            return float(mode)
        except (TypeError, ValueError):
            pass
    if dur <= target + 1 or len(beats) < 8:
        return 0.0
    energy = np.array(music["energy"])
    phase = music["downbeat_phase"]
    best, best_t = -1e9, 0.0
    for i in range(phase, len(beats), 4):  # start on a downbeat
        t0 = beats[i]
        if t0 + target > dur - 0.5:
            break
        sel = (beats >= t0) & (beats < t0 + target)
        if sel.sum() < 4:
            continue
        en = energy[sel]
        # want energetic overall, with a lift soon after the start (hook), and not a fade-out
        first = en[: max(2, len(en) // 4)].mean()
        score = en.mean() + 0.4 * first - 0.6 * max(0.0, en[: len(en) // 2].mean() - en[len(en) // 2:].mean() - 0.3)
        if t0 < 1.0:
            score -= 0.05  # intros are usually weaker
        if score > best:
            best, best_t = score, float(t0)
    return best_t


def beats_in_window(music: dict, start: float, length: float) -> tuple[list[float], list[float], int]:
    """Beat times relative to window start, their energy, and the index of the first downbeat."""
    beats = np.array(music["beats"])
    energy = np.array(music["energy"])
    sel = (beats >= start - 1e-3) & (beats <= start + length + 1e-3)
    idx = np.nonzero(sel)[0]
    rel = list((beats[idx] - start).round(4))
    en = list(energy[idx].round(3))
    first_db = next((k for k, i in enumerate(idx) if (i - music["downbeat_phase"]) % 4 == 0), 0)
    return rel, en, first_db


def phase_stats(cuts, beats, fps: float = 30.0) -> dict | None:
    """Where cuts land against the beat, the way an editor's habit shows: `on_beat` (share within one frame of a
    beat), `offset_f` (the typical signed offset, in frames, of the cuts near a beat: -1 = a frame early, as many
    editors cut so the new picture is there when the hit lands), `phase` (circular mean of where in the beat the
    cuts fall: 0 = on it, 0.5 = on the "and") and `R` (0-1, how consistently: 1 = every cut at that phase)."""
    b = np.asarray(beats, float)
    c = np.asarray([x for x in cuts if len(b) > 1 and b[0] <= x <= b[-1]], float)
    if len(c) < 4:
        return None
    i = np.clip(np.searchsorted(b, c, side="right") - 1, 0, len(b) - 2)
    ph = (c - b[i]) / np.maximum(b[i + 1] - b[i], 1e-3)
    ang = 2 * np.pi * ph
    mc, ms = float(np.mean(np.cos(ang))), float(np.mean(np.sin(ang)))
    near = np.abs(c[:, None] - b[None, :]).argmin(1)
    off = (c - b[near]) * fps
    close = off[np.abs(off) <= 3.5]
    return {"n": int(len(c)), "on_beat": round(float(np.mean(np.abs(off) <= 1.01)), 2),
            "offset_f": int(round(float(np.median(close)))) if len(close) >= 3 else 0,
            "phase": round(float((np.arctan2(ms, mc) / (2 * np.pi)) % 1.0), 3), "R": round(float(np.hypot(mc, ms)), 2)}
