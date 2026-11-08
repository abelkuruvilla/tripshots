"""Build an edit decision list (plan.json) from scored shots, music beats and a style."""
from __future__ import annotations

from collections import Counter

import numpy as np

from .config import OUT_FPS
from .framing import crop_fraction, decide_layout, focus_box, subject_for
from .panels import layout_rects, plan_panel_clips
from .music import beats_in_window, choose_window
from .util import ReelError, clamp, log

FRAME = 1.0 / OUT_FPS


def _snap(t: float) -> float:
    return round(round(t * OUT_FPS) / OUT_FPS, 4)


# ----------------------------------------------------------------- cut grid
def cut_grid(music: dict | None, style: dict, target: float) -> dict:
    cuts = style["cuts"]
    lo_th, hi_th = cuts.get("energy_thresholds", [0.35, 0.7])
    bpc = cuts["beats_per_cut"]
    if music:
        start = choose_window(music, target, style["music"].get("window", "auto"))
        avail = music["duration"] - start
        length = min(target + 4, avail)
        beats, energy, first_db = beats_in_window(music, start, length)
        tempo = music["tempo"]
    else:
        start, tempo = 0.0, 100.0
        beats = list(np.arange(0, target + 4, 60 / tempo))
        energy, first_db = [0.5] * len(beats), 0
    beat_len = 60.0 / tempo if tempo > 0 else 0.6
    min_s, max_s = cuts["min_shot_sec"], cuts["max_shot_sec"]

    def beats_for(level: str) -> int:
        n = int(bpc.get(level, 2))
        while n * beat_len < min_s and n < 16:
            n *= 2
        while n * beat_len > max_s and n > 1:
            n //= 2
        return max(1, n)

    if not beats or beats[0] > 0.05:
        beats = [0.0] + beats
        energy = [energy[0] if energy else 0.5] + energy
        first_db += 1
    # start on the first downbeat if it is close, so cuts phrase with bars
    i = first_db if first_db < len(beats) and beats[first_db] < 1.2 else 0
    offset = beats[i]
    bounds = [beats[i]]
    levels = []
    hook_n = max(1, int(cuts.get("hook_beats", 2)))
    k = 0
    while True:
        e = energy[i] if i < len(energy) else 0.5
        level = "calm" if e < lo_th else ("intense" if e >= hi_th else "medium")
        n = hook_n if k == 0 else beats_for(level)
        if k == 0:
            while n * beat_len < min_s:
                n += 1
        j = i + n
        if j >= len(beats):
            break
        if beats[j] - offset > target + 0.01:
            # finishing: end on the beat closest to target if within duration limits
            break
        bounds.append(beats[j])
        levels.append(level)
        i, k = j, k + 1
    # make sure we reach the min duration (extend with the last cadence)
    dmin = style["duration"]["min"]
    while bounds[-1] - offset < dmin:
        bounds.append(bounds[-1] + beats_for("medium") * beat_len)
        levels.append("medium")
    # round each boundary (not each duration) to the frame grid so error never accumulates
    fb = [int(round((b - offset) * OUT_FPS)) for b in bounds]
    segs = []
    for a, b, lv in zip(fb[:-1], fb[1:], levels):
        if b > a:
            segs.append({"out_start": round(a / OUT_FPS, 4), "dur": round((b - a) / OUT_FPS, 4), "level": lv})
    total = fb[-1] / OUT_FPS
    beats_out = [round(b - offset, 4) for b in beats if -0.01 <= b - offset <= total + 0.01]
    energy_out = [float(e) for b, e in zip(beats, energy) if -0.01 <= b - offset <= total + 0.01]
    # the whole window's beats (not just up to the default cut): the story planner lays out its own length
    beats_all = [round(b - offset, 4) for b in beats if b - offset >= -0.01]
    energy_all = [float(e) for b, e in zip(beats, energy) if b - offset >= -0.01]
    # drops: start of a bar whose energy jumps well above the previous bar
    drops = []
    for j in range(4, len(beats) - 3, 1):
        prev = float(np.mean(energy[max(0, j - 4):j]))
        nxt = float(np.mean(energy[j:j + 4]))
        if nxt - prev > 0.22 and 0.3 < beats[j] - offset < total - 0.5:
            if not drops or beats[j] - offset - drops[-1] > 2.0:
                drops.append(round(beats[j] - offset, 4))
    return {"music_start": round(start + offset, 4), "segments": segs, "tempo": tempo,
            "duration": round(total, 4), "beat_len": beat_len, "beats": beats_out, "drops": drops,
            "energy": energy_out, "beats_all": beats_all, "energy_all": energy_all,
            "thresholds": (lo_th, hi_th)}


# ------------------------------------------------------------ shot selection
def _quality(s: dict) -> float:
    return float(s.get("ai", {}).get("score", 5.0))


