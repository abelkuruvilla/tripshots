"""Your reels as projects: pinned, favourite, filed in collections (a trip, a client, a series), renamed,
duplicated or deleted, everything that belongs to one reel moving with it.

A reel is its NAME.plan.json and the files next to it named NAME.* (the mp4, cover, storyboard, caption, sound
sheet, draft, the NAME.carousel/ and NAME.edits/ folders). Flags and collections live in ~/.tripshots/projects.json,
keyed by the plan's path; the undo history (~/.tripshots/undo), shown-before memory (history.json) and results
(results.json) follow a rename. Deleting moves the files to the Trash (macOS) or ~/.tripshots/trash, never deletes.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .config import HOME
from .util import ReelError, read_json, write_json

STORE = HOME / "projects.json"


def _load() -> dict:
    d = read_json(STORE, {}) or {}
    return {"reels": d.get("reels") or {}, "collections": d.get("collections") or []}


def _save(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    write_json(STORE, d)


def _key(plan: Path) -> str:
    return str(Path(plan).expanduser().resolve())


def base(plan: Path) -> Path:
    plan = Path(plan)
    if not plan.name.endswith(".plan.json"):
        raise ReelError(f"not a TripShots plan file: {plan}")
    return plan.with_name(plan.name[:-len(".plan.json")])


def files(plan: Path) -> list[Path]:
    """Everything that belongs to the reel: NAME.plan.json, NAME.mp4, NAME.cover.jpg, NAME.carousel/ ..."""
    b = base(plan)
    return sorted(b.parent.glob(glob_escape(b.name) + ".*"))


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


def flags(plan: Path) -> dict:
    return dict(_load()["reels"].get(_key(plan)) or {})


def annotate(cards: list[dict]) -> list[dict]:
    """The gallery's reels with their pins, favourites and collections; pinned first."""
    d = _load()["reels"]
    for c in cards:
        f = d.get(_key(Path(c["plan"]))) or {}
        c.update({"pinned": bool(f.get("pinned")), "favorite": bool(f.get("favorite")),
                  "collection": f.get("collection")})
    return sorted(cards, key=lambda c: (not c["pinned"], -c.get("modified", 0)))


def collections() -> list[str]:
    d = _load()
    named = {f.get("collection") for f in d["reels"].values() if f.get("collection")}
    return sorted(set(d["collections"]) | named, key=str.lower)


def _set(plan: Path, **kv) -> dict:
    d = _load()
    f = dict(d["reels"].get(_key(plan)) or {})
    for k, v in kv.items():
        if v in (None, False, ""):
            f.pop(k, None)
        else:
            f[k] = v
    if f:
        d["reels"][_key(plan)] = f
    else:
        d["reels"].pop(_key(plan), None)
    if kv.get("collection") and kv["collection"] not in d["collections"]:
        d["collections"].append(kv["collection"])
    _save(d)
    return f


def _move_records(old: Path, new: Path) -> None:
    """A renamed reel keeps its flags, undo history, shown-before memory and results."""
    d = _load()
    if _key(old) in d["reels"]:
        d["reels"][_key(new)] = d["reels"].pop(_key(old))
        _save(d)
    from .planedit import _history
    h_old, h_new = _history(old), _history(new)
    if h_old.exists() and not h_new.exists():
        h_new.parent.mkdir(parents=True, exist_ok=True)
        h_old.rename(h_new)
    ob, nb = str(base(old).resolve()), str(base(new).resolve())
    for store, field in ((HOME / "history.json", "out"), (HOME / "results.json", "reel")):
        rows = read_json(store, None)
        if not isinstance(rows, list):
            continue
        changed = False
        for r in rows:
            v = r.get(field) if isinstance(r, dict) else None
            if isinstance(v, str) and (v == ob + ".mp4" or v.startswith(ob + ".")):
                r[field] = nb + v[len(ob):]
                changed = True
            if isinstance(r, dict) and isinstance(r.get("plan"), str) and r["plan"].startswith(ob + "."):
                r["plan"] = nb + r["plan"][len(ob):]
                changed = True
        if changed:
            write_json(store, rows)


