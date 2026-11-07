"""Beat, downbeat and energy analysis with librosa, plus picking the best window of a song."""
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


def analyze_music(path: Path, work: Path) -> dict:
    cache_p = work / f"music_{file_sig(path)}.json"
    cached = read_json(cache_p)
    if cached:
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

    res = {"path": str(path), "duration": float(dur), "tempo": round(tempo, 1), "beats": [round(t, 4) for t in beat_t],
           "downbeat_phase": phase, "energy": [round(float(v), 3) for v in energy], "drops": sorted(drops)}
    write_json(cache_p, res)
    log(f"  tempo {tempo:.0f} BPM, {len(beat_t)} beats, {dur:.1f}s")
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