def taste_scores(shots: list[dict], style: dict) -> dict[str, float]:
    """Bonus (about -3..+3) for shots that look like what the style was learned from: the same light and colour
    (golden backlight for a golden, backlit reference), its kind of light and of people, and shots that fit
    the frame's shape."""
    t = style.get("taste") or {}
    w = float(t.get("weight", 0) or 0)
    ref = t.get("look")
    from .framing import FRAME
    out: dict[str, float] = {}
    if w <= 0 and FRAME["ar"] <= 1.0:
        return out
    import numpy as np
    from .diversity import look_similarity, thumb_look
    ref_v = np.array(ref, np.float32) if ref else None
    lights = {str(x).lower() for x in t.get("light") or []}
    people = str(t.get("people") or "").lower()
    from .story import has_people
    for s in shots:
        v = 0.0
        if ref_v is not None and w > 0:
            lv = thumb_look(s.get("thumb"))
            if lv is not None and len(lv) == len(ref_v):
                v += w * (6.0 * look_similarity(ref_v, lv) - 2.0)
        a = s.get("ai") or {}
        tod = str(a.get("time_of_day") or "").lower()
        if lights and w > 0:
            words = (tod + " " + " ".join(a.get("tags", [])[:10]) + " " + str(a.get("note", ""))).lower()
            hit = any(l.replace("_", " ") in words or l.split("_")[0] in words for l in lights)
            v += w * (1.0 if hit else -0.5)
        if people and w > 0:
            hp = has_people(s)
            if people in ("silhouette", "back_to_camera", "facing_camera", "crowd"):
                v += w * (0.8 if hp else -0.3)
            elif people == "none":
                v += w * (-0.6 if hp else 0.3)
        if FRAME["ar"] > 1.0 and s.get("w") and s.get("h") and s["w"] < s["h"]:
            v -= 2.0  # an upright clip in a wide cinematic band loses most of its picture
        out[s["id"]] = round(v, 3)
    return out


def select_shots(shots: list[dict], n: int, style: dict) -> list[dict]:
    sh = style["shots"]
    pool = [s for s in shots if s.get("ai", {}).get("usable", True)]
    if not pool and shots:  # the user picked this footage (e.g. a search): use the best of it anyway
        log(f"the AI judged all {len(shots)} shots unusable; using the best of them anyway (check the storyboard)")
        pool = list(shots)
    if not pool:
        raise ReelError("no usable shots in this footage")
    thr = float(sh.get("min_score", 6))
    good = [s for s in pool if _quality(s) >= thr]
    while len(good) < n and thr > 1:
        thr -= 1
        good = [s for s in pool if _quality(s) >= thr]
    if len(good) < n:
        log(f"only {len(good)} usable shots for {n} cuts; some shots will repeat")
    per_src = int(sh.get("max_per_source", 3))
    taste = taste_scores(good, style)
    from .diversity import scene_groups
    group = scene_groups(good) if not sh.get("allow_similar") else {}
    used_group = Counter()
    chosen, used_src, used_tags = [], Counter(), Counter()
    cands = sorted(good, key=_quality, reverse=True)
    while len(chosen) < n and cands:
        best, best_v = None, -1e9
        for s in cands:
            if used_src[s["src"]] >= per_src:
                continue
            tags = s.get("ai", {}).get("tags", [])[:4]  # the main subjects (newer verdicts list up to 12)
            v = _quality(s) + taste.get(s["id"], 0.0) - 0.6 * used_src[s["src"]] - 0.25 * sum(used_tags[t] for t in tags)
            # avoid near-duplicate chunks of the same clip
            if any(c["src"] == s["src"] and abs(c["t0"] - s["t0"]) < 6 for c in chosen):
                v -= 2.0
            dup = s.get("ai", {}).get("duplicate_of")
            if dup and any(c["id"] == dup or c.get("ai", {}).get("duplicate_of") == s["id"] for c in chosen):
                v -= 2.5
            # the same moment again (a burst, the photo and the clip of one view): only when footage is thin
            v -= 4.0 * used_group[group.get(s["id"], s["id"])]
            if v > best_v:
                best, best_v = s, v
        if best is None:
            per_src += 1  # relax
            continue
        chosen.append(best)
        cands.remove(best)
        used_group[group.get(best["id"], best["id"])] += 1
        used_src[best["src"]] += 1
        for t in best.get("ai", {}).get("tags", [])[:4]:
            used_tags[t] += 1
    # top up by repeating best shots if footage is thin
    i = 0
    while len(chosen) < n and good:
        chosen.append(sorted(good, key=_quality, reverse=True)[i % len(good)])
        i += 1
    return chosen


