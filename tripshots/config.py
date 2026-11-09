"""Paths, .env loading and style loading."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from .util import ReelError, deep_merge, short_hash

for _k in [k for k in os.environ if k.startswith("REELMAKER_")]:  # the app used to be called reelmaker
    os.environ.setdefault("TRIPSHOTS_" + _k[len("REELMAKER_"):], os.environ[_k])


def _home() -> Path:
    """~/.tripshots. A ~/.reelmaker folder from before the rename is moved here once (a link is left
    at the old path, so an old virtualenv inside it keeps working until install.sh is re-run)."""
    if os.environ.get("TRIPSHOTS_HOME"):
        return Path(os.environ["TRIPSHOTS_HOME"]).expanduser()
    new, old = Path.home() / ".tripshots", Path.home() / ".reelmaker"
    if not new.exists() and old.is_dir() and not old.is_symlink():
        try:
            old.rename(new)
            old.symlink_to(new)
        except OSError:
            return old
    return new


HOME = _home()
BUILTIN_STYLES = Path(__file__).parent / "styles"
USER_STYLES = HOME / "styles"
CACHE_ROOT = HOME / "cache"

OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30

DEFAULT_STYLE: dict = {
    "name": "default",
    "description": "Balanced beat-synced scenic montage.",
    "duration": {"target": 15, "min": 10, "max": 25},
    "music": {"window": "auto", "fade_out": 0.8},
    "cuts": {
        "beats_per_cut": {"calm": 4, "medium": 2, "intense": 2},
        "hook_beats": 2,
        "min_shot_sec": 0.6,
        "max_shot_sec": 3.5,
        "energy_thresholds": [0.35, 0.7],
    },
    "shots": {
        "min_score": 6,
        "ordering": "energy",          # energy | chronological | score
        "max_per_source": 3,
        "slowmo": True,                 # play high-fps calm shots at half speed
    },
    "layout": {
        "landscape": "auto",            # auto | crop | pan | blur_fill
        "photo_motion": "kenburns",     # kenburns | static
        "photo_zoom": 1.12,
        "pan_speed": 0.06,              # pans and drifts: at most this share of the picture's width per second
    },
    # frame: the picture's shape inside the 9:16 reel. aspect 9:16 = full screen; 16:9 or 2.39:1 = a cinematic
    # letterbox (the picture in a band, black above and below, text in the bars)
    "frame": {"aspect": "9:16"},
    # taste: what the edit should look for in your footage (learned from reference reels by `tripshots learn`).
    # look: the references' light and colour (diversity.look vector); weight 0..1 how strongly shots that look
    # like that are preferred; light: the kinds of light they show (golden_hour, sunset, fog, ...); people: how
    # people appear (silhouette, back_to_camera, facing_camera, none).
    "taste": {"look": None, "weight": 0.0, "light": [], "people": ""},
    # transitions: which ones per energy level, what share of cuts get one (the rest are hard
    # cuts on the beat), speed multiplier; "at: sections" forces one at every energy change/drop
    "transitions": {
        "palette": {"calm": ["dissolve", "leak", "blur"], "medium": ["whip", "zoom_in", "blur"],
                    "intense": ["flash", "zoom_in", "whip", "spin", "glitch"]},
        "density": 0.5, "speed": 1.0, "at": "sections",
    },
    # motion on top of every shot: zoom bump on beats, shake on drops, slow push on static video
    "motion": {"beat_punch": 0.05, "punch_on": ["intense"], "shake_on_drop": True, "shake_px": 22,
               "video_push": 0.06,
               # hype effects: freeze-frame (flash + push-in) on the biggest drop, and a colour-split
               # glitch on this share of hard cuts (0-1)
               "freeze": False, "rgb_split": 0.0},
    "color": {
        "saturation": 1.08, "contrast": 1.05, "brightness": 0.0, "gamma": 1.0,
        "warmth": 0.0, "vignette": False, "sharpen": 0.3, "lut": None,
    },
    # grade: per-shot colour grading (grade.py). look: auto (AI picks) | none | a preset
    # (natural, teal-orange, golden-hour, warm-film, moody, nordic, vivid, faded-matte) | a look
    # made with `tripshots look`. When active it replaces color.saturation/contrast/warmth/lut.
    # strength 0..1; ai: let the AI colourist judge exposure / white balance / mood per shot.
    "grade": {"look": "auto", "strength": 0.75, "ai": True},
    # route_map: animated travel-route map drawn from the footage's GPS (routemap.py, needs Node 22+
    # for HyperFrames). mode: off | intro (big card early on: the route draws itself on the beat)
    # | tracker (small corner map, a dot follows where each shot was taken) | both.
    # theme: auto (from the text preset) | dark | light. title: card heading (default: the regions).
    # sound: real sound effects on the cue frames (whooshes on whip/zoom transitions, an impact + riser on
    # the freeze-frame drop, pops as words land, shutter on flash cuts...) and a quiet ambience bed per
    # location (waves, wind, birds, city). Sources: ~/.tripshots/sfx/library, Openverse (CC0 / public
    # domain by default; "cc0,pdm,by" also allows credited CC BY), earshot's sound bank, then a fallback.
    # level_db shifts all effects; mixed under the music and mastered to -14 LUFS.
    "sound": {"sfx": "on", "ambience": "on", "native": "auto", "level_db": 0.0, "licenses": "cc0,pdm"},
    "route_map": {"mode": "off", "theme": "auto", "title": "", "max_stops": 7},
    # text.preset: bold | editorial | minimal | handwritten | typewriter (fonts + animations that
    # belong together; see typo.py). Any hook/location/cta key below overrides the preset.
    # text.motion: auto (with the HyperFrames runtime, words animate in a browser: rise out of a blur,
    # focus pull, tracking, write-on, slam; picked per preset, see hfx.py) | off | rise | focus |
    # tracking | typewriter | slam | write | cinema
    "text": {
        "preset": "bold",
        "motion": "auto",
        "font": None,
        "hook": {"mode": "off", "text": None, "start": 0.2, "duration": 2.8, "position": "auto"},
        "location": {"mode": "first", "position": "auto", "duration": 2.8, "coords": True},
        "cta": {"mode": "off", "text": None, "duration": 2.2},
        "labels": {"mode": "off", "max": 8},   # ai: short label on each shot ("Golden hour", "Highway 1")
    },
    # split screens / grids whose panels appear and keep cutting on the beat
    "panels": {"use": 0.0, "kinds": ["split2", "grid4", "split3", "columns3"], "mode": "mixed", "max": 2},
    # speed effects (retime.py). velocity.use: share (0-1) of moving clips that get a speed ramp, picked from
    # speed.ramps: velocity (rush in, slam into slow motion on the beat, speed out) | slam (real time, then
    # slow motion from the beat) | bullet (slow-motion hold around the beat) | rush (speeds up into the next
    # cut) | surge (slow start, takes off). speed.fast: share of moving clips in busy sections sped up
    # (1.6x medium, 2.2x intense, at most fast_max, with motion blur). speed.drop: the biggest drop gets
    # rush (the shot before speeds into it) | impact (the shot on it starts in slow motion) | both | off.
    # speed.smooth: slow motion from clips under 50 fps: flow (optical-flow in-between frames) | blend | off.
    "velocity": {"use": 0.0},
    "speed": {"ramps": ["velocity"], "fast": 0.0, "fast_max": 2.5, "drop": "off", "smooth": "flow"},
    "loop": False,  # dissolve the end into the first frame so the reel replays seamlessly
    # story (story.py, formats.py): plan every reel as a story instead of an even slideshow.
    # arc: on | off (off = the older even cut grid). format: auto | montage | pov | list | series | reveal.
    # hook_text: on (big hook line from the third frame, written by the AI) | style (the style's own hook setting).
    # hook_punch: the first shot settles from a push-in within 0.45 s. people_first: shots with you in them
    # win the hook, payoff and ending. loop: the ending is chosen to flow back into the opening.
    # captions: lines of dialogue/lyrics on screen: auto (dialogue: yes, songs: no) | original | english | off.
    # parallax: photos move in depth (2.5D) instead of a flat zoom: auto | on | off.
    # match_cuts: order and cut moving shots so their motion carries across the cut.
    # critic: check the plan like an editor and fix what it can: auto (rules + AI when available) | rules | off.
    # direction: a few sentences on how this style is directed (story, rhythm, camera, light, text); the critic's
    # AI review reads it with tripshots/DIRECTOR.md. `learn` writes one from the reference reels.
    "direction": "",
    "story": {"arc": "on", "format": "auto", "hook_text": "on", "hook_punch": True, "people_first": True,
              "loop": True, "captions": "auto", "parallax": "auto", "match_cuts": True, "critic": "auto"},
    # photo in a frame with the subject stepping out of it (needs rembg for the cut-out)
    "popout": {"use": 0.0, "bg": "paper", "variant": "auto"},
    "caption": {"tone": "warm, concise, first-person travel storyteller", "hashtags": 12},
}


def load_env() -> None:
    """Minimal .env loader: ./.env then ~/.tripshots/.env (existing env wins)."""
    for p in (Path.cwd() / ".env", HOME / ".env"):
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k.startswith("REELMAKER_"):  # .env files written before the rename
                k = "TRIPSHOTS_" + k[len("REELMAKER_"):]
            os.environ.setdefault(k, v)


def _fix_yaml_bools(d):
    """YAML reads an unquoted `mode: off` as False; turn those back into the words we mean."""
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if k in ("mode", "at", "landscape", "photo_motion", "window") and isinstance(v, bool):
                v = "on" if v else ("off" if k == "mode" else "none")
            out[k] = _fix_yaml_bools(v)
        return out
    if isinstance(d, list):
        return [_fix_yaml_bools(x) for x in d]
    return d


def list_styles() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in (BUILTIN_STYLES, USER_STYLES):
        if d.exists():
            for p in sorted(d.glob("*.y*ml")):
                found[p.stem] = p
    return found


def load_style(name_or_path: str | None) -> dict:
    if not name_or_path:
        name_or_path = "beat-montage"
    p = Path(name_or_path).expanduser()
    if not p.exists():
        styles = list_styles()
        if name_or_path not in styles:
            raise ReelError(f"Unknown style '{name_or_path}'. Available: {', '.join(styles) or 'none'}")
        p = styles[name_or_path]
    data = _fix_yaml_bools(yaml.safe_load(p.read_text()) or {})
    style = deep_merge(DEFAULT_STYLE, data)
    style.setdefault("name", p.stem)
    return style


def cache_dir_for(inputs: list[Path]) -> Path:
    key = "|".join(sorted(str(p.resolve()) for p in inputs))
    name = inputs[0].resolve().name if inputs else "reel"
    d = CACHE_ROOT / f"{name}-{short_hash(key)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


ENV_PATH = HOME / ".env"


def read_env() -> dict:
    out = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env(updates: dict) -> None:
    """Update keys in ~/.tripshots/.env, keep everything else (comments included)."""
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    done = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip().lstrip("# ").strip() if "=" in line else None
        if key in updates:
            if key not in done:
                v = updates[key]
                out.append(f"{key}={v}" if v else f"# {key}=")
                done.add(key)
            continue
        out.append(line)
    for k, v in updates.items():
        if k not in done and v:
            out.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(out).rstrip() + "\n")
    for k, v in updates.items():  # so jobs started from this session see it immediately
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def default_out_dir() -> Path:
    """Where finished reels go: TRIPSHOTS_OUT, else ./reels (the app and the MCP server set TRIPSHOTS_OUT)."""
    v = os.environ.get("TRIPSHOTS_OUT")
    return Path(v).expanduser() if v else Path.cwd() / "reels"