def _free_name(folder: Path, name: str) -> str:
    name = re.sub(r"[\\/:\0]+", "-", name).strip(" .") or "reel"
    out, k = name, 2
    while any(folder.glob(glob_escape(out) + ".*")):
        out, k = f"{name} {k}", k + 1
    return out


def rename(plan: Path, new_name: str) -> Path:
    plan = Path(plan)
    b = base(plan)
    new_name = re.sub(r"[\\/:\0]+", "-", str(new_name)).strip(" .")
    if not new_name or "." in new_name:
        raise ReelError("a reel's name can't be empty or contain a dot")
    if new_name == b.name:
        return plan
    if any(plan.parent.glob(glob_escape(new_name) + ".*")):
        raise ReelError(f"there is already a reel called {new_name} in that folder")
    new_plan = plan.with_name(new_name + ".plan.json")
    for f in files(plan):
        f.rename(f.with_name(new_name + f.name[len(b.name):]))
    _move_records(plan, new_plan)
    return new_plan


def duplicate(plan: Path, name: str | None = None) -> Path:
    """A copy of the reel's plan (and its storyboard and caption) to try something else; render it to get a video."""
    plan = Path(plan)
    b = base(plan)
    new = _free_name(plan.parent, name or f"{b.name} copy")
    for ext in (".plan.json", ".storyboard.jpg", ".caption.txt", ".social.json", ".edl", ".storyboard.md"):
        src = Path(str(b) + ext)
        if src.exists():
            shutil.copy2(src, plan.with_name(new + ext))
    out = plan.with_name(new + ".plan.json")
    f = flags(plan)
    if f.get("collection"):
        _set(out, collection=f["collection"])
    return out


def trash(plan: Path) -> list[str]:
    """Move every file of the reel to the Trash (or ~/.tripshots/trash); returns where they went."""
    plan = Path(plan)
    mac = Path.home() / ".Trash"
    dest = mac if mac.is_dir() else HOME / "trash" / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for f in files(plan):
        to = dest / f.name
        if to.exists():
            to = dest / f"{f.stem} {time.strftime('%H%M%S')}{''.join(f.suffixes[-1:])}"
        shutil.move(str(f), str(to))
        moved.append(str(to))
    _set(plan, pinned=None, favorite=None, collection=None)
    return moved


def collection(action: str, name: str, to: str | None = None) -> list[str]:
    """Collections themselves: add an empty one, rename one (its reels follow), or remove one (its reels stay,
    outside any collection). Returns the collections."""
    name = str(name or "").strip()
    if not name:
        raise ReelError("a collection needs a name")
    d = _load()
    if action == "add":
        if name not in d["collections"]:
            d["collections"].append(name)
    elif action in ("rename", "remove"):
        new = str(to or "").strip() if action == "rename" else None
        if action == "rename" and not new:
            raise ReelError("rename to what?")
        d["collections"] = [c for c in d["collections"] if c != name] + ([new] if new and new not in d["collections"] else [])
        for f in d["reels"].values():
            if f.get("collection") == name:
                if new:
                    f["collection"] = new
                else:
                    f.pop("collection")
        d["reels"] = {k: v for k, v in d["reels"].items() if v}
    else:
        raise ReelError("collection action: add, rename or remove")
    _save(d)
    return collections()


def manage(plan: Path, action: str, value=None) -> dict:
    """One action on a reel: pin, unpin, favorite, unfavorite, collection (value: name or null), rename (value),
    duplicate (value: optional name), delete. Returns {plan, ...}."""
    plan = Path(plan)
    if not plan.is_file():
        raise ReelError(f"no such reel: {plan}")
    if action in ("pin", "unpin"):
        return {"plan": str(plan), **_set(plan, pinned=action == "pin")}
    if action in ("favorite", "unfavorite"):
        return {"plan": str(plan), **_set(plan, favorite=action == "favorite")}
    if action == "collection":
        name = str(value).strip() if value else None
        return {"plan": str(plan), **_set(plan, collection=name)}
    if action == "rename":
        return {"plan": str(rename(plan, str(value or "")))}
    if action == "duplicate":
        return {"plan": str(duplicate(plan, value))}
    if action == "delete":
        return {"plan": str(plan), "trashed": trash(plan)}
    raise ReelError(f"unknown action {action} (pin, unpin, favorite, unfavorite, collection, rename, duplicate, delete)")