def assign(chosen: list[dict], segs: list[dict], style: dict) -> list[dict]:
    """Order chosen shots onto segments."""
    pool = list(chosen)
    order: list[dict | None] = [None] * len(segs)

    def take(pred_key):
        best = max(pool, key=pred_key)
        pool.remove(best)
        return best

    variant = int(style["shots"].get("variant", 0) or 0)

    def hook_v(s):
        return (_quality(s) + (1.5 if s.get("ai", {}).get("role") == "hook" else 0)
                + (0.5 if s.get("ai", {}).get("mood") == "dynamic" else 0))
    # hook: strongest attention-grabber (variant k opens with the k-th best one)
    hooks = sorted(pool, key=hook_v, reverse=True)
    order[0] = hooks[min(variant, len(hooks) - 1)] if hooks else take(hook_v)
    if order[0] in pool:
        pool.remove(order[0])
    if len(segs) > 2:
        order[-1] = take(lambda s: _quality(s) * 0.5 + (2.0 if s.get("ai", {}).get("role") == "closer" else 0)
                         + (0.8 if s.get("ai", {}).get("mood") == "calm" else 0))
    mid_idx = [i for i, o in enumerate(order) if o is None]
    mode = style["shots"].get("ordering", "energy")
    if mode == "chronological":
        pool.sort(key=lambda s: (s.get("created") or "", s["src"], s["t0"]))
        for i, s in zip(mid_idx, pool):
            order[i] = s
    elif mode == "score":
        pool.sort(key=_quality, reverse=True)
        for i, s in zip(mid_idx, pool):
            order[i] = s
    else:  # energy: dynamic shots to intense sections, calm shots to calm sections
        def dyn(s):
            a = s.get("ai", {})
            jitter = (_stable_rand("var", variant, s["id"]) - 0.5) * 1.6 if variant else 0.0
            return (1.0 if a.get("mood") == "dynamic" else 0.0) + min(1.0, s["metrics"].get("pan", 0) * 40) + jitter
        rank = {"calm": 0, "medium": 1, "intense": 2}
        seg_sorted = sorted(mid_idx, key=lambda i: (rank[segs[i]["level"]], i))
        shot_sorted = sorted(pool, key=dyn)
        for i, s in zip(seg_sorted, shot_sorted):
            order[i] = s
    # avoid the same source twice in a row
    for i in range(1, len(order) - 1):
        if order[i]["src"] == order[i - 1]["src"]:
            for j in range(i + 1, len(order) - 1):
                if order[j]["src"] != order[i - 1]["src"] and order[j]["src"] != order[i]["src"] \
                        and (j + 1 >= len(order) or order[j + 1]["src"] != order[i]["src"]):
                    order[i], order[j] = order[j], order[i]
                    break
    return order


# ------------------------------------------------------------- per-shot cut
def _best_window(shot: dict, need: float) -> float:
    """Pick the in-point inside the shot: around the best instant Gemini saw (when the clip was
    watched), else the sharpest, steadiest frames."""
    w = (shot.get("ai") or {}).get("watch") or {}
    pk = w.get("peak")
    if pk is not None and shot["t0"] <= pk <= shot["t1"]:
        lo, hi = shot["t0"], max(shot["t0"], shot["t1"] - need)
        mo = w.get("moment") or [shot["t0"], shot["t1"]]
        # keep the peak a little past the middle (the eye arrives, then the moment lands), inside its moment
        start = pk - need * 0.45
        start = min(max(start, max(lo, mo[0] - 0.2)), hi)
        return round(max(lo, start), 3)
    s = shot.get("samples") or {}
    ts = s.get("t") or []
    t0, t1 = shot["t0"], shot["t1"]
    room = (t1 - t0) - need
    if room <= 0.05 or len(ts) < 3:
        return t0 + max(0.0, room) / 2
    sharp = np.log1p(np.array(s["sharp"]))
    jit = np.array(s["jitter"])
    q = (sharp - sharp.mean()) / (sharp.std() + 1e-6) - (jit - jit.mean()) / (jit.std() + 1e-6)
    best, best_v = t0, -1e9
    for start in np.arange(t0 + 0.15 * min(room, 1.0), t0 + room + 1e-6, 0.25):
        sel = [k for k, t in enumerate(ts) if start <= t <= start + need]
        if not sel:
            continue
        v = float(q[sel].mean())
        if v > best_v:
            best, best_v = float(start), v
    return best


def layout_for(shot: dict, style: dict) -> str:
    want = style["layout"].get("landscape", "auto")
    if shot["kind"] == "photo":
        return "kenburns" if style["layout"].get("photo_motion", "kenburns") == "kenburns" else "static"
    ar = shot["w"] / max(shot["h"], 1)
    if ar <= 0.75:
        return "fill"
    if want != "auto":
        return want
    if ar > 2.1:
        return "pan"
    return "crop"


