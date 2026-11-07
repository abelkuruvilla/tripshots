"""tripshots app: a full-screen terminal UI (Textual, MIT licence) over the CLI.

Run `tripshots` with no arguments. Every job runs the CLI in a subprocess, so the UI stays
responsive, shows live progress and can cancel. Choices are remembered in ~/.tripshots/tui.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, Collapsible, DataTable, DirectoryTree, Footer, Header, Input, Label,
                             ListItem, ListView, ProgressBar, RichLog, Select, Static, Switch, TabbedContent,
                             TabPane, TextArea)

from .config import HOME, USER_STYLES, list_styles, load_style

STATE_PATH = HOME / "tui.json"
ENV_PATH = HOME / ".env"
IS_MAC = platform.system() == "Darwin"
DEFAULT_OUT = (Path.home() / "Movies" / "Reels") if IS_MAC else (Path.home() / "reels")
PRESETS = ["bold", "editorial", "minimal", "handwritten", "typewriter"]


def look_names() -> list[str]:
    try:
        from .grade import list_looks
        return list(list_looks())
    except Exception:
        return []
BROWSERS = ["chrome", "safari", "firefox", "brave", "edge", "arc"]
AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".mp4", ".mov")


# ---------------------------------------------------------------- helpers
def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=2))


def remember(st: dict, key: str, value: str, n: int = 12) -> None:
    lst = [v for v in st.get(key, []) if v != value]
    st[key] = [value] + lst[: n - 1]


from .config import read_env, write_env  # noqa: E402  (moved: also used by the MCP server)


def open_path(p: str | Path, reveal: bool = False) -> None:
    p = str(p)
    if IS_MAC:
        subprocess.Popen(["open", "-R", p] if reveal else ["open", p])
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(Path(p).parent) if reveal else p])


def blank(v):
    return None if v in (Select.BLANK, Select.NULL) or v is None or v == "" else v


def fmt_secs(s) -> str:
    try:
        return f"{float(s):.1f}s"
    except (TypeError, ValueError):
        return "?"


def find_reels(st: dict) -> list[Path]:
    seen, out = set(), []
    roots = [Path(st.get("out_dir") or DEFAULT_OUT), Path.cwd() / "reels"]
    cands = [Path(p) for p in st.get("reels", [])]
    for r in roots:
        if r.exists():
            cands += list(r.glob("*.plan.json")) + list(r.glob("*/*.plan.json"))
    for p in cands:
        rp = p.resolve()
        if rp.exists() and rp not in seen:
            seen.add(rp)
            out.append(rp)
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def reel_files(plan: Path) -> dict:
    base = str(plan)[: -len(".plan.json")]
    f = {k: Path(base + ext) for k, ext in [("video", ".mp4"), ("upload", ".noaudio.mp4"), ("cover", ".cover.jpg"),
                                             ("storyboard", ".storyboard.jpg"), ("caption", ".caption.txt")]}
    return {k: v for k, v in f.items() if v.exists()} | {"plan": plan}


# ------------------------------------------------------------- run screen
class RunScreen(ModalScreen[dict | None]):
    """Runs one tripshots command, streams its log, shows progress and the results."""

    BINDINGS = [Binding("escape", "close", "Close")]
    STAGES = [("reading metadata", "Reading your files"), ("analyzing", "Analysing footage"),
              ("AI", "Asking the AI about your shots"), ("batch", "Asking the AI about your shots"),
              ("analyzing music", "Finding the beat"), ("downloading", "Downloading"),
              ("plan:", "Planning the edit"), ("rendering", "Rendering shots"),
              ("colourist", "AI colourist grading each shot"), ("cutting the reference", "Studying the reel"),
              ("reading reference", "AI reading the reel's shots and text"), ("matching", "AI matching your shots"),
              ("variant", "Making the next version"), ("beat check", "Checking the cuts"),
              ("sound design", "Placing sound effects on the cuts"), ("fetching real sound", "Fetching sounds"), ("route map", "Drawing the route map"), ("grade:", "Colour grading"),
              ("compositing", "Adding transitions, motion and text"), ("measuring", "Studying the reference"),
              ("done", "Finished")]

    def __init__(self, title: str, args: list[str]):
        super().__init__()
        self.title_text, self.args = title, args
        self.proc = None
        self.result: dict | None = None
        self.out_text: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="run_box"):
            yield Label(self.title_text, id="run_title")
            yield Label("Starting…", id="run_stage")
            yield ProgressBar(id="run_progress", show_eta=False)
            yield RichLog(id="run_log", wrap=True, markup=True)
            with Horizontal(id="run_results"):
                pass
            with Horizontal(id="run_buttons"):
                yield Button("Cancel", id="run_cancel", variant="error")
                yield Button("Close", id="run_close", disabled=True)

    def on_mount(self) -> None:
        self.run_job()

    @work(exclusive=True)
    async def run_job(self) -> None:
        log = self.query_one("#run_log", RichLog)
        stage = self.query_one("#run_stage", Label)
        bar = self.query_one("#run_progress", ProgressBar)
        cmd = [sys.executable, "-m", "tripshots"] + self.args
        log.write(f"[dim]$ tripshots {' '.join(self.args)}[/dim]")
        self.proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.STDOUT,
                                                         env={**os.environ, "PYTHONUNBUFFERED": "1"})
        assert self.proc.stdout
        while True:
            raw = await self.proc.stdout.readline()
            if not raw:
                break
            line = raw.decode(errors="ignore").rstrip()
            if line.startswith("[tripshots]"):
                msg = line[len("[tripshots]"):].strip()
                style = "red" if "error" in msg.lower() or "failed" in msg.lower() else ""
                log.write(f"[{style}]{msg}[/{style}]" if style else msg)
                for key, label in self.STAGES:
                    if key in msg:
                        stage.update(label)
                        break
                m = re.search(r"(\d+)/(\d+)", msg)
                if m:
                    bar.update(total=int(m.group(2)), progress=int(m.group(1)))
            else:
                self.out_text.append(line)
                if line.strip() and not line.strip().startswith(("{", "}", "[", "]", '"')):
                    log.write(line)
        rc = await self.proc.wait()
        text = "\n".join(self.out_text)
        try:
            start = text.index("{")
            self.result = json.loads(text[start:text.rindex("}") + 1])
        except ValueError:
            self.result = {"output": text.strip()} if text.strip() else {}
        bar.update(total=1, progress=1)
        if rc == 0:
            stage.update("[b green]✓ Done[/]")
        else:
            stage.update(f"[b red]✗ Stopped (exit {rc})[/] — see the log above")
            self.result = None
        self.query_one("#run_cancel", Button).disabled = True
        self.query_one("#run_close", Button).disabled = False
        self.show_results()

    def show_results(self) -> None:
        box = self.query_one("#run_results", Horizontal)
        r = self.result or {}
        if r.get("video"):
            box.mount(Button("▶ Play", id="r_play", variant="success"))
        if r.get("upload_video"):
            box.mount(Button("Upload copy", id="r_upload"))
        if r.get("storyboard"):
            box.mount(Button("Storyboard", id="r_story"))
        if r.get("caption"):
            box.mount(Button("Copy caption", id="r_caption"))
        if r.get("plan") and not r.get("video"):
            box.mount(Button("Render this plan", id="r_render", variant="primary"))
        if r.get("video") or r.get("plan"):
            box.mount(Button("Show in Finder" if IS_MAC else "Open folder", id="r_reveal"))
        if r.get("plan") and not r.get("variants"):
            box.mount(Button("Send to Edits", id="r_edits"))
        if r.get("media") and str(r.get("media")).endswith("media.jsonl"):
            box.mount(Button("Open the analysis", id="r_analysis", variant="success"))
            self.query_one("#run_log", RichLog).write(
                f"\n[b]Analysed[/b] {r.get('files')} files, {r.get('shots')} shots "
                f"({r.get('described_by_ai')} described by AI).")
        if r.get("package"):
            box.mount(Button("Open the package", id="r_pkg", variant="success"))
            from .edits import PROFILE
            from .util import read_json
            if (read_json(PROFILE) or {}).get("confirmed"):
                box.mount(Button("Build it in Edits", id="r_push", variant="primary"))
            else:
                self.query_one("#run_log", RichLog).write(
                    "\n[b]Next:[/b] in Edits, add picture.mp4 (or the clips), the texts, sound-effects.wav and the song "
                    "(README.txt in the package lists the times). To have TripShots do it, see docs/edits.md.")
        if r.get("folder"):
            box.mount(Button(f"Open folder ({len(r.get('frames', []))} images)", id="r_folder", variant="success"))
            if r.get("skipped"):
                self.query_one("#run_log", RichLog).write(f"[yellow]Skipped (no clear subject): "
                                                         f"{', '.join(r['skipped'])}[/yellow]")
        if r.get("compare"):
            box.mount(Button("Compare" if not r.get("variants") else "Compare versions", id="r_compare"))
        for k, v in enumerate(r.get("variants") or []):
            if v.get("video"):
                box.mount(Button(f"▶ v{k + 1}", id=f"r_v{k}", variant="success"))
        if r.get("variants") and not any(v.get("video") for v in r["variants"]):
            box.mount(Button("Render all versions", id="r_render_all", variant="primary"))
        if r.get("variants"):
            box.mount(Button("Show in Finder" if IS_MAC else "Open folder", id="r_reveal_v"))
            hooks = [f"v{k + 1}: {v.get('hook') or '(no hook)'}" for k, v in enumerate(r["variants"])]
            self.query_one("#run_log", RichLog).write("\n[b]Versions[/b]\n" + "\n".join(hooks))
        if r.get("beat_check"):
            bc = r["beat_check"]
            self.query_one("#run_log", RichLog).write(
                f"[dim]beat check: {bc.get('within_1_frame')}/{bc.get('measured')} cuts within 1 frame[/dim]")
        if r.get("sound"):
            self.query_one("#run_log", RichLog).write(f"\n[b]{r['sound']}[/b]")
        log = self.query_one("#run_log", RichLog)
        if r.get("understood"):
            u = r["understood"]
            log.write(f"\n[b]Understood:[/b] {u.get('summary', '')}")
        if r.get("found"):
            f = r["found"]
            days = ", ".join(f"{d} ({n})" for d, n in (f.get("days") or {}).items())
            log.write(f"[b]Found:[/b] {f.get('count')} files ({f.get('photos')} photos, {f.get('videos')} videos)"
                      + (f" · {days}" if days else "") + "".join(f"\n  [dim]{n}[/dim]" for n in f.get("notes", [])))
            if f.get("sheet"):
                box.mount(Button("See what it found", id="r_sheet"))
        if r.get("question"):
            log.write(f"\n[b yellow]{r['question']}[/b yellow]\n[dim]Change the request and try again.[/dim]")
        if r.get("sheet") and not r.get("found"):
            box.mount(Button("Open the sheet", id="r_sheet"))
        if isinstance(r.get("trips"), list):
            for t in r["trips"]:
                log.write(f"{t['from']} → {t['to']}  {t['files']} files  {', '.join(t.get('places') or []) or ''}")
        if r.get("output") and not r.get("media"):  # raw (non-JSON) command output
            log.write(r["output"])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        r = self.result or {}
        bid = event.button.id
        if bid == "run_cancel" and self.proc and self.proc.returncode is None:
            self.proc.terminate()
            self.query_one("#run_stage", Label).update("Cancelling…")
        elif bid == "run_close":
            self.dismiss(self.result)
        elif bid == "r_play":
            open_path(r["video"])
        elif bid == "r_upload":
            open_path(r["upload_video"], reveal=True)
        elif bid == "r_story":
            open_path(r["storyboard"])
        elif bid == "r_caption":
            self.app.copy_text(Path(r["caption"]).read_text())
        elif bid == "r_reveal":
            open_path(r.get("video") or r["plan"], reveal=True)
        elif bid == "r_folder":
            open_path(r["folder"])
        elif bid == "r_render":
            self.dismiss({**r, "_render": True})
        elif bid == "r_analysis":
            open_path(r["output"])
        elif bid == "r_edits":
            self.app.push_screen(RunScreen("Preparing it for Edits", ["edits", "package", r["plan"]]))
        elif bid == "r_pkg":
            open_path(r.get("staged") or r["package"])
        elif bid == "r_push":
            self.app.push_screen(RunScreen("Building the timeline in Edits", ["edits", "push", r["package"]]))
        elif bid == "r_compare":
            open_path(r["compare"])
        elif bid == "r_sheet":
            open_path((r.get("found") or {}).get("sheet") or r["sheet"])
        elif bid and bid.startswith("r_v") and bid[3:].isdigit():
            open_path(r["variants"][int(bid[3:])]["video"])
        elif bid == "r_reveal_v":
            v = r["variants"][0]
            open_path(v.get("video") or v["plan"], reveal=True)
        elif bid == "r_render_all":
            self.dismiss({**r, "_render": True})

    def action_close(self) -> None:
        if self.proc is None or self.proc.returncode is not None:
            self.dismiss(self.result)


# ------------------------------------------------------------ small modals
class Confirm(ModalScreen[bool]):
    def __init__(self, question: str, yes: str = "Yes", danger: bool = False):
        super().__init__()
        self.q, self.yes, self.danger = question, yes, danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.q, classes="dialog_q")
            with Horizontal(classes="dialog_buttons"):
                yield Button(self.yes, id="yes", variant="error" if self.danger else "primary")
                yield Button("Cancel", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class PickPath(ModalScreen[str | None]):
    """Browse for a folder (or a file) instead of typing a path."""

    def __init__(self, want_file: bool = False, start: str | None = None):
        super().__init__()
        self.want_file = want_file
        self.start = Path(start).expanduser() if start and Path(start).expanduser().exists() else Path.home()
        self.choice: Path | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label("Choose a file" if self.want_file else "Choose a folder (Enter opens, Select picks)",
                        classes="dialog_q")
            with Horizontal(classes="roots"):
                yield Button("Home", id="root_home")
                if IS_MAC and Path("/Volumes").exists():
                    yield Button("Drives", id="root_volumes")
                yield Button("Up", id="root_up")
            yield DirectoryTree(str(self.start), id="tree")
            yield Label(str(self.start), id="picked")
            with Horizontal(classes="dialog_buttons"):
                yield Button("Select", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def _set_root(self, p: Path) -> None:
        tree = self.query_one("#tree", DirectoryTree)
        tree.path = p
        self.choice = None if self.want_file else p
        self.query_one("#picked", Label).update(str(p))

    @on(DirectoryTree.DirectorySelected)
    def dir_sel(self, e: DirectoryTree.DirectorySelected) -> None:
        if not self.want_file:
            self.choice = Path(e.path)
            self.query_one("#picked", Label).update(str(e.path))

    @on(DirectoryTree.FileSelected)
    def file_sel(self, e: DirectoryTree.FileSelected) -> None:
        if self.want_file:
            self.choice = Path(e.path)
            self.query_one("#picked", Label).update(str(e.path))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        tree = self.query_one("#tree", DirectoryTree)
        if bid == "root_home":
            self._set_root(Path.home())
        elif bid == "root_volumes":
            self._set_root(Path("/Volumes"))
        elif bid == "root_up":
            self._set_root(Path(tree.path).parent)
        elif bid == "ok":
            pick = self.choice or (None if self.want_file else Path(tree.path))
            self.dismiss(str(pick) if pick else None)
        else:
            self.dismiss(None)


class EditText(ModalScreen[dict | None]):
    """Change the on-screen words of a finished reel, then re-render."""

    def __init__(self, plan: dict):
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog wide"):
            yield Label("Edit the text on screen. Empty = remove it.", classes="dialog_q")
            kinds = {o["type"]: o for o in self.plan.get("overlays", [])}
            for kind, label in [("hook", "Opening hook"), ("location", "Location"), ("cta", "Closing line")]:
                o = kinds.get(kind)
                yield Label(label, classes="field_label")
                yield Input(o["text"] if o else "", id=f"t_{kind}",
                            placeholder="(not in this reel; type to add)" if not o else "")
            yield Label("Text style", classes="field_label")
            cur = (self.plan.get("text") or {}).get("preset", "bold")
            yield Select([(p, p) for p in PRESETS], value=cur if cur in PRESETS else "bold", id="t_preset",
                         allow_blank=False)
            with Horizontal(classes="dialog_buttons"):
                yield Button("Save & re-render", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "ok":
            self.dismiss(None)
            return
        plan = self.plan
        ovs = {o["type"]: o for o in plan.get("overlays", [])}
        dur = float(plan.get("duration", 10))
        new = []
        for kind in ("hook", "location", "cta"):
            txt = self.query_one(f"#t_{kind}", Input).value.strip()
            if not txt:
                continue
            o = dict(ovs.get(kind) or {})
            if not o:
                o = {"type": kind, "start": {"hook": 0.2, "location": 3.0, "cta": max(0.0, dur - 2.3)}[kind],
                     "duration": 2.6 if kind != "cta" else 2.2}
            o["text"] = txt
            for k in ("main", "sub"):  # recomputed from the text
                o.pop(k, None)
            new.append(o)
        # keep everything this dialog doesn't edit (shot labels, route maps)
        new += [o for o in plan.get("overlays", []) if o["type"] not in ("hook", "location", "cta")]
        plan["overlays"] = new
        plan.setdefault("text", {})["preset"] = self.query_one("#t_preset", Select).value
        self.dismiss(plan)


class EditStyle(ModalScreen[dict | None]):
    FIELDS = [  # (label, path, kind, options)
        ("Description", ("description",), "text", None),
        ("Length (seconds)", ("duration", "target"), "num", None),
        ("Text style", ("text", "preset"), "sel", PRESETS),
        ("Opening hook", ("text", "hook", "mode"), "sel", ["off", "ai"]),
        ("Location title", ("text", "location", "mode"), "sel", ["off", "first", "each"]),
        ("Title behind mountains", ("text", "location", "behind"), "sel", ["auto", "on", "off"]),
        ("Show GPS coordinates", ("text", "location", "coords"), "bool", None),
        ("Closing line (CTA)", ("text", "cta", "mode"), "sel", ["off", "ai"]),
        ("Share of cuts with a transition (0-1)", ("transitions", "density"), "num", None),
        ("Transition speed (<1 snappier)", ("transitions", "speed"), "num", None),
        ("Zoom punch on beats (0-0.1)", ("motion", "beat_punch"), "num", None),
        ("Split screens / grids (0 never … 1 often)", ("panels", "use"), "num", None),
        ("Split screen behaviour", ("panels", "mode"), "sel", ["mixed", "reveal", "cycle"]),
        ("Speed ramps on moving clips (0-1)", ("velocity", "use"), "num", None),
        ("Bass-hit pulse (0-0.15)", ("motion", "pulse"), "num", None),
        ("Label on each shot", ("text", "labels", "mode"), "sel", ["off", "ai"]),
        ("Seamless loop ending", ("loop",), "bool", None),
        ("Shake on the drop", ("motion", "shake_on_drop"), "bool", None),
        ("Colour look (auto = AI picks)", ("grade", "look"), "sel", None),
        ("Route map (needs Node.js)", ("route_map", "mode"), "sel", ["off", "intro", "tracker", "both"]),
        ("Sound effects", ("sound", "sfx"), "sel", ["on", "off"]),
        ("Ambience under each place", ("sound", "ambience"), "sel", ["on", "off"]),
        ("Sound effects level (dB, -6 … +6)", ("sound", "level_db"), "num", None),
        ("Colour look strength (0-1)", ("grade", "strength"), "num", None),
        ("Colour saturation, when look is none (1 = natural)", ("color", "saturation"), "num", None),
        ("Warmth, when look is none (-0.15 … 0.15)", ("color", "warmth"), "num", None),
        ("Photo zoom (1.0-1.25)", ("layout", "photo_zoom"), "num", None),
    ]

    def __init__(self, name: str, style: dict, builtin: bool):
        super().__init__()
        self.sname, self.style, self.builtin = name, style, builtin

    def _get(self, path):
        d = self.style
        for k in path:
            if not isinstance(d, dict):
                return None
            d = d.get(k)
        return d

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog wide"):
            yield Label(f"Edit style “{self.sname}”" + ("  (built-in: saved as your own copy)" if self.builtin else ""),
                        classes="dialog_q")
            yield Label("Save as", classes="field_label")
            yield Input(self.sname, id="s_name")
            for i, (label, path, kind, opts) in enumerate(self.FIELDS):
                yield Label(label, classes="field_label")
                v = self._get(path)
                if kind == "sel":
                    if opts is None:  # colour looks: listed live
                        opts = ["auto", "none"] + look_names()
                    v = str(v) if v is not None else opts[0]
                    yield Select([(o, o) for o in opts], value=v if v in opts else opts[0], id=f"f{i}",
                                 allow_blank=False)
                elif kind == "bool":
                    yield Switch(value=bool(v), id=f"f{i}")
                else:
                    yield Input("" if v is None else str(v), id=f"f{i}",
                                type="number" if kind == "num" else "text")
            with Horizontal(classes="dialog_buttons"):
                yield Button("Save", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "ok":
            self.dismiss(None)
            return
        data = {}
        for i, (label, path, kind, opts) in enumerate(self.FIELDS):
            w = self.query_one(f"#f{i}")
            if kind == "bool":
                v = w.value
            elif kind == "sel":
                v = w.value
            else:
                raw = w.value.strip()
                if raw == "":
                    continue
                v = float(raw) if kind == "num" else raw
                if kind == "num" and float(v).is_integer() and path[-1] == "target":
                    v = int(v)
            d = data
            for k in path[:-1]:
                d = d.setdefault(k, {})
            d[path[-1]] = v
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", self.query_one("#s_name", Input).value.strip()) or self.sname
        self.dismiss({"name": name, "data": data})


class LearnStyle(ModalScreen[dict | None]):
    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label("Learn a style from reels you like", classes="dialog_q")
            yield Label("Reel links or video files, one per line (2–3 similar reels work best)", classes="field_label")
            yield TextArea(id="l_urls")
            yield Label("Name for the style", classes="field_label")
            yield Input(placeholder="e.g. moody-coast", id="l_name")
            with Horizontal(classes="dialog_buttons"):
                yield Button("Learn", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "ok":
            self.dismiss(None)
            return
        refs = [x.strip() for x in self.query_one("#l_urls", TextArea).text.splitlines() if x.strip()]
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", self.query_one("#l_name", Input).value.strip())
        if not refs or not name:
            self.notify("Add at least one link and a name", severity="warning")
            return
        self.dismiss({"refs": refs, "name": name})


# ------------------------------------------------------------------- tabs
class MakeTab(VerticalScroll):
    def compose(self) -> ComposeResult:
        st = self.app.state
        yield Static("[b]1 · Your footage[/b]  [dim]folders are searched inside too; add as many as you like[/dim]",
                     classes="section")
        yield ListView(*[ListItem(Label(s)) for s in st.get("sources", [])], id="sources")
        with Horizontal(classes="row"):
            yield Input(placeholder="Folder path — or drag a folder from Finder here and press Enter", id="src_input")
            yield Button("Add", id="src_add")
            yield Button("Browse…", id="src_browse")
            yield Button("Remove", id="src_remove", variant="warning")
        recents = [s for s in st.get("recent_sources", []) if s not in st.get("sources", [])]
        yield Select([(r, r) for r in recents], prompt="Recent folders…", id="src_recent")

        yield Static("[b]2 · Music[/b]  [dim]an Instagram reel link (uses its sound) or an audio file[/dim]",
                     classes="section")
        with Horizontal(classes="row"):
            yield Input(st.get("music", ""), placeholder="https://www.instagram.com/reel/…  or  /path/song.mp3",
                        id="music")
            yield Button("Browse…", id="music_browse")
        yield Select([(m, m) for m in st.get("recent_music", [])], prompt="Recent music…", id="music_recent")

        yield Static("[b]3 · Look[/b]", classes="section")
        styles = list_styles()
        cur = st.get("style") if st.get("style") in styles else ("beat-montage" if "beat-montage" in styles
                                                                 else next(iter(styles), None))
        yield Select([(n, n) for n in styles], value=cur, id="style", allow_blank=False)
        yield Static("", id="style_desc", classes="hint")
        with Horizontal(classes="row"):
            yield Select([("Text: style default", "")] + [(f"Text: {p}", p) for p in PRESETS], value="",
                         id="preset", allow_blank=False)
            yield Select([("Title behind mountains: auto", ""), ("behind: always", "on"), ("behind: never", "off")],
                         value="", id="behind", allow_blank=False)
            yield Input(placeholder="Length (s), empty = style", id="duration", type="number")
        with Horizontal(classes="row"):
            yield Select([("Split screens: style default", ""), ("Split screens: lots", "lots"),
                          ("Split screens: some", "some"), ("Split screens: off", "off")],
                         value="", id="split", allow_blank=False)
            yield Select([("Speed ramps: style default", ""), ("Speed ramps: on", "on"), ("Speed ramps: off", "off")],
                         value="", id="ramps", allow_blank=False)
            yield Select([("Shot labels: style default", ""), ("Shot labels: AI", "ai"), ("Shot labels: off", "off")],
                         value="", id="labels", allow_blank=False)
        with Horizontal(classes="row"):
            yield Select([("Colour: style default", ""), ("Colour: AI picks the look", "auto"),
                          ("Colour: no grading", "none")] + [(f"Colour: {n}", n) for n in look_names()],
                         value="", id="look", allow_blank=False)
            yield Input(placeholder="Look strength 0-1 (empty = 0.75)", id="grade_strength", type="number")
            yield Select([("1 version", ""), ("2 versions", "2"), ("3 versions", "3"), ("4 versions", "4")],
                         value="", id="variants", allow_blank=False)
            yield Select([("Sound effects: style default", ""), ("Sound effects: on", "on"),
                          ("Sound effects: off", "off")], value="", id="sfx", allow_blank=False)
            yield Select([("Ambience: style default", ""), ("Ambience: on", "on"), ("Ambience: off", "off")],
                         value="", id="ambience", allow_blank=False)
            yield Select([("Route map: style default", ""), ("Route map: big card early on", "intro"),
                          ("Route map: corner tracker", "tracker"), ("Route map: both", "both"),
                          ("Route map: off", "off")], value="", id="route_map", allow_blank=False)

        yield Static("[b]4 · Words on screen[/b]  [dim]optional — empty lets the style/AI decide[/dim]",
                     classes="section")
        yield Input(placeholder="Opening hook, e.g. POV: you finally made it to Big Sur", id="hook")
        yield Input(placeholder="Location, e.g. Big Sur, California  (empty = from photo GPS)", id="location")

        with Collapsible(title="More options", collapsed=True, id="more"):
            with Horizontal(classes="row"):
                yield Input(placeholder="Only from date YYYY-MM-DD", id="since")
                yield Input(placeholder="Until date YYYY-MM-DD", id="until")
            yield Input(placeholder="Skip files/folders matching, comma separated, e.g. */timelapse/*, DJI_*.JPG",
                        id="exclude")
            with Horizontal(classes="row"):
                yield Input(placeholder="Lowest AI score to use (1-10)", id="min_score", type="number")
                yield Select([("AI: settings default", ""), ("AI: Claude (subscription)", "claude-cli"),
                              ("AI: MiniMax", "minimax"), ("AI: Claude API key", "api"), ("AI: none", "none")],
                             value="", id="backend", allow_blank=False)
            with Horizontal(classes="switches"):
                yield Switch(id="allow_similar")
                yield Label("Use similar/burst shots too")
                yield Switch(id="rescore")
                yield Label("Ask the AI again")
                yield Switch(id="no_location")
                yield Label("No location title")
        with Horizontal(classes="actions"):
            yield Button("See what the AI picks", id="scan")
            yield Button("Preview plan", id="preview")
            yield Button("Make reel", id="make", variant="primary")

    def on_mount(self) -> None:
        self.update_style_desc()

    def update_style_desc(self) -> None:
        name = blank(self.query_one("#style", Select).value)
        if not name:
            return
        try:
            s = load_style(name)
            t = s.get("text", {})
            self.query_one("#style_desc", Static).update(
                f"{s.get('description', '')}\n[dim]{s['duration']['target']}s · text {t.get('preset')} · "
                f"hook {t.get('hook', {}).get('mode')} · transitions {s['transitions'].get('density')}"
                f" · punch {s['motion'].get('beat_punch')}[/dim]")
        except Exception as e:
            self.query_one("#style_desc", Static).update(f"[red]{e}[/red]")

    @on(Select.Changed, "#style")
    def style_changed(self) -> None:
        self.update_style_desc()

    def sources(self) -> list[str]:
        return [str(item.query_one(Label).content) for item in self.query_one("#sources", ListView).children]

    def add_source(self, path: str) -> None:
        path = path.strip().strip("'\"").replace("\\ ", " ")
        if not path:
            return
        p = Path(path).expanduser()
        if not p.exists():
            self.notify(f"Not found: {path}", severity="error")
            return
        if str(p) in self.sources():
            return
        self.query_one("#sources", ListView).append(ListItem(Label(str(p))))
        self.query_one("#src_input", Input).value = ""

    @on(Input.Submitted, "#src_input")
    def src_submit(self, e: Input.Submitted) -> None:
        self.add_source(e.value)

    @on(Select.Changed, "#src_recent")
    def src_recent(self, e: Select.Changed) -> None:
        if blank(e.value):
            self.add_source(e.value)

    @on(Select.Changed, "#music_recent")
    def music_recent(self, e: Select.Changed) -> None:
        if blank(e.value):
            self.query_one("#music", Input).value = e.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "src_add":
            self.add_source(self.query_one("#src_input", Input).value)
        elif bid == "src_browse":
            self.app.push_screen(PickPath(start=(self.sources() or [None])[-1]),
                                 lambda p: p and self.add_source(p))
        elif bid == "src_remove":
            lv = self.query_one("#sources", ListView)
            if lv.index is not None and lv.children:
                lv.children[lv.index].remove()
        elif bid == "music_browse":
            self.app.push_screen(PickPath(want_file=True),
                                 lambda p: p and setattr(self.query_one("#music", Input), "value", p))
        elif bid in ("make", "preview", "scan"):
            self.start(bid)

    def start(self, kind: str) -> None:
        srcs = self.sources()
        pending = self.query_one("#src_input", Input).value.strip()
        if pending:
            self.add_source(pending)
            srcs = self.sources()
        if not srcs:
            self.notify("Add at least one footage folder first", severity="warning")
            return
        q = lambda i: self.query_one(f"#{i}")  # noqa: E731
        music = q("music").value.strip().strip("'\"")
        st = self.app.state
        st["sources"] = srcs
        for s in srcs:
            remember(st, "recent_sources", s)
        st["music"] = music
        if music:
            remember(st, "recent_music", music)
        st["style"] = blank(q("style").value)
        save_state(st)

        src_args = []
        if q("since").value.strip():
            src_args += ["--since", q("since").value.strip()]
        if q("until").value.strip():
            src_args += ["--until", q("until").value.strip()]
        for pat in [p.strip() for p in q("exclude").value.split(",") if p.strip()]:
            src_args += ["--exclude", pat]
        if q("rescore").value:
            src_args.append("--rescore")
        backend = blank(q("backend").value)
        if kind == "scan":
            args = ["scan", *srcs, "--top", "40", *src_args] + (["-b", backend] if backend else [])
            self.app.push_screen(RunScreen("What the AI thinks of your footage", args))
            return
        args = ["make", *srcs, "-s", st["style"]]
        if music:
            args += ["-m", music]
        for flag, wid in (("--hook", "hook"), ("--location", "location"), ("-d", "duration"),
                          ("--min-score", "min_score"), ("--grade-strength", "grade_strength")):
            v = q(wid).value.strip()
            if v:
                args += [flag, v]
        for flag, wid in (("--text-preset", "preset"), ("--behind", "behind"), ("--split-screens", "split"),
                          ("--speed-ramps", "ramps"), ("--labels", "labels"), ("--look", "look"),
                          ("--route-map", "route_map"), ("--variants", "variants"), ("--sfx", "sfx"),
                          ("--ambience", "ambience")):
            v = blank(q(wid).value)
            if v:
                args += [flag, v]
        if q("allow_similar").value:
            args.append("--allow-similar")
        if q("no_location").value:
            args.append("--no-location")
        if backend:
            args += ["-b", backend]
        args += src_args
        out_dir = Path(st.get("out_dir") or DEFAULT_OUT).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(srcs[0]).name)[:40] or "reel"
        out = out_dir / f"{name}-{st['style']}-{datetime.now():%Y%m%d-%H%M%S}.mp4"
        args += ["-o", str(out)]
        if kind == "preview":
            args.append("--dry-run")
        title = "Previewing the plan" if kind == "preview" else "Making your reel"
        self.app.push_screen(RunScreen(title, args), lambda r: self.app.after_job(r, out))


class ReelsTab(Horizontal):
    def compose(self) -> ComposeResult:
        with Vertical(id="reels_left"):
            yield DataTable(id="reels", cursor_type="row", zebra_stripes=True)
            yield Button("Refresh", id="reels_refresh")
        with VerticalScroll(id="reel_detail"):
            yield Static("Select a reel", id="reel_info")
            with Horizontal(classes="actions wrap"):
                yield Button("▶ Play", id="rv_play", variant="success")
                yield Button("Storyboard", id="rv_story")
                yield Button("Copy caption", id="rv_caption")
                yield Button("Show in Finder" if IS_MAC else "Open folder", id="rv_reveal")
            with Horizontal(classes="actions wrap"):
                yield Button("Edit text…", id="rv_edit", variant="primary")
                yield Button("Re-render", id="rv_render")
                yield Button("Delete", id="rv_delete", variant="error")

    def on_mount(self) -> None:
        t = self.query_one("#reels", DataTable)
        t.add_columns("Made", "Reel", "Style", "Length", "Shots", "")
        self.refresh_list()

    def refresh_list(self) -> None:
        t = self.query_one("#reels", DataTable)
        t.clear()
        self.plans = find_reels(self.app.state)
        for p in self.plans:
            try:
                plan = json.loads(p.read_text())
            except Exception:
                continue
            files = reel_files(p)
            t.add_row(datetime.fromtimestamp(p.stat().st_mtime).strftime("%b %d %H:%M"),
                      p.name[: -len(".plan.json")][:38], plan.get("style", "?"), fmt_secs(plan.get("duration")),
                      str(len(plan.get("segments", []))), "✓" if "video" in files else "plan", key=str(p))
        if not self.plans:
            self.query_one("#reel_info", Static).update("No reels yet. Make one in the Make tab.")

    def current(self) -> Path | None:
        t = self.query_one("#reels", DataTable)
        if t.row_count == 0:
            return None
        try:
            key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        except Exception:
            return None
        return Path(key) if key else None

    @on(DataTable.RowHighlighted, "#reels")
    def show(self) -> None:
        p = self.current()
        if not p or not p.exists():
            return
        plan = json.loads(p.read_text())
        files = reel_files(p)
        texts = "\n".join(f"  [b]{o['type']}[/b]: {o['text']}" for o in plan.get("overlays", [])) or "  (none)"
        cap = files["caption"].read_text().strip() if "caption" in files else "(no caption)"
        music = plan.get("music") or {}
        trans = sum(1 for s in plan.get("segments", []) if s.get("trans_out"))
        self.query_one("#reel_info", Static).update(
            f"[b]{p.name[:-len('.plan.json')]}[/b]\n"
            f"{fmt_secs(plan.get('duration'))} · {len(plan.get('segments', []))} shots · {trans} transitions · "
            f"{plan.get('tempo', '?')} BPM · style {plan.get('style')} · text {(plan.get('text') or {}).get('preset')}\n"
            f"music: {music.get('label') or Path(music.get('path') or '-').name}"
            f"{' (start ' + fmt_secs(music.get('start')) + ')' if music.get('path') else ''}\n\n"
            f"[b]On screen[/b]\n{texts}\n\n[b]Caption[/b]\n{cap}\n\n"
            f"[dim]{'rendered' if 'video' in files else 'plan only: press Re-render to make the video'} · "
            f"{p.parent}[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "reels_refresh":
            self.refresh_list()
            return
        p = self.current()
        if not p:
            return
        files = reel_files(p)
        if bid == "rv_play":
            if "video" in files:
                open_path(files["video"])
            else:
                self.notify("Not rendered yet — press Re-render", severity="warning")
        elif bid == "rv_story" and "storyboard" in files:
            open_path(files["storyboard"])
        elif bid == "rv_caption" and "caption" in files:
            self.app.copy_text(files["caption"].read_text())
        elif bid == "rv_reveal":
            open_path(files.get("video") or p, reveal=True)
        elif bid == "rv_render":
            self.app.push_screen(RunScreen("Rendering", ["render", str(p)]), lambda r: self.refresh_list())
        elif bid == "rv_edit":
            plan = json.loads(p.read_text())

            def saved(new):
                if new:
                    p.write_text(json.dumps(new, indent=2))
                    self.app.push_screen(RunScreen("Rendering with new text", ["render", str(p)]),
                                         lambda r: (self.refresh_list(), self.show()))
            self.app.push_screen(EditText(plan), saved)
        elif bid == "rv_delete":
            def gone(ok):
                if ok:
                    for f in files.values():
                        Path(f).unlink(missing_ok=True)
                    self.refresh_list()
            self.app.push_screen(Confirm(f"Delete {p.name[:-10]} and its files?", "Delete", True), gone)


class StylesTab(Horizontal):
    def compose(self) -> ComposeResult:
        with Vertical(id="styles_left"):
            yield DataTable(id="styles", cursor_type="row", zebra_stripes=True)
            with Horizontal(classes="actions wrap"):
                yield Button("Learn from reels…", id="st_learn", variant="primary")
        with VerticalScroll(id="style_detail"):
            yield Static("", id="style_info")
            with Horizontal(classes="actions wrap"):
                yield Button("Edit…", id="st_edit", variant="primary")
                yield Button("Use for next reel", id="st_use")
                yield Button("Open file", id="st_open")
                yield Button("Delete", id="st_delete", variant="error")

    def on_mount(self) -> None:
        self.query_one("#styles", DataTable).add_columns("Style", "Type", "About")
        self.refresh_list()

    def refresh_list(self) -> None:
        t = self.query_one("#styles", DataTable)
        t.clear()
        for name, path in list_styles().items():
            try:
                s = load_style(str(path))
            except Exception:
                continue
            kind = "yours" if USER_STYLES in path.parents else "built-in"
            t.add_row(name, kind, (s.get("description") or "")[:60], key=name)

    def current(self) -> str | None:
        t = self.query_one("#styles", DataTable)
        if t.row_count == 0:
            return None
        return t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value

    @on(DataTable.RowHighlighted, "#styles")
    def show(self) -> None:
        n = self.current()
        if not n:
            return
        path = list_styles()[n]
        s = load_style(str(path))
        t, tr, mo, c = s["text"], s["transitions"], s["motion"], s["color"]
        self.query_one("#style_info", Static).update(
            f"[b]{n}[/b]  [dim]{path}[/dim]\n{s.get('description', '')}\n\n"
            f"[b]Length[/b] {s['duration']['target']}s ({s['duration']['min']}-{s['duration']['max']})\n"
            f"[b]Cuts[/b] every {s['cuts']['beats_per_cut']} beats · shots {s['cuts']['min_shot_sec']}-"
            f"{s['cuts']['max_shot_sec']}s\n"
            f"[b]Transitions[/b] {int(float(tr.get('density', 0)) * 100)}% of cuts · speed {tr.get('speed')}\n"
            f"  calm {tr.get('palette', {}).get('calm')}\n  medium {tr.get('palette', {}).get('medium')}\n"
            f"  intense {tr.get('palette', {}).get('intense')}\n"
            f"[b]Motion[/b] beat punch {mo.get('beat_punch')} on {mo.get('punch_on')} · shake on drop "
            f"{mo.get('shake_on_drop')} · pulse {mo.get('pulse', 0)}\n"
            f"[b]Split screens[/b] {int(float((s.get('panels') or {}).get('use', 0)) * 100)}% · "
            f"{(s.get('panels') or {}).get('mode')} · {(s.get('panels') or {}).get('kinds')}\n"
            f"[b]Speed ramps[/b] {int(float((s.get('velocity') or {}).get('use', 0)) * 100)}% of moving clips · "
            f"loop {s.get('loop', False)} · labels {(t.get('labels') or {}).get('mode', 'off')}\n"
            f"[b]Text[/b] {t.get('preset')} · hook {t['hook'].get('mode')} · location {t['location'].get('mode')} · "
            f"behind {t['location'].get('behind', 'preset default')} · cta {t.get('cta', {}).get('mode')}\n"
            f"[b]Colour[/b] saturation {c['saturation']} · contrast {c['contrast']} · warmth {c['warmth']} · "
            f"vignette {c['vignette']}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "st_learn":
            def go(r):
                if r:
                    self.app.push_screen(RunScreen(f"Learning style “{r['name']}”",
                                                   ["learn", *r["refs"], "-n", r["name"]]),
                                         lambda _: self.refresh_list())
            self.app.push_screen(LearnStyle(), go)
            return
        n = self.current()
        if not n:
            return
        path = list_styles()[n]
        builtin = USER_STYLES not in path.parents
        if bid == "st_use":
            self.app.query_one("#style", Select).value = n
            self.app.query_one(TabbedContent).active = "tab_make"
        elif bid == "st_open":
            open_path(path)
        elif bid == "st_delete":
            if builtin:
                self.notify("Built-in styles can't be deleted (edit makes your own copy)", severity="warning")
                return

            def gone(ok):
                if ok:
                    path.unlink(missing_ok=True)
                    self.refresh_list()
            self.app.push_screen(Confirm(f"Delete style {n}?", "Delete", True), gone)
        elif bid == "st_edit":
            raw = yaml.safe_load(path.read_text()) or {}
            merged = load_style(str(path))

            def saved(r):
                if not r:
                    return
                from .util import deep_merge
                out = deep_merge(raw, r["data"])
                out["name"] = r["name"]
                USER_STYLES.mkdir(parents=True, exist_ok=True)
                dst = USER_STYLES / f"{r['name']}.yaml"
                dst.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True))
                self.notify(f"Saved {dst}")
                self.refresh_list()
                self.app.refresh_styles()
            self.app.push_screen(EditStyle(n, merged, builtin), saved)


class MusicTab(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("[b]Get the sound of a reel[/b]  [dim]downloads the audio and finds its tempo[/dim]",
                     classes="section")
        with Horizontal(classes="row"):
            yield Input(placeholder="https://www.instagram.com/reel/…", id="mu_url")
            yield Button("Download", id="mu_get", variant="primary")
        yield Static("[b]Downloaded sounds[/b]", classes="section")
        yield DataTable(id="mu_list", cursor_type="row", zebra_stripes=True)
        with Horizontal(classes="actions"):
            yield Button("Use for next reel", id="mu_use", variant="success")
            yield Button("Play", id="mu_play")
            yield Button("Refresh", id="mu_refresh")
        yield Static("[b]Sound effects[/b]  [dim]whooshes on transitions, a hit on the drop, pops as words land, "
                     "waves / wind / birds under each place. Real CC0 recordings from Openverse are fetched once; "
                     f"your own go in {HOME / 'sfx' / 'library'} (a folder per kind: whoosh, impact, riser, pop…).[/dim]",
                     classes="section")
        yield Static("", id="sfx_status", classes="hint")
        with Horizontal(classes="actions"):
            yield Button("Get real sound effects", id="sfx_fetch", variant="primary")
            yield Button("Open my sound folder", id="sfx_open")

    def on_mount(self) -> None:
        self.query_one("#mu_list", DataTable).add_columns("Sound", "Length", "From")
        self.refresh_list()
        self.refresh_sfx()

    def refresh_sfx(self, *_):
        try:
            from .sound import status
            st = status()
            real = [r for r, v in st["roles"].items() if v["library"] or v["openverse"]]
            amb = [z for z, v in st["ambience"].items() if v["library"] or v["openverse"]]
            self.query_one("#sfx_status", Static).update(
                f"real recordings for {len(real)}/{len(st['roles'])} effect kinds, {len(amb)} ambience places"
                + (" · earshot sound bank installed" if st["earshot"] else "")
                + ("" if real else " · press [b]Get real sound effects[/b] once"))
        except Exception as e:
            self.query_one("#sfx_status", Static).update(f"[red]{e}[/red]")

    def refresh_list(self) -> None:
        t = self.query_one("#mu_list", DataTable)
        t.clear()
        d = HOME / "music"
        if not d.exists():
            return
        for meta in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                m = json.loads(meta.read_text())
            except Exception:
                continue
            if not m.get("url"):
                continue
            t.add_row(m.get("label") or meta.stem, fmt_secs(m.get("duration")), (m.get("url") or "")[:48],
                      key=m.get("url"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        t = self.query_one("#mu_list", DataTable)
        key = None
        if t.row_count:
            key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        if bid == "mu_get":
            url = self.query_one("#mu_url", Input).value.strip()
            if not url:
                return
            self.app.push_screen(RunScreen("Downloading sound", ["music", url]), lambda r: self.refresh_list())
        elif bid == "mu_refresh":
            self.refresh_list()
        elif bid == "sfx_fetch":
            self.app.push_screen(RunScreen("Fetching real sound effects (Openverse, CC0)", ["sounds", "--fetch"]),
                                 self.refresh_sfx)
        elif bid == "sfx_open":
            (HOME / "sfx" / "library").mkdir(parents=True, exist_ok=True)
            open_path(str(HOME / "sfx" / "library"))
        elif bid == "mu_use" and key:
            self.app.query_one("#music", Input).value = key
            self.app.query_one(TabbedContent).active = "tab_make"
            self.notify("Music set for your next reel")
        elif bid == "mu_play" and key:
            from .fetch import MUSIC_DIR, canonical
            from .util import short_hash
            hits = [p for p in MUSIC_DIR.glob(f"{short_hash(canonical(key), 12)}.*") if p.suffix != ".json"]
            if hits:
                open_path(hits[0])


class FramesTab(VerticalScroll):
    """Pop-out frame stills for feed posts / carousels."""

    def compose(self) -> ComposeResult:
        st = self.app.state
        yield Static("[b]Pop-out frames[/b]  [dim]the photo sits in a frame and the person or subject steps out "
                     "of it — great for carousel posts[/dim]", classes="section")
        yield ListView(*[ListItem(Label(s)) for s in st.get("frame_sources", [])], id="fr_sources")
        with Horizontal(classes="row"):
            yield Input(placeholder="Photo or folder — or drag it here and press Enter", id="fr_input")
            yield Button("Add", id="fr_add")
            yield Button("Browse…", id="fr_browse")
            yield Button("Remove", id="fr_remove", variant="warning")
        with Horizontal(classes="row"):
            yield Select([("4:5 post / carousel", "post"), ("9:16 story", "story"), ("Square", "square"),
                          ("Post + story", "both")], value="post", id="fr_format", allow_blank=False)
            yield Select([("Paper background", "paper"), ("Blurred photo", "blur"), ("Soft colour", "solid"),
                          ("Dark", "dark")], value="paper", id="fr_bg", allow_blank=False)
            yield Select([("Break out: automatic", "auto"), ("Head above the frame", "top"),
                          ("Legs below the frame", "bottom")], value="auto", id="fr_variant", allow_blank=False)
            yield Select([("Colour: as shot", ""), ("Colour: auto", "auto")] + [(f"Colour: {n}", n)
                                                                               for n in look_names()],
                         value="", id="fr_look", allow_blank=False)
        with Horizontal(classes="switches"):
            yield Switch(id="fr_border")
            yield Label("White print border")
        with Horizontal(classes="actions"):
            yield Button("Make frames", id="fr_make", variant="primary")
        yield Static("[dim]Photos without one clear subject (a person, a lighthouse, a tree…) are skipped. "
                     "The first run downloads the cut-out model once (~170 MB).[/dim]", classes="hint")

    def sources(self) -> list[str]:
        return [str(i.query_one(Label).content) for i in self.query_one("#fr_sources", ListView).children]

    def add(self, path: str) -> None:
        path = path.strip().strip("'\"").replace("\\ ", " ")
        if path and Path(path).expanduser().exists() and path not in self.sources():
            self.query_one("#fr_sources", ListView).append(ListItem(Label(str(Path(path).expanduser()))))
            self.query_one("#fr_input", Input).value = ""
        elif path:
            self.notify(f"Not found: {path}", severity="error")

    @on(Input.Submitted, "#fr_input")
    def submitted(self, e: Input.Submitted) -> None:
        self.add(e.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "fr_add":
            self.add(self.query_one("#fr_input", Input).value)
        elif bid == "fr_browse":
            self.app.push_screen(PickPath(), lambda p: p and self.add(p))
        elif bid == "fr_remove":
            lv = self.query_one("#fr_sources", ListView)
            if lv.index is not None and lv.children:
                lv.children[lv.index].remove()
        elif bid == "fr_make":
            srcs = self.sources()
            if not srcs:
                self.notify("Add photos or a folder first", severity="warning")
                return
            self.app.state["frame_sources"] = srcs
            save_state(self.app.state)
            out = Path(self.app.state.get("out_dir") or DEFAULT_OUT).expanduser() / "frames"
            args = ["frame", *srcs, "-f", self.query_one("#fr_format", Select).value,
                    "--bg", self.query_one("#fr_bg", Select).value,
                    "--variant", self.query_one("#fr_variant", Select).value, "-o", str(out)]
            if self.query_one("#fr_border", Switch).value:
                args.append("--border")
            lk = self.query_one("#fr_look", Select).value
            if lk and lk != Select.BLANK:
                args += ["--look", str(lk)]
            self.app.push_screen(RunScreen("Making pop-out frames", args))


class CloneTab(VerticalScroll):
    """Remake a reel you like, shot for shot, with your own footage."""

    def compose(self) -> ComposeResult:
        st = self.app.state
        yield Static("[b]1 · The reel to copy[/b]  [dim]an Instagram reel link, or a saved video. Its cuts, "
                     "timing, sound, colour and on-screen text are copied; the AI fills every shot with "
                     "your best matching one and rewrites the text for your trip.[/dim]", classes="section")
        yield Input(st.get("clone_ref", ""), placeholder="https://www.instagram.com/reel/…  or  /path/reel.mp4",
                    id="cl_ref")
        yield Static("[b]2 · Your footage[/b]  [dim]uses the folders from the Make tab, or add others here[/dim]",
                     classes="section")
        yield ListView(*[ListItem(Label(s)) for s in st.get("clone_sources") or st.get("sources", [])],
                       id="cl_sources")
        with Horizontal(classes="row"):
            yield Input(placeholder="Folder path — or drag a folder here and press Enter", id="cl_input")
            yield Button("Add", id="cl_add")
            yield Button("Browse…", id="cl_browse")
            yield Button("Remove", id="cl_remove", variant="warning")
        yield Static("[b]3 · Options[/b]", classes="section")
        with Horizontal(classes="row"):
            yield Select([("1 version", "1"), ("2 versions", "2"), ("3 versions", "3")], value="1",
                         id="cl_variants", allow_blank=False)
            yield Select([("Colour: copy the reel's", ""), ("Colour: AI picks", "auto"), ("Colour: none", "none")]
                         + [(f"Colour: {n}", n) for n in look_names()], value="", id="cl_look", allow_blank=False)
            yield Select([("Text: style default", "")] + [(f"Text: {p}", p) for p in PRESETS], value="",
                         id="cl_preset", allow_blank=False)
        with Horizontal(classes="switches"):
            yield Switch(id="cl_keep")
            yield Label("Keep the reel's text word for word")
            yield Switch(id="cl_hype")
            yield Label("Add freeze-frame + glitch")
        with Horizontal(classes="actions"):
            yield Button("Preview clone", id="cl_preview")
            yield Button("Clone reel", id="cl_go", variant="primary")
        yield Static("[dim]The preview writes a side-by-side sheet (reference vs. your shots) so you can check "
                     "the matches before rendering.[/dim]", classes="hint")

    def sources(self) -> list[str]:
        return [str(i.query_one(Label).content) for i in self.query_one("#cl_sources", ListView).children]

    def add(self, path: str) -> None:
        path = path.strip().strip("'\"").replace("\\ ", " ")
        if path and Path(path).expanduser().exists() and path not in self.sources():
            self.query_one("#cl_sources", ListView).append(ListItem(Label(str(Path(path).expanduser()))))
            self.query_one("#cl_input", Input).value = ""
        elif path:
            self.notify(f"Not found: {path}", severity="error")

    @on(Input.Submitted, "#cl_input")
    def submitted(self, e: Input.Submitted) -> None:
        self.add(e.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "cl_add":
            self.add(self.query_one("#cl_input", Input).value)
        elif bid == "cl_browse":
            self.app.push_screen(PickPath(), lambda p: p and self.add(p))
        elif bid == "cl_remove":
            lv = self.query_one("#cl_sources", ListView)
            if lv.index is not None and lv.children:
                lv.children[lv.index].remove()
        elif bid in ("cl_go", "cl_preview"):
            ref = self.query_one("#cl_ref", Input).value.strip().strip("'\"")
            srcs = self.sources()
            if not ref or not srcs:
                self.notify("Paste the reel to copy and add your footage first", severity="warning")
                return
            st = self.app.state
            st["clone_ref"], st["clone_sources"] = ref, srcs
            save_state(st)
            out_dir = Path(st.get("out_dir") or DEFAULT_OUT).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"clone-{Path(srcs[0]).name}-{datetime.now():%Y%m%d-%H%M%S}.mp4"
            args = ["clone", ref, *srcs, "-o", str(out), "--variants", self.query_one("#cl_variants", Select).value]
            for flag, wid in (("--look", "cl_look"), ("--text-preset", "cl_preset")):
                v = blank(self.query_one(f"#{wid}", Select).value)
                if v:
                    args += [flag, v]
            if self.query_one("#cl_keep", Switch).value:
                args.append("--keep-text")
            if self.query_one("#cl_hype", Switch).value:
                args.append("--hype")
            browser = os.environ.get("TRIPSHOTS_COOKIES_BROWSER")
            if browser and ref.startswith("http"):
                args += ["--cookies-from-browser", browser]
            if bid == "cl_preview":
                args.append("--dry-run")
            self.app.push_screen(RunScreen("Cloning the reel", args), lambda r: self.app.after_job(r, out))


class ColorTab(VerticalScroll):
    """Colour looks: copy a look from reels you like, grade photos/videos."""

    def compose(self) -> ComposeResult:
        st = self.app.state
        yield Static("[b]1 · Copy a look you like[/b]  [dim]paste Instagram reel links (or video/photo paths), one "
                     "per line. TripShots measures their colour grade (tone curve, tints, saturation) and saves it "
                     "as a look you can use on any reel or photo.[/dim]", classes="section")
        yield TextArea("", id="lk_refs")
        with Horizontal(classes="row"):
            yield Input(placeholder="Name for the look, e.g. dreamy-bali", id="lk_name")
            yield Button("Copy look", id="lk_learn", variant="primary")
        yield Static("[b]2 · Grade photos and videos[/b]  [dim]makes graded copies (originals untouched) and a "
                     "before/after sheet[/dim]", classes="section")
        yield ListView(*[ListItem(Label(s)) for s in st.get("grade_sources", [])], id="gr_sources")
        with Horizontal(classes="row"):
            yield Input(placeholder="Photo, video or folder — or drag it here and press Enter", id="gr_input")
            yield Button("Add", id="gr_add")
            yield Button("Browse…", id="gr_browse")
            yield Button("Remove", id="gr_remove", variant="warning")
        with Horizontal(classes="row"):
            yield Select(self._options(), value="auto", id="gr_look", allow_blank=False)
            yield Input("0.8", placeholder="Strength 0-1", id="gr_strength", type="number")
            yield Button("Grade copies", id="gr_make", variant="primary")
        yield Static("[b]Looks[/b]", classes="section")
        yield Static(self._looks_text(), id="lk_list")

    @staticmethod
    def _options():
        return [("auto: picked from the footage", "auto")] + [(n, n) for n in look_names()]

    @staticmethod
    def _looks_text() -> str:
        try:
            from .grade import list_looks
            return "\n".join(f"[b]{n}[/b]{'' if v.get('builtin') else ' [yellow](yours)[/yellow]'}  "
                             f"[dim]{v.get('desc', '')}[/dim]" for n, v in list_looks().items())
        except Exception as e:
            return f"[red]{e}[/red]"

    def refresh_looks(self, *_):
        self.query_one("#gr_look", Select).set_options(self._options())
        self.query_one("#lk_list", Static).update(self._looks_text())

    def sources(self) -> list[str]:
        return [str(i.query_one(Label).content) for i in self.query_one("#gr_sources", ListView).children]

    def add(self, path: str) -> None:
        path = path.strip().strip("'\"").replace("\\ ", " ")
        if path and Path(path).expanduser().exists() and path not in self.sources():
            self.query_one("#gr_sources", ListView).append(ListItem(Label(str(Path(path).expanduser()))))
            self.query_one("#gr_input", Input).value = ""
        elif path:
            self.notify(f"Not found: {path}", severity="error")

    @on(Input.Submitted, "#gr_input")
    def submitted(self, e: Input.Submitted) -> None:
        self.add(e.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "gr_add":
            self.add(self.query_one("#gr_input", Input).value)
        elif bid == "gr_browse":
            self.app.push_screen(PickPath(), lambda p: p and self.add(p))
        elif bid == "gr_remove":
            lv = self.query_one("#gr_sources", ListView)
            if lv.index is not None and lv.children:
                lv.children[lv.index].remove()
        elif bid == "lk_learn":
            refs = [r.strip() for r in self.query_one("#lk_refs", TextArea).text.splitlines() if r.strip()]
            name = re.sub(r"[^a-z0-9-]+", "-", self.query_one("#lk_name", Input).value.strip().lower()).strip("-")
            if not refs or not name:
                self.notify("Paste at least one link and give the look a name", severity="warning")
                return
            args = ["look", *refs, "-n", name]
            browser = os.environ.get("TRIPSHOTS_COOKIES_BROWSER")
            if browser:
                args += ["--cookies-from-browser", browser]
            self.app.push_screen(RunScreen(f"Copying look “{name}”", args), self.refresh_looks)
        elif bid == "gr_make":
            srcs = self.sources()
            if not srcs:
                self.notify("Add photos, videos or a folder first", severity="warning")
                return
            self.app.state["grade_sources"] = srcs
            save_state(self.app.state)
            out = Path(self.app.state.get("out_dir") or DEFAULT_OUT).expanduser() / "graded"
            args = ["grade", *srcs, "--look", str(self.query_one("#gr_look", Select).value), "-o", str(out)]
            v = self.query_one("#gr_strength", Input).value.strip()
            if v:
                args += ["--strength", v]
            self.app.push_screen(RunScreen("Colour grading", args))


class LibraryTab(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("[b]What TripShots remembers[/b]  [dim]each file is analysed and judged once, then "
                     "reused forever[/dim]", classes="section")
        yield Static("", id="lib_info")
        with Horizontal(classes="actions"):
            yield Button("Refresh", id="lib_refresh")
            yield Button("Forget AI verdicts", id="lib_forget", variant="warning")
            yield Button("Wipe everything", id="lib_wipe", variant="error")
        yield Static("[b]Analyse your footage[/b]  [dim]describe every photo and clip now (what's in it, quality, people, "
                     "places), without making a reel. Reels made later reuse it, and other apps can read it "
                     "(~/.tripshots/analysis/…/media.jsonl). Uses the footage folders from the Ask tab.[/dim]",
                     classes="section")
        with Horizontal(classes="actions"):
            yield Button("Analyse my footage", id="lib_analyze", variant="primary")
            yield Button("Technical only (no AI)", id="lib_analyze_noai")

    def on_mount(self) -> None:
        self.refresh_info()

    def refresh_info(self) -> None:
        from . import library as lib
        try:
            s = lib.stats()
        except Exception as e:
            self.query_one("#lib_info", Static).update(f"[red]{e}[/red]")
            return
        ai = "\n".join(f"    {k}: {v} shots" for k, v in (s.get("ai_scored_shots") or {}).items()) or "    none yet"
        self.query_one("#lib_info", Static).update(
            f"  Files known: [b]{s['files']}[/b]\n  Shots analysed: [b]{s['shots']}[/b]\n"
            f"  AI verdicts:\n{ai}\n  Disk used: {s['disk_mb']} MB\n  [dim]{s['location']}[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from . import library as lib
        bid = event.button.id
        if bid == "lib_refresh":
            self.refresh_info()
        elif bid in ("lib_analyze", "lib_analyze_noai"):
            from .catalog import footage_roots
            if not footage_roots():
                self.notify("Set your footage folders first (Ask tab)", severity="warning")
                return
            args = ["analyze"] + (["--no-ai"] if bid == "lib_analyze_noai" else [])
            self.app.push_screen(RunScreen("Analysing your footage", args), lambda r: self.refresh_info())
        elif bid == "lib_forget":
            def go(ok):
                if ok:
                    self.notify(f"Forgot {lib.forget_scores()} verdicts")
                    self.refresh_info()
            self.app.push_screen(Confirm("Forget all AI verdicts? Footage will be re-judged next time.",
                                         "Forget"), go)
        elif bid == "lib_wipe":
            def go(ok):
                if ok:
                    shutil.rmtree(lib.LIB_DIR, ignore_errors=True)
                    lib._conn = None
                    self.refresh_info()
            self.app.push_screen(Confirm("Delete the whole library? Everything is re-analysed next time.",
                                         "Wipe", True), go)


class AskTab(VerticalScroll):
    """Say what you want ("a reel about my days in Yellowstone"); the AI finds the footage and plans it."""

    def compose(self) -> ComposeResult:
        st = self.app.state
        yield Static("[b]What reel do you want?[/b]  [dim]say it in your own words; your AI (Settings) works out "
                     "the place, dates and people, finds the footage and plans the edit[/dim]", classes="section")
        yield TextArea(st.get("ask_last", ""), id="ask_text")
        yield Static("[dim]e.g.  a reel about my days in Yellowstone  ·  all the pictures I'm in  ·  "
                     "15 seconds of Lisbon with mom, something calm  ·  last summer's beach days[/dim]",
                     classes="hint")
        with Horizontal(classes="row"):
            yield Input(st.get("music", ""), placeholder="Music: a reel link or /path/song.mp3 (empty = AI picks "
                        "from your music folder, or silent)", id="ask_music")
            yield Select([(m, m) for m in st.get("recent_music", [])], prompt="Recent music…", id="ask_music_recent")
        with Horizontal(classes="actions"):
            yield Button("Plan it", id="ask_plan", variant="primary")
            yield Button("Make it (plan + render)", id="ask_make", variant="success")
            yield Button("Just find the footage", id="ask_find")

        yield Static("[b]Where your footage lives[/b]  [dim]searched for every request; folders are searched "
                     "inside too (one per line)[/dim]", classes="section")
        yield TextArea("", id="ask_roots")
        with Horizontal(classes="actions"):
            yield Button("Save folders", id="ask_roots_save")
            yield Button("Use the Make tab's folders", id="ask_roots_make")
            yield Button("Show my trips", id="ask_trips")

        yield Static("[b]People[/b]  [dim]so \"pictures I'm in\" and \"with mom\" work; faces are recognised "
                     "on this computer, nothing is uploaded[/dim]", classes="section")
        yield Static("", id="ask_people", classes="hint")
        with Horizontal(classes="row"):
            yield Input(placeholder="2-5 photos of you (paths separated by spaces, or drag them in)", id="ask_me")
            yield Button("This is me", id="ask_me_add")
        with Horizontal(classes="row"):
            yield Button("Find everyone else's faces", id="ask_discover")
            yield Input(placeholder="cluster, e.g. c2", id="ask_cluster")
            yield Input(placeholder="name, e.g. mom", id="ask_cname")
            yield Button("Name them", id="ask_name")

    def on_mount(self) -> None:
        self.refresh_info()

    def refresh_info(self) -> None:
        from . import catalog, people
        roots = catalog.footage_roots()
        self.query_one("#ask_roots", TextArea).text = "\n".join(str(r) for r in roots)
        known = people.list_people()
        self.query_one("#ask_people", Static).update(
            "Known: " + ", ".join(f"[b]{p['name']}[/b] ({p['faces']} faces)" for p in known) if known
            else "Nobody yet. Add a few photos of yourself below.")

    @on(Select.Changed, "#ask_music_recent")
    def _recent(self, e: Select.Changed) -> None:
        if e.value and e.value != Select.BLANK:
            self.query_one("#ask_music", Input).value = str(e.value)

    def _request(self) -> str | None:
        text = self.query_one("#ask_text", TextArea).text.strip()
        if not text:
            self.notify("Describe the reel first", severity="warning")
            return None
        self.app.state["ask_last"] = text
        save_state(self.app.state)
        return text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from . import catalog, people
        bid = event.button.id
        q = lambda i: self.query_one(f"#{i}")  # noqa: E731
        if bid in ("ask_plan", "ask_make"):
            text = self._request()
            if not text:
                return
            if not catalog.footage_roots():
                self.notify("Add the folders where your footage lives first (below)", severity="warning")
                return
            args = ["ask", text]
            music = q("ask_music").value.strip()
            if music:
                args += ["-m", music]
                remember(self.app.state, "recent_music", music)
                save_state(self.app.state)
            if bid == "ask_make":
                args.append("--render")
            title = "Making your reel" if bid == "ask_make" else "Planning your reel"
            self.app.push_screen(RunScreen(title, args), lambda r: self.app.after_job(r, Path(".")))
        elif bid == "ask_find":
            text = self._request()
            if text:
                self.app.push_screen(RunScreen("Finding the footage", ["ask", text, "--find-only"]))
        elif bid in ("ask_roots_save", "ask_roots_make"):
            if bid == "ask_roots_make":
                folders = self.app.state.get("sources", [])
            else:
                folders = [x.strip() for x in q("ask_roots").text.splitlines() if x.strip()]
            try:
                catalog.set_footage_roots(folders)
                self.notify(f"{len(folders)} footage folder(s) saved")
            except Exception as e:
                self.notify(str(e), severity="error")
            self.refresh_info()
        elif bid == "ask_trips":
            self.app.push_screen(RunScreen("Your trips", ["trips"]))
        elif bid == "ask_me_add":
            import shlex
            photos = shlex.split(q("ask_me").value.strip())
            if not photos:
                self.notify("Add 2-5 photos where your face is the biggest", severity="warning")
                return
            self.app.push_screen(RunScreen("Learning your face", ["people", "add", "me", *photos]),
                                 lambda r: self.refresh_info())
        elif bid == "ask_discover":
            self.app.push_screen(RunScreen("Finding faces in your footage", ["people", "discover"]),
                                 lambda r: self.refresh_info())
        elif bid == "ask_name":
            cid, name = q("ask_cluster").value.strip(), q("ask_cname").value.strip()
            if not (cid and name):
                self.notify("Type the cluster (c1, c2…) and a name", severity="warning")
                return
            try:
                people.name_cluster(cid, name)
                self.notify(f"{cid} is now {name}")
            except Exception as e:
                self.notify(str(e), severity="error")
            self.refresh_info()


class SettingsTab(VerticalScroll):
    def compose(self) -> ComposeResult:
        env = {**read_env(), **{k: v for k, v in os.environ.items() if k.startswith(("TRIPSHOTS_", "MINIMAX_", "GEMINI_"))}}
        st = self.app.state
        yield Static("[b]AI that judges your shots[/b]", classes="section")
        yield Select([("Automatic", "auto"), ("Claude (your subscription, via Claude Code)", "claude-cli"),
                      ("MiniMax (API key)", "minimax"), ("Claude API key", "api"), ("None (no AI)", "none")],
                     value=env.get("TRIPSHOTS_BACKEND", "auto") if env.get("TRIPSHOTS_BACKEND", "auto") in
                     ("auto", "claude-cli", "minimax", "api", "none") else "auto", id="se_backend", allow_blank=False)
        yield Input(env.get("TRIPSHOTS_CLAUDE_MODEL", ""), placeholder="Claude model (optional: sonnet / opus)",
                    id="se_model")
        yield Input(env.get("MINIMAX_API_KEY", ""), placeholder="MiniMax API key", password=True, id="se_minimax")
        yield Input(env.get("TRIPSHOTS_MODEL", ""), placeholder="MiniMax/API model (default MiniMax-M3)",
                    id="se_mmodel")
        yield Input(env.get("ANTHROPIC_API_KEY", ""), placeholder="Claude API key (only for the API option)",
                    password=True, id="se_anthropic")
        yield Static("[b]Gemini watches your clips (optional)[/b]  [dim]a free key from aistudio.google.com/apikey: "
                     "each clip is watched once as a small 480p copy (deleted right after) for its best instant, "
                     "shake, tilt and in-camera whip pans[/dim]", classes="section")
        yield Input(env.get("GEMINI_API_KEY", ""), placeholder="Gemini API key", password=True, id="se_gemini")
        yield Static("[b]Instagram login[/b]  [dim]browser you're logged in with, for reel links[/dim]",
                     classes="section")
        cb = env.get("TRIPSHOTS_COOKIES_BROWSER", "")
        yield Select([("None", "")] + [(b, b) for b in BROWSERS], value=cb if cb in BROWSERS else "",
                     id="se_cookies", allow_blank=False)
        yield Static("[b]Video encoder[/b]  [dim]auto uses your Mac's (or GPU's) hardware encoder when it works: "
                     "several times faster encoding, slightly bigger files[/dim]", classes="section")
        enc = env.get("TRIPSHOTS_ENCODER", "") or "auto"
        yield Select([("Auto (hardware when it works)", "auto"), ("Hardware", "hardware"),
                      ("Software (libx264: slowest, smallest files)", "software")],
                     value=enc if enc in ("auto", "hardware", "software") else "auto", id="se_encoder",
                     allow_blank=False)
        yield Static("[b]Where finished reels go[/b]", classes="section")
        yield Input(st.get("out_dir") or str(DEFAULT_OUT), id="se_out")
        with Horizontal(classes="actions"):
            yield Button("Save", id="se_save", variant="primary")
            yield Button("Check setup", id="se_doctor")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "se_save":
            q = lambda i: self.query_one(f"#{i}")  # noqa: E731
            backend = q("se_backend").value
            write_env({
                "TRIPSHOTS_BACKEND": "" if backend == "auto" else backend,
                "TRIPSHOTS_CLAUDE_MODEL": q("se_model").value.strip(),
                "MINIMAX_API_KEY": q("se_minimax").value.strip(),
                "TRIPSHOTS_MODEL": q("se_mmodel").value.strip(),
                "ANTHROPIC_API_KEY": q("se_anthropic").value.strip(),
                "GEMINI_API_KEY": q("se_gemini").value.strip(),
                "TRIPSHOTS_COOKIES_BROWSER": blank(q("se_cookies").value) or "",
                "TRIPSHOTS_ENCODER": "" if q("se_encoder").value == "auto" else q("se_encoder").value,
            })
            self.app.state["out_dir"] = q("se_out").value.strip() or str(DEFAULT_OUT)
            save_state(self.app.state)
            self.notify("Settings saved")
        elif event.button.id == "se_doctor":
            self.app.push_screen(RunScreen("Checking your setup", ["doctor"]))


# -------------------------------------------------------------------- app
class TripShotsApp(App):
    TITLE = "TripShots"
    SUB_TITLE = "travel footage → beat-synced reels"
    CSS = """
    Screen { background: $surface; }
    TabbedContent { height: 1fr; }
    .section { margin: 1 0 0 0; color: $text; }
    .hint { color: $text-muted; margin: 0 0 0 1; }
    .row { height: auto; }
    .row Input { width: 1fr; }
    .row Select { width: 1fr; }
    .actions { height: auto; margin: 1 0; }
    .actions Button { margin: 0 1 0 0; }
    .wrap { height: auto; }
    .switches { height: auto; }
    .switches Label { padding: 1 2 0 0; }
    #sources { height: auto; max-height: 8; border: round $primary 40%; }
    #sources:focus { border: round $primary; }
    MakeTab { padding: 0 2; }
    MusicTab, LibraryTab, SettingsTab, FramesTab, ColorTab, CloneTab, AskTab { padding: 0 2; }
    #ask_text { height: 5; }
    #ask_roots { height: 5; }
    #lk_refs { height: 5; }
    #fr_sources { height: auto; max-height: 8; border: round $primary 40%; }
    #reels_left, #styles_left { width: 55%; padding: 0 1; }
    #reel_detail, #style_detail { width: 45%; padding: 0 2; border-left: vkey $primary 30%; }
    #reels, #styles { height: 1fr; }
    #mu_list { height: auto; max-height: 14; }
    RunScreen { align: center middle; }
    #run_box { width: 92%; height: 90%; border: thick $primary; background: $panel; padding: 1 2; }
    #run_title { text-style: bold; color: $accent; }
    #run_stage { margin: 1 0 0 0; }
    #run_progress { margin: 0 0 1 0; }
    #run_log { height: 1fr; border: round $primary 30%; }
    #run_results { height: auto; margin: 1 0 0 0; }
    #run_results Button, #run_buttons Button { margin: 0 1 0 0; }
    #run_buttons { height: auto; margin: 1 0 0 0; }
    Confirm, PickPath, EditText, EditStyle, LearnStyle { align: center middle; }
    .dialog { width: 70; height: auto; max-height: 90%; border: thick $primary; background: $panel; padding: 1 2; }
    .dialog.wide { width: 90%; height: 90%; }
    .dialog_q { text-style: bold; margin: 0 0 1 0; }
    .field_label { margin: 1 0 0 0; color: $text-muted; }
    .dialog_buttons { height: auto; margin: 1 0 0 0; }
    .dialog_buttons Button { margin: 0 1 0 0; }
    .roots { height: auto; }
    .roots Button { margin: 0 1 0 0; }
    #tree { height: 1fr; border: round $primary 30%; }
    #l_urls { height: 8; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("0", "tab('tab_ask')", "Ask", show=True),
        Binding("1", "tab('tab_make')", "Make", show=True),
        Binding("2", "tab('tab_clone')", "Clone"),
        Binding("3", "tab('tab_reels')", "Reels"),
        Binding("4", "tab('tab_styles')", "Styles"),
        Binding("5", "tab('tab_music')", "Music"),
        Binding("6", "tab('tab_frames')", "Frames"),
        Binding("7", "tab('tab_color')", "Colour"),
        Binding("8", "tab('tab_library')", "Library"),
        Binding("9", "tab('tab_settings')", "Settings"),
    ]

    def __init__(self):
        super().__init__()
        self.state = load_state()
        # jobs started from here (ask, find) write reels where the app does
        os.environ.setdefault("TRIPSHOTS_OUT", str(Path(self.state.get("out_dir") or DEFAULT_OUT).expanduser()))

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab_ask"):
            with TabPane("Ask", id="tab_ask"):
                yield AskTab()
            with TabPane("Make", id="tab_make"):
                yield MakeTab()
            with TabPane("Clone", id="tab_clone"):
                yield CloneTab()
            with TabPane("Reels", id="tab_reels"):
                yield ReelsTab()
            with TabPane("Styles", id="tab_styles"):
                yield StylesTab()
            with TabPane("Music", id="tab_music"):
                yield MusicTab()
            with TabPane("Frames", id="tab_frames"):
                yield FramesTab()
            with TabPane("Colour", id="tab_color"):
                yield ColorTab()
            with TabPane("Library", id="tab_library"):
                yield LibraryTab()
            with TabPane("Settings", id="tab_settings"):
                yield SettingsTab()
        yield Footer()

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def copy_text(self, text: str) -> None:
        if IS_MAC and shutil.which("pbcopy"):
            subprocess.run(["pbcopy"], input=text.encode())
        else:
            self.copy_to_clipboard(text)
        self.notify("Caption copied")

    def refresh_styles(self) -> None:
        sel = self.query_one("#style", Select)
        cur = sel.value
        names = list(list_styles())
        sel.set_options([(n, n) for n in names])
        if cur in names:
            sel.value = cur

    def after_job(self, result: dict | None, out: Path) -> None:
        if not result:
            return
        if result.get("variants"):
            plans = [v["plan"] for v in result["variants"] if v.get("plan")]
            for p in plans:
                remember(self.state, "reels", p, 200)
            save_state(self.state)
            if result.get("_render") and plans:
                self._render_queue(plans)
            else:
                self.query_one(ReelsTab).refresh_list()
            return
        plan = result.get("plan")
        if plan:
            remember(self.state, "reels", plan, 200)
            save_state(self.state)
        if result.get("_render") and plan:
            self.push_screen(RunScreen("Rendering", ["render", plan]),
                             lambda r: self.query_one(ReelsTab).refresh_list())
            return
        self.query_one(ReelsTab).refresh_list()

    def _render_queue(self, plans: list[str]) -> None:
        if not plans:
            self.query_one(ReelsTab).refresh_list()
            return
        self.push_screen(RunScreen(f"Rendering {Path(plans[0]).name.replace('.plan.json', '')}",
                                   ["render", plans[0]]), lambda r: self._render_queue(plans[1:]))


def _noop():
    pass


def run() -> None:
    TripShotsApp().run()


if __name__ == "__main__":
    run()
