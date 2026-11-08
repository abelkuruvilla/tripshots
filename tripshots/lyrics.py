"""The words in the sound: song lines, film dialogue or a voice-over, with their times.

A beat tracker only hears the drums. When the sound has words, the edit should follow them: a dialogue reel
cuts in the pauses between lines and lands its payoff shot on the punchline; a song's payoff lands on its hook
line. `words(audio)` asks Gemini (which listens to audio; GEMINI_API_KEY) for every line with its start and end,
an English translation when it isn't English, what kind of sound it is and which line is the punchline. With
faster-whisper installed it can transcribe offline instead (no punchline then). Cached per file.

Result: {"kind": "dialogue" | "song" | "instrumental", "language", "lines": [{"start", "end", "text",
"english"}], "punch": line index or None, "punch_t": seconds or None, "source"}.
"""
from __future__ import annotations

from pathlib import Path

from . import library as lib
from .util import file_sig, log, read_json, write_json

CACHE = lib.LIB_DIR / "lyrics"
VERSION = 1

PROMPT = """Listen to this audio (the sound of a short video). Transcribe every spoken or sung line with exact
times in seconds from the start of THIS file (one decimal).
Reply with JSON only:
{"kind": "dialogue" | "song" | "instrumental",   // dialogue = speech (a film scene, a voice-over), even over music
 "language": "<ISO code of the words, e.g. en, ml, hi, es>",
 "lines": [{"start": 0.0, "end": 1.8, "text": "<the words as said, in their own script>",
            "english": "<an English translation, or the same text if it is English>"}],
 "punch": <index of the line that lands hardest: the punchline, the hook line, the reveal; null if none>}
Rules: one entry per phrase or sentence as it is delivered (split at breaths and pauses); lines in time order,
never overlapping; no lines for instrumental parts; if there are no words, "lines" is [] and kind is
"instrumental". Never invent words you can't hear; mark unclear words with "…"."""


def _cache(path: Path) -> Path:
    return CACHE / f"{file_sig(path)}-v{VERSION}.json"


def _clean(raw: dict, duration: float | None = None) -> dict:
    lines = []
    for ln in raw.get("lines") or []:
        try:
            a, b = float(ln["start"]), float(ln["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if b <= a or (duration and a > duration):
            continue
        txt = str(ln.get("text") or "").strip()
        if not txt:
            continue
        lines.append({"start": round(a, 2), "end": round(b, 2), "text": txt[:160],
                      "english": str(ln.get("english") or txt).strip()[:160]})
    lines.sort(key=lambda x: x["start"])
    for x, y in zip(lines, lines[1:]):  # never overlapping
        if y["start"] < x["end"]:
            x["end"] = round(max(x["start"] + 0.1, y["start"]), 2)
    kind = str(raw.get("kind") or ("dialogue" if lines else "instrumental"))
    if kind not in ("dialogue", "song", "instrumental"):
        kind = "song" if lines else "instrumental"
    punch = raw.get("punch")
    punch = int(punch) if isinstance(punch, (int, float)) and 0 <= int(punch) < len(lines) else None
    return {"kind": kind if lines else "instrumental", "language": str(raw.get("language") or "")[:8],
            "lines": lines, "punch": punch, "punch_t": lines[punch]["start"] if punch is not None else None}


def _gemini(path: Path) -> dict | None:
    from . import watch
    ok, why = watch.available()
    if not ok:
        log(f"words: Gemini off ({why}); the edit follows the beat only")
        return None
    try:
        g = watch.Gemini()
        from google.genai import types
        up = g._active(g.client.files.upload(file=str(path)))
        try:
            g.pacer.wait()
            cfg = types.GenerateContentConfig(response_mime_type="application/json")
            for model in list(g.models):
                try:
                    r = g.client.models.generate_content(model=model, contents=[up, PROMPT], config=cfg)
                    from .ai import extract_json
                    return extract_json(r.text or "")
                except Exception as e:
                    if watch._gone(e):
                        continue
                    raise
        finally:
            try:
                g.client.files.delete(name=up.name)
            except Exception:
                pass
    except Exception as e:
        log(f"words: Gemini couldn't transcribe the sound ({str(e)[:140]}); the edit follows the beat only")
    return None


def _whisper(path: Path) -> dict | None:
    try:
        from faster_whisper import WhisperModel  # optional
    except ImportError:
        return None
    try:
        model = WhisperModel("small", compute_type="int8")
        segs, info = model.transcribe(str(path), vad_filter=True)
        lines = [{"start": s.start, "end": s.end, "text": s.text.strip(), "english": s.text.strip()} for s in segs]
        return {"kind": "dialogue" if lines else "instrumental", "language": info.language, "lines": lines,
                "punch": None}
    except Exception as e:
        log(f"words: offline transcription failed ({str(e)[:120]})")
        return None


def words(audio: str | Path | None, duration: float | None = None, refresh: bool = False) -> dict | None:
    """The sound's lines (cached per file). None when nothing can transcribe it."""
    if not audio:
        return None
    path = Path(audio)
    if not path.exists():
        return None
    c = _cache(path)
    if not refresh:
        got = read_json(c)
        if got:
            return got
    raw = _gemini(path)
    src = "gemini"
    if raw is None:
        raw, src = _whisper(path), "whisper"
    if raw is None:
        return None
    out = {**_clean(raw, duration), "source": src}
    CACHE.mkdir(parents=True, exist_ok=True)
    write_json(c, out)
    if out["lines"]:
        log(f"words: {out['kind']} in '{out['language'] or '?'}', {len(out['lines'])} line(s)"
            + (f", punchline at {out['punch_t']:.1f}s" if out.get("punch_t") is not None else ""))
    return out


def window(w: dict | None, start: float, length: float) -> dict | None:
    """The lines inside the music window the reel uses, re-timed from its start."""
    if not w or not w.get("lines"):
        return w
    lines = [{**ln, "start": round(ln["start"] - start, 2), "end": round(ln["end"] - start, 2)}
             for ln in w["lines"] if ln["end"] > start and ln["start"] < start + length]
    punch_t = w.get("punch_t")
    punch_t = round(punch_t - start, 2) if punch_t is not None and start <= punch_t < start + length else None
    return {**w, "lines": lines, "punch_t": punch_t}


def caption_overlays(w: dict | None, total: float, mode: str = "auto") -> list[dict]:
    """On-screen lines. auto: dialogue gets English subtitles (its own words when it is English); songs none."""
    if not w or not w.get("lines") or mode == "off":
        return []
    if mode == "auto" and w.get("kind") != "dialogue":
        return []
    use_english = mode == "english" or (mode == "auto" and (w.get("language") or "en")[:2] != "en")
    out = []
    for ln in w["lines"]:
        a, b = max(0.0, ln["start"]), min(total - 0.05, ln["end"] + 0.25)
        if b - a < 0.4:
            continue
        txt = ln["english"] if use_english else ln["text"]
        out.append({"type": "caption", "text": txt, "start": round(a, 3), "duration": round(b - a, 3)})
    return out