def build_plan(shots: list[dict], music: dict | None, style: dict, target: float | None = None,
               music_path: str | None = None) -> dict:
    target = float(target or style["duration"]["target"])
    target = clamp(target, style["duration"]["min"], style["duration"]["max"])
    from .framing import band_height, set_frame
    ar = set_frame((style.get("frame") or {}).get("aspect"))
    letterbox = ar > 1.0
    if letterbox:  # a cinematic band: full-screen layouts (split screens, pop-out frames) don't fit it
        style.setdefault("panels", {})["use"] = 0.0
        style.setdefault("popout", {})["use"] = 0.0
    grid = cut_grid(music, style, target)
    segs = grid["segments"]
    st = style.get("story") or {}
    arc = str(st.get("arc", "on")).lower() not in ("off", "false", "0", "none")
    variant = int(style["shots"].get("variant", 0) or 0)
    fmt = str(st.get("format") or "montage")
    if arc:  # the story engine lays out the reel: roles and a varied rhythm (story.py)
        from . import story
        r = story.rhythm(grid, style, target, words=style.get("_words"), variant=variant)
        segs = r["segments"]
        grid = {**grid, "segments": segs, "duration": r["duration"], "drops": r["drops"],
                "beats": [b for b in (grid.get("beats_all") or grid["beats"]) if b <= r["duration"] + 0.01]}
        log(f"story: {story.describe(segs)}")
    floor = float(style["shots"].get("min_score", 6)) - 2
    allow_similar = bool(style["shots"].get("allow_similar", False))
    good = {s["id"]: s for s in shots if s.get("ai", {}).get("usable", True) and _quality(s) >= floor}
    n_unusable = sum(1 for s in shots if not s.get("ai", {}).get("usable", True))
    n_low = len(shots) - n_unusable - len(good)
    # near-duplicates (burst shots, the same view twice) count once, unless allowed
    distinct = [s for s in good.values() if allow_similar or s.get("ai", {}).get("duplicate_of") not in good]
    n_dup = len(good) - len(distinct)
    avail = len(distinct) or (len(shots) if n_unusable == len(shots) else 0)  # all rejected: select_shots falls back
    wanted = len(segs)
    max_len = float(style["cuts"]["max_shot_sec"]) * 1.6
    if avail < wanted:
        log(f"{len(shots)} candidates -> {avail} distinct usable shots "
            f"({n_dup} near-duplicates, {n_low} scored below {floor:g}, {n_unusable} rejected); "
            f"the style wants {wanted} cuts, so shots are held longer"
            + ("" if allow_similar else ". Use --allow-similar and/or --min-score 4 to use more of your footage"))
    while len(segs) > max(avail, 3):  # thin footage: hold shots longer rather than repeat them
        pairs = [(segs[i]["dur"] + segs[i + 1]["dur"], i) for i in range(1, len(segs) - 1)]
        pairs = [p for p in pairs if p[0] <= max_len]
        if not pairs:
            break
        pairs = [p for p in pairs if segs[p[1]].get("role") not in ("hook", "peak", "ending")
                 and segs[p[1] + 1].get("role") not in ("hook", "peak", "ending")] or pairs
        _, i = min(pairs)
        role = "peak" if "peak" in (segs[i].get("role"), segs[i + 1].get("role")) else segs[i].get("role")
        segs[i] = {"out_start": segs[i]["out_start"], "dur": round(segs[i]["dur"] + segs[i + 1]["dur"], 4),
                   "level": segs[i]["level"], **({"role": role} if role else {})}
        del segs[i + 1]
    segs, beat_len = plan_panels(segs, grid, style, avail)
    normal = [sg for sg in segs if not sg.get("panel")]
    panel_need = sum(panel_shot_count(sg) for sg in segs if sg.get("panel"))
    chosen = select_shots(shots, len(normal) + panel_need, style)
    # the strongest shots go full-screen; the rest fill panels (they're seen smaller anyway)
    ranked = sorted(chosen, key=_quality, reverse=True)
    full, extra = ranked[:len(normal)], ranked[len(normal):]
    if arc:
        from . import story
        from .diversity import scene_groups
        order_normal = story.cast(full, normal, style, variant, scene_groups(full), tease=fmt == "reveal",
                                  places=style.get("_places"), fmt=fmt)
    else:
        order_normal = assign(full, normal, style)
    extra = _spread_sources(extra)
    out = []
    kb_dir = 0
    it_normal = iter(order_normal)
    for i, seg in enumerate(segs):
        if seg.get("panel"):
            k = panel_shot_count(seg)
            mine, extra = extra[:k], extra[k:]
            if len(mine) < len(layout_rects(seg["panel"])):  # not enough footage: fall back to one shot
                seg = {kk: v for kk, v in seg.items() if kk not in ("panel", "pmode")}
                shot = mine[0] if mine else full[i % max(1, len(full))]
                e, kb_dir = _entry_for(shot, seg, style, kb_dir)
            else:
                e, kb_dir = _panel_entry(seg, mine, grid, style, kb_dir)
                if seg.get("role"):
                    e["role"] = seg["role"]
        else:
            e, kb_dir = _entry_for(next(it_normal), seg, style, kb_dir)
        e["idx"] = i
        ps = (style.get("layout") or {}).get("pan_speed")
        if ps is not None and e.get("layout") in ("pan", "kenburns"):
            e["pan_speed"] = float(ps)
        if seg.get("role"):
            e["role"] = seg["role"]
            if seg["role"] in ("hook", "peak", "ending") and e.get("layout") == "kenburns":
                e["kb"] = "in"  # the moments that matter push in on their subject, no sideways drift
        e["drop"] = any(abs(e["out_start"] - d) < 0.12 for d in grid["drops"]) or e.get("role") == "peak"
        out.append(e)
    apply_speed(out, {s["id"]: s for s in shots}, grid, style)
    choose_transitions(out, style)
    if arc:
        from . import story
        story.restrain_transitions(out)
    use_incam(out, {s["id"]: s for s in shots}, style)
    return {
        "version": 1, "style": style["name"], "duration": grid["duration"], "tempo": round(grid["tempo"], 1),
        "music": {"path": music_path, "start": grid["music_start"], "fade_out": style["music"].get("fade_out", 0.8)},
        "transition_duration": float(style["transitions"].get("duration", 0.3)),
        "color": style["color"], "text": style["text"], "segments": out, "overlays": [],
        "beats": grid["beats"], "drops": grid["drops"],
        "motion": {**style.get("motion", {}), **({"hook_punch": True} if arc and st.get("hook_punch", True) else {})},
        "loop": bool(style.get("loop", False)) or (arc and bool(st.get("loop", True))),
        **({"story": {"format": fmt, "arc": [s.get("role") for s in out]}} if arc else {}),
        **({"frame": {"aspect": (style.get("frame") or {}).get("aspect"), "ar": round(ar, 4),
                      "band": band_height(ar)}} if letterbox else {}),
    }



def use_incam(segs: list[dict], by_id: dict, style: dict, max_n: int = 3) -> int:
    """In-camera transitions: when the outgoing clip has a whip pan, end the shot in the middle of the
    swing (and start the next one mid-swing if it has one too), as a hard cut. The camera's own motion
    hides the cut: no added effect. Found by watch.py (Gemini, or blur at an in-clip picture change)."""
    if not (style.get("transitions") or {}).get("in_camera", True):
        return 0
    ends = {}
    for s in by_id.values():
        if s["kind"] == "video":
            ends[s["sig"]] = max(ends.get(s["sig"], 0.0), s["t1"])
    n, last = 0, -9.0
    for i, e in enumerate(segs[:-1]):
        sh = by_id.get(e.get("shot_id"))
        if (n >= max_n or not sh or e.get("panel") or e.get("ramp") or e.get("kind") != "video"
                or float(e.get("speed", 1)) > 1.01 or e["out_start"] - last < 4.0):
            continue
        need = float(e["dur"]) * float(e.get("speed", 1))
        for w in sh.get("incam") or []:
            if w.get("type") != "whip_pan":
                continue
            mid = (w["start"] + w["end"]) / 2
            if mid - need >= max(0.0, sh["t0"] - 1.0) and mid <= ends.get(sh["sig"], mid):
                e["in"] = round(mid - need, 3)
                e["incam_out"] = {"type": "whip_pan", "at": round(mid, 3), "src": w.get("src", "gemini")}
                e.update({"trans_out": None, "trans_dur": 0.0, "trans_params": {}})
                nxt, nsh = segs[i + 1], by_id.get(segs[i + 1].get("shot_id"))
                if nsh and nxt.get("kind") == "video" and not nxt.get("panel") and not nxt.get("ramp"):
                    for w2 in nsh.get("incam") or []:
                        m2 = (w2["start"] + w2["end"]) / 2
                        if w2.get("type") == "whip_pan" and nsh["t0"] - 0.5 <= m2 <= nsh["t0"] + 1.5 and \
                                m2 + float(nxt["dur"]) * float(nxt.get("speed", 1)) <= ends.get(nsh["sig"], 0):
                            nxt["in"] = round(m2, 3)
                            nxt["incam_in"] = True
                            break
                n += 1
                last = e["out_start"]
                break
    if n:
        log(f"{n} in-camera whip transition(s): cut inside the camera's own swing")
    return n


def _shot_fields(shot: dict, dur: float, level: str, style: dict, kb_dir: int, size=None) -> tuple[dict, int]:
    """Render fields for one shot used for `dur` seconds (full screen, or a panel of `size`)."""
    from .story import has_people
    e = {"shot_id": shot["id"], "kind": shot["kind"], "src": shot["src"], "thumb": shot.get("thumb"),
         "people": has_people(shot),
         "note": shot.get("ai", {}).get("note", ""), "score": _quality(shot)}
    box = subject_for(shot)
    e["subject"], e["subject_x"] = box, box["cx"]
    e["subject_out"] = {"y0": box["y0"], "y1": box["y1"]}
    if shot["kind"] == "video":
        avail = shot["t1"] - shot["t0"]
        speed = 1.0
        if size is None and style["shots"].get("slowmo", True) and (shot.get("fps") or 30) >= 48 \
                and level != "intense" and avail >= dur * 0.5:
            speed = 0.5
        elif avail < dur:
            speed = max(0.6, avail / dur)  # gentle slow-down instead of freezing
        e.update({"in": round(_best_window(shot, dur * speed), 3), "speed": round(speed, 3),
                  "hdr": shot.get("hdr", False), "transfer": shot.get("transfer"),
                  "src_w": shot["w"], "src_h": shot["h"], "fps": shot.get("fps")})
        if size is None:
            lay, extra = decide_layout(shot, box, style["layout"].get("landscape", "auto"))
            fb = focus_box(shot)
            if lay == "pan" and fb and (fb["x1"] - fb["x0"]) <= crop_fraction(shot["w"], shot["h"]) * 0.95:
                # a pan across a wide view would start or end without the person (or the main subject): frame it
                lay, extra = "crop", {}
                e["subject"], e["subject_x"] = fb, fb["cx"]
            e["layout"] = lay
            e.update(extra)
            e["track"] = lay == "crop" and (shot["metrics"].get("activity", 0) > 0.012
                                             or shot["metrics"].get("pan", 0) > 0.004)
        else:
            e["layout"] = "crop"
        e["static"] = shot["metrics"].get("pan", 0) < 0.003
        e["moving"] = shot["metrics"].get("pan", 0) > 0.004 or shot["metrics"].get("activity", 0) > 0.015
    else:
        st = style.get("story") or {}
        if (size is None and str(st.get("arc", "on")).lower() not in ("off", "false")
                and str(st.get("parallax", "auto")).lower() in ("auto", "on", "true")):
            e["parallax"] = True
            e["depth_key"] = f"{shot.get('sig') or shot['id']}"
        fb = focus_box(shot)
        if fb:  # Ken Burns pushes towards (and drifts around) the person or the main subject
            e["subject"], e["subject_x"], e["focus"] = fb, fb["cx"], True
        modes = ["in", "right", "out", "in_rot", "left", "up"] if size is None else ["in", "out"]
        e.update({"still": shot["still"], "kb": modes[kb_dir % len(modes)], "layout": "kenburns",
                  "src_w": shot["w"], "src_h": shot["h"], "static": False})
        kb_dir += 1
    return e, kb_dir


FAST_MOTIONS = {"walk", "drone", "pan", "handheld", "timelapse", "push"}


def _set_ramp(e: dict, shot: dict, kind: str, hit: float | None = None) -> bool:
    """Give a video segment a speed ramp if the clip has enough footage for it."""
    from . import retime
    trial = {**e, "ramp": kind, "speed": 1.0}
    if kind != "custom":
        trial.pop("ramp_points", None)
    if hit is not None:
        trial["ramp_hit"] = round(hit, 3)
    else:
        trial.pop("ramp_hit", None)
    need = retime.source_seconds(trial) * 1.08 + 0.3
    if shot["t1"] - shot["t0"] < need:
        return False
    e.clear()
    e.update(trial)
    e["in"] = round(_best_window(shot, need), 3)
    return True


def _hit_beat(e: dict, beats: list[float]) -> float | None:
    """The beat a ramp should slam into slow motion on: the first one 25-65 % into the shot."""
    st, d = float(e["out_start"]), float(e["dur"])
    for b in beats:
        if st + 0.25 * d <= b <= st + 0.65 * d:
            return b - st
    return None


def apply_speed(segs: list[dict], by_id: dict, grid: dict, style: dict) -> None:
    """Speed effects for impact (retime.py): ramps on clips with movement (style velocity.use, kinds from
    speed.ramps, the slam on a beat), speed-ups on moving clips in busy sections (speed.fast), and what
    happens around the biggest drop (speed.drop: rush into it, impact out of it). Calm shots stay real time
    or slow motion."""
    sp = style.get("speed") or {}
    smooth = sp.get("smooth", "flow")
    kinds = [k for k in (sp.get("ramps") or ["velocity"]) if k != "impact"]
    use = float((style.get("velocity") or {}).get("use", 0) or 0)
    fast = float(sp.get("fast", 0) or 0)
    fast_max = float(sp.get("fast_max", 2.5) or 2.5)
    beats = [float(b) for b in grid.get("beats") or []]
    n_ramp = n_fast = 0
    for e in segs:
        if e.get("kind") != "video":
            continue
        if smooth != "flow":
            e["smooth"] = smooth
        sh = by_id.get(e.get("shot_id"))
        if not sh or e.get("panel") or float(e.get("speed", 1)) < 0.99:
            continue
        motion = (sh.get("ai") or {}).get("motion")
        moving = e.get("moving") or motion in FAST_MOTIONS - {"timelapse"}
        if (use > 0 and kinds and moving and e["level"] != "calm" and e["dur"] >= 0.9
                and _stable_rand("vel", sh["id"], e["out_start"]) < use):
            kind = kinds[int(_stable_rand("rampkind", sh["id"], e["out_start"]) * len(kinds)) % len(kinds)]
            hit = _hit_beat(e, beats) if kind in ("velocity", "slam", "bullet") else None
            if _set_ramp(e, sh, kind, hit):
                e["track"] = False
                n_ramp += 1
                continue
        if (fast > 0 and e["level"] != "calm" and (moving or motion in FAST_MOTIONS)
                and _stable_rand("fast", sh["id"], e["out_start"]) < fast):
            want = min(fast_max, 1.6 if e["level"] == "medium" else 2.2)
            s = min(want, (sh["t1"] - sh["t0"]) / max(0.1, e["dur"]))
            if s >= 1.3:
                e["speed"] = round(s, 2)
                e["in"] = round(_best_window(sh, e["dur"] * s), 3)
                n_fast += 1
    drop = str(sp.get("drop", "off") or "off")
    if drop != "off" and grid.get("drops"):
        d = float(grid["drops"][0])
        for i, e in enumerate(segs):
            sh = by_id.get(e.get("shot_id"))
            if not sh or e.get("kind") != "video" or e.get("panel"):
                continue
            end = float(e["out_start"]) + float(e["dur"])
            if drop in ("rush", "both") and abs(end - d) < 0.05 and e["dur"] >= 0.6:
                n_ramp += _set_ramp(e, sh, "rush")
            elif drop in ("impact", "both") and abs(float(e["out_start"]) - d) < 0.05 and e["dur"] >= 0.8:
                n_ramp += _set_ramp(e, sh, "impact")
    if n_ramp or n_fast:
        log(f"speed: {n_ramp} ramp(s), {n_fast} speed-up(s)")


def _entry_for(shot: dict, seg: dict, style: dict, kb_dir: int) -> tuple[dict, int]:
    e, kb_dir = _shot_fields(shot, seg["dur"], seg["level"], style, kb_dir)
    e.update({"out_start": seg["out_start"], "dur": seg["dur"], "level": seg["level"]})
    # pop-out frame: photos with one clear, not-too-big subject (person, lighthouse, tree…)
    pcfg = style.get("popout") or {}
    if (e["kind"] == "photo" and float(pcfg.get("use", 0) or 0) > 0 and seg["dur"] >= 0.9
            and _stable_rand("pop", shot["id"], seg["out_start"]) < float(pcfg["use"])):
        sb = e.get("subject") or {}
        area = (sb.get("x1", 1) - sb.get("x0", 0)) * (sb.get("y1", 1) - sb.get("y0", 0))
        if 0.02 <= area <= 0.45 and sb.get("source") == "ai":
            e.update({"layout": "popout", "popout_bg": pcfg.get("bg", "paper"),
                      "popout_variant": pcfg.get("variant", "auto")})
    return e, kb_dir


def _panel_entry(seg: dict, shots: list[dict], grid: dict, style: dict, kb_dir: int) -> tuple[dict, int]:
    start, dur = seg["out_start"], seg["dur"]
    beats_rel = [round(b - start, 4) for b in grid["beats"] if start - 0.01 <= b < start + dur - 0.05]
    raw = plan_panel_clips(seg["panel"], dur, beats_rel, shots, seg.get("pmode", "reveal"), grid["beat_len"])
    clips = []
    for c in raw:
        x, y, w, h = c["rect"]
        f, kb_dir = _shot_fields(c["shot"], c["t1"] - c["t0"] + 0.3, seg["level"], style, kb_dir, size=(w, h))
        f.update({"rect": c["rect"], "t0": c["t0"], "t1": c["t1"], "intro": c["intro"]})
        clips.append(f)
    first = clips[0]
    e = {"panel": seg["panel"], "pmode": seg.get("pmode", "reveal"), "kind": "panel", "clips": clips,
         "out_start": start, "dur": dur, "level": seg["level"], "shot_id": first["shot_id"], "src": first["src"],
         "note": f"{seg['panel']} · {len(clips)} clips", "subject_out": {"y0": 0.45, "y1": 0.55},
         "static": False, "layout": "panel", "score": max(c["score"] for c in clips)}
    return e, kb_dir


def _spread_sources(shots: list[dict]) -> list[dict]:
    """Reorder so neighbouring panels don't show the same clip twice in a row."""
    out, pool = [], list(shots)
    while pool:
        pick = next((s for s in pool if not out or s["src"] != out[-1]["src"]), pool[0])
        out.append(pick)
        pool.remove(pick)
    return out


def panel_shot_count(seg: dict) -> int:
    n = len(layout_rects(seg["panel"]))
    return n * 2 if seg.get("pmode") == "cycle" else n


def plan_panels(segs: list[dict], grid: dict, style: dict, avail: int) -> tuple[list[dict], float]:
    """Merge runs of beat segments into split-screen / grid moments (style `panels`)."""
    pc = style.get("panels") or {}
    use = float(pc.get("use", 0) or 0)
    beat_len = grid["beat_len"]
    if use <= 0 or len(segs) < 5:
        return segs, beat_len
    kinds = [k for k in (pc.get("kinds") or ["split2", "grid4", "split3", "columns3"])
             if k in ("split2", "split3", "grid4", "columns3")] or ["split2"]
    mode = pc.get("mode", "mixed")
    max_n = int(pc.get("max", 2))
    step_beats = 1 if beat_len >= 0.38 else 2
    out = list(segs)
    count, i = 0, 2
    budget = avail - (len(segs) - 2)  # spare shots beyond one per remaining cut
    while i < len(out) - 2 and count < max_n:
        sg = out[i]
        if sg.get("panel") or sg["level"] == "calm" or sg.get("role") in ("hook", "peak", "ending") or _stable_rand("panel", i, sg["out_start"]) >= use:
            i += 1
            continue
        kind = kinds[int(_stable_rand("kind", i) * len(kinds)) % len(kinds)]
        n = len(layout_rects(kind))
        m = mode if mode in ("reveal", "cycle") else ("cycle" if count % 2 else "reveal")
        steps = n + (n if m == "cycle" else 1)
        need = steps * step_beats * beat_len
        j, total = i, 0.0
        while j < len(out) - 1 and total < need * 0.95 and out[j].get("role") not in ("hook", "peak", "ending"):
            total += out[j]["dur"]
            j += 1
        if total < (n + 0.5) * step_beats * beat_len:
            i += 1
            continue
        extra_needed = (n * (2 if m == "cycle" else 1)) - (j - i)
        if extra_needed > budget:
            if m == "cycle" and n - (j - i) <= budget:
                m = "reveal"
                extra_needed = n - (j - i)
            else:
                i += 1
                continue
        budget -= max(0, extra_needed)
        merged = {"out_start": out[i]["out_start"], "dur": round(sum(x["dur"] for x in out[i:j]), 4),
                  "level": "intense" if any(x["level"] == "intense" for x in out[i:j]) else "medium",
                  "panel": kind, "pmode": m, **({"role": out[i]["role"]} if out[i].get("role") else {})}
        out[i:j] = [merged]
        count += 1
        i += 3  # leave some full-screen shots between panel moments
    if count:
        log(f"{count} split-screen moment(s): " + ", ".join(f"{x['panel']} ({x['pmode']})" for x in out if x.get("panel")))
    return out, beat_len


# --------------------------------------------------------------- transitions
DEFAULT_PALETTE = {"calm": ["dissolve", "blur"], "medium": ["whip", "zoom_in", "blur"],
                   "intense": ["flash", "zoom_in", "whip", "spin", "glitch"]}


def _stable_rand(*parts) -> float:
    import hashlib
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def choose_transitions(segs: list[dict], style: dict) -> None:
    """Decide the transition at every cut (stored on the outgoing segment as trans_out).

    - level changes (calm->intense etc.) and drops always get a transition
    - otherwise a style-set share of cuts ("density") get one, the rest are hard cuts on the beat
    - the transition is picked from the palette for the incoming section's energy, never the same
      one twice in a row, and shortened (or swapped for a short one) if the shots are too brief
    """
    from .motion import NATURAL, normalize
    tr = style.get("transitions", {})
    palette = tr.get("palette") or (None if tr.get("type") else DEFAULT_PALETTE)
    legacy = normalize(tr.get("type")) if not palette else None
    if not palette:  # old style files: one transition type + "at"
        palette = {k: [legacy or "dissolve"] for k in ("calm", "medium", "intense")}
        density = {"all": 1.0, "sections": 0.0, "none": 0.0}.get(tr.get("at", "none"), 0.0)
        force_sections = tr.get("at") in ("sections", "all")
    else:
        density = float(tr.get("density", 0.5))  # share of ordinary cuts that get a transition
        force_sections = tr.get("at", "sections") != "none"
    speed = float(tr.get("speed", 1.0) or 1.0)
    last = None
    side = 0
    for i, e in enumerate(segs):
        e["trans_out"], e["trans_dur"], e["trans_params"] = None, 0.0, {}
        if i == len(segs) - 1:
            break
        nxt = segs[i + 1]
        changed = nxt["level"] != e["level"]
        want = (force_sections and (changed or nxt.get("drop"))) or \
            _stable_rand(e["shot_id"], nxt["shot_id"], i, *([style["shots"]["variant"]] if style.get("shots", {}).get("variant") else [])) < density
        if not want:
            last = None
            continue
        opts = [normalize(x) for x in palette.get(nxt["level"], [])]
        opts = [o for o in opts if o] or ["dissolve"]
        if nxt.get("drop"):
            opts = [o for o in opts if o in ("flash", "zoom_in", "spin", "glitch")] or opts
        if len(opts) > 1 and last in opts:
            opts = [o for o in opts if o != last]
        name = opts[int(_stable_rand("pick", e["shot_id"], nxt["shot_id"], i) * len(opts)) % len(opts)]
        d = NATURAL.get(name, 0.4) * speed
        room = 0.9 * min(e["dur"], nxt["dur"])  # window is centred on the cut: d/2 into each shot
        if d > room:
            if room >= NATURAL["flash"] * speed:
                d = room
            else:
                continue
        frames = max(2, int(round(d * OUT_FPS / 2)) * 2)  # even -> handles are whole frames
        params = {}
        if name == "whip":
            params["direction"] = ["left", "right", "up", "left"][side % 4]
            side += 1
        elif name == "spin":
            params["clockwise"] = bool(side % 2)
            side += 1
        elif name == "glitch":
            params["seed"] = i
        e["trans_out"], e["trans_dur"], e["trans_params"] = name, round(frames / OUT_FPS, 4), params
        last = name


def _behind_wanted(style: dict) -> bool:
    from .typo import PRESETS
    loc = style["text"].get("location") or {}
    val = loc.get("behind")
    if val is None:
        val = PRESETS.get(str(style["text"].get("preset", "bold")), PRESETS["bold"])["location"].get("behind", "off")
    return str(val).lower() in ("auto", "on", "true")


def add_location_overlays(plan: dict, shots_by_id: dict, places: dict[str, str], style: dict,
                          override: str | None = None) -> None:
    cfg = style["text"]["location"]
    mode = cfg.get("mode", "first")
    want_d = float(cfg.get("duration", 2.6))
    hook_end = max([o["start"] + o["duration"] for o in plan["overlays"] if o["type"] == "hook"] or [0.0])
    want_coords = cfg.get("coords", True)
    behind = _behind_wanted(style)
    segs = plan["segments"]

    def gps_of(seg):
        g = shots_by_id.get(seg["shot_id"], {}).get("gps")
        return [round(g[0], 2), round(g[1], 2)] if (g and want_coords) else None

    def slot(after: float, seg_from: int = 0):
        """(start, duration, segment). For a title tucked behind the skyline, the title must
        start with a shot and end with it (another shot's skyline would re-cut the letters)."""
        if behind:
            for seg in segs[seg_from:]:
                if seg["out_start"] + 0.01 >= after and seg["dur"] >= 1.5 and not seg.get("panel"):
                    return seg["out_start"] + 0.05, min(want_d, seg["dur"] - 0.12), seg
        st = max(after, segs[seg_from]["out_start"] + 0.15 if seg_from else after)
        # don't start a title on a split screen: move it to the next full-screen shot
        for x in segs:
            if x["out_start"] <= st < x["out_start"] + x["dur"] and x.get("panel"):
                st = x["out_start"] + x["dur"] + 0.05
        seg = next((x for x in segs if x["out_start"] <= st < x["out_start"] + x["dur"]), segs[-1])
        return st, min(want_d, plan["duration"] - st - 0.3), seg

    if override:
        st, du, seg = slot(hook_end + 0.25 if hook_end else 0.4)
        gps = gps_of(seg) or next((gps_of(x) for x in segs if gps_of(x)), None)
        if du > 0.8:
            plan["overlays"].append({"type": "location", "text": override, "start": round(st, 3), "gps": gps,
                                     "duration": round(du, 3)})
        return
    if mode == "off":
        return
    last = None
    for i, seg in enumerate(segs):
        name = places.get(seg["shot_id"])
        if not name or name == last:
            continue
        prev_end = max([o["start"] + o["duration"] for o in plan["overlays"]] or [0.0])
        st, du, at = slot(max(seg["out_start"], prev_end + 0.25 if prev_end else 0.0), i)
        if st > plan["duration"] - 1.5 or du < 0.8:
            break
        plan["overlays"].append({"type": "location", "text": name, "start": round(st, 3), "gps": gps_of(at),
                                 "duration": round(du, 3)})
        last = name
        if mode == "first":
            break