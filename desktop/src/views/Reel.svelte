<script>
  // One reel, laid out like an editor: the viewer, an inspector with tabs (Text, Colour, Post; in Expert also Shot
  // and Sound), and the timeline along the bottom, all on one screen.
  import { onMount } from "svelte";
  import { revealItemInDir } from "@tauri-apps/plugin-opener";
  import { app, api, media, startJob, tc } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";
  import { ed, load, edit, undo, redo, setExpert, frames, select, loadNotes } from "./reel/editor.svelte.js";
  import NotesPanel from "./reel/NotesPanel.svelte";
  import TextPanel from "./reel/TextPanel.svelte";
  import PostPanel from "./reel/PostPanel.svelte";
  import Timeline from "./reel/Timeline.svelte";
  import ShotPanel from "./reel/ShotPanel.svelte";
  import SoundPanel from "./reel/SoundPanel.svelte";
  import ColourPanel from "./reel/ColourPanel.svelte";
  import CarouselPanel from "./reel/CarouselPanel.svelte";
  import ClipTrim from "./reel/ClipTrim.svelte";

  let video = $state(null);
  let bust = $state(Date.now());
  let picking = $state(null); // { mode: "swap", seg } | { mode: "insert", after }
  let cands = $state([]);
  let kindShown = $state("all"); // the drawer shows clips, photos or both
  let candQ = $state("");
  // "suggested" = the best shots of the footage; "all" = every shot of it, searched and paged by the engine
  let source = $state("suggested");
  let sortBy = $state("best");
  let all = $state({ total: 0, items: [], loading: false });
  let trim = $state(null); // a long clip chosen: which part of it plays (ClipTrim)
  let allTimer;
  async function loadAll(more = false) {
    if (!reel) return;
    const offset = more ? all.items.length : 0;
    all.loading = true;
    const q = new URLSearchParams({ plan: reel.plan, q: candQ, kind: kindShown, sort: sortBy, offset, limit: 60 });
    try {
      const r = await api(`/api/shots?${q}`);
      all = { total: r.total, items: more ? [...all.items, ...r.items] : r.items, loading: false };
    } catch {
      all.loading = false;
    }
  }
  $effect(() => {
    // search again when the words, the kind or the order change (the words after a short pause)
    const key = `${source}|${candQ}|${kindShown}|${sortBy}`;
    if (!picking || source !== "all" || !key) return;
    clearTimeout(allTimer);
    allTimer = setTimeout(() => loadAll(), candQ ? 250 : 0);
  });
  let shownCands = $derived(cands.filter((c) => (kindShown === "all" || c.kind === kindShown)
    && (!candQ || candQ.toLowerCase().split(/\s+/).every((w) => `${c.caption} ${c.note} ${c.file} ${(c.tags || []).join(" ")} ${(c.vibes || []).join(" ")} ${c.size || ""} ${c.angle || ""}`.toLowerCase().includes(w)))));
  let still = $state(""); // the edited frame's address
  let showDraft = $state(false); // the viewer plays the quick preview of the edits (render --draft)
  let stillBusy = $state(false);
  let tabsEl = $state(null);

  onMount(() => {
    ed.reel = null;
    ed.sel = null;
    ed.now = 0;
    ed.preview = false;
    ed.tab = ed.expert ? "shot" : "text";
    load().then(() => ((ed.preview = !ed.reel?.video), loadNotes()));
  });
  let reel = $derived(ed.reel);
  // the inspector's tools, down a rail at its side (always all in view, like an editor's tool bar)
  let tabs = $derived(ed.expert
    ? [["shot", "Shot", "scissors"], ["text", "Text", "type"], ["colour", "Colour", "palette"], ["sound", "Sound", "music"],
       ["notes", "Notes", "message"], ["post", "Post", "send"], ["carousel", "Carousel", "grid"]]
    : [["text", "Text", "type"], ["colour", "Colour", "palette"], ["notes", "Notes", "message"], ["post", "Post", "send"],
       ["carousel", "Carousel", "grid"]]);

  // a render of this plan finished: show the new video
  let lastRender = null;
  $effect(() => {
    const done = app.jobs.find((j) => j.kind === "render" && j.state === "done" && reel && j.label === reel.name + ".plan.json");
    if (done && done.id !== lastRender) {
      if (lastRender !== null) load().then(() => ((bust = Date.now()), (ed.preview = false), (showDraft = false)));
      lastRender = done.id;
    }
  });
  // a quick preview of the edits finished: play it
  let lastPreview = null;
  $effect(() => {
    const done = app.jobs.find((j) => j.kind === "preview" && j.state === "done" && reel && j.label === reel.name + ".plan.json");
    if (done && done.id !== lastPreview) {
      if (lastPreview !== null) load().then(() => ((bust = Date.now()), (showDraft = !!ed.reel?.draft), (ed.preview = !ed.reel?.draft),
                                                    showDraft && setTimeout(() => video?.play(), 0)));
      lastPreview = done.id;
    }
  });
  // an edit makes the preview out of date: back to the still of the edit
  $effect(() => {
    if (showDraft && reel && !reel.draft) ((showDraft = false), (ed.preview = true));
  });
  let previewJob = $derived(app.jobs.find((j) => j.kind === "preview" && j.state === "running" && reel && j.label === reel.name + ".plan.json"));
  async function playEdit() {
    if (reel.draft) {
      showDraft = true;
      ed.preview = false;
      setTimeout(() => video?.play(), 0);
      return;
    }
    video?.pause();
    await startJob("preview", { plan: reel.plan }, `Preview of ${reel.name}`);
  }

  // notes were turned into edits (and rendered): show the result
  let lastRevise = null;
  $effect(() => {
    const done = app.jobs.find((j) => j.kind === "revise" && j.state === "done" && reel && j.label === reel.name + ".plan.json");
    if (done && done.id !== lastRevise) {
      if (lastRevise !== null) load().then(() => ((bust = Date.now()), (ed.preview = false), (ed.tab = "notes")));
      lastRevise = done.id;
    }
  });
  function noteHere() {
    video?.pause();
    ed.tab = "notes";
    ed.noting = true;
  }

  // the playhead follows the video smoothly while it plays
  $effect(() => {
    if (!video) return;
    let raf = 0;
    const tick = () => {
      ed.now = video.currentTime;
      if (!video.paused) raf = requestAnimationFrame(tick);
    };
    const start = () => (raf = requestAnimationFrame(tick));
    video.addEventListener("play", start);
    video.addEventListener("seeked", tick);
    video.addEventListener("timeupdate", tick);
    return () => {
      cancelAnimationFrame(raf);
      video.removeEventListener("play", start);
      video.removeEventListener("seeked", tick);
      video.removeEventListener("timeupdate", tick);
    };
  });

  // the edited frame at the playhead, asked for a moment after the playhead or the plan last changed
  $effect(() => {
    if (!ed.preview || !reel || !app.engine) return;
    const at = Math.max(0, Math.min(ed.now, reel.duration - 0.04)).toFixed(2);
    const url = `${app.engine.url}/api/still?t=${app.engine.token}&plan=${encodeURIComponent(reel.plan)}&at=${at}&v=${ed.version}${ed.raw ? "&raw=1" : ""}${ed.mask && !ed.raw ? `&mask=${ed.mask}` : ""}`;
    const id = setTimeout(() => {
      if (url !== still) {
        stillBusy = true;
        still = url;
      }
    }, ed.raw ? 0 : 120);
    return () => clearTimeout(id);
  });

  let renderJob = $derived(app.jobs.find((j) => j.kind === "render" && j.state === "running" && reel && j.label === reel.name + ".plan.json"));
  let selText = $derived(ed.sel?.kind === "text" ? reel?.texts.find((t) => t.index === ed.sel.index) : null);

  async function render() {
    await startJob("render", { plan: reel.plan }, reel.name);
  }
  function seek(t) {
    ed.now = Math.max(0, Math.min(t, (reel?.duration || 0) - 0.02));
    if (video && !ed.preview) video.currentTime = ed.now;
  }
  function togglePlay() {
    if (ed.preview) {
      if (!reel.video) return;
      ed.preview = false;
      setTimeout(() => video?.play(), 0);
      return;
    }
    if (video) video.paused ? video.play() : video.pause();
  }
  // click the preview: the selected text goes there
  function place(e) {
    if (!selText) return;
    const img = e.currentTarget;
    const r = img.getBoundingClientRect();
    const k = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight);
    const w = img.naturalWidth * k, h = img.naturalHeight * k;
    const x = (e.clientX - r.left - (r.width - w) / 2) / w;
    const y = (e.clientY - r.top - (r.height - h) / 2) / h;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    edit({ op: "edit_text", index: selText.index, style: { x: +x.toFixed(3), y: +y.toFixed(3) } }, true);
  }

  // the before/after divider: drag it, or move it with the arrow keys
  let splitting = false;
  function splitDown(e) {
    splitting = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    e.stopPropagation();
  }
  function splitMove(e) {
    if (!splitting) return;
    const r = e.currentTarget.parentElement.getBoundingClientRect();
    ed.splitAt = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  }
  function splitKeys(e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    e.stopPropagation();
    ed.splitAt = Math.max(0, Math.min(1, ed.splitAt + (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 0.1 : 0.02)));
  }

  function openDrawer(p) {
    picking = p;
    trim = null;
    source = "suggested";
  }
  // the part of the selected clip that plays, from the Shot tab: straight to the trim step
  function choosePart(seg) {
    picking = { mode: "part", seg };
    trim = { shot: { id: seg.shot_id, file: seg.file }, start: seg.in };
  }
  async function pick(seg) {
    openDrawer({ mode: "swap", seg });
    kindShown = seg.kind === "video" ? "video" : "all"; // a clip's slot: clips first
    cands = [];
    cands = await api(`/api/candidates?plan=${encodeURIComponent(reel.plan)}&top=200`);
  }
  // any panel can ask for a shot from this trip (the carousel's slides): the same drawer, its own title
  async function pickShot(title, note, done) {
    openDrawer({ mode: "custom", title, note, done });
    cands = [];
    cands = await api(`/api/candidates?plan=${encodeURIComponent(reel.plan)}&top=200`);
  }
  async function addOnTop() {
    openDrawer({ mode: "pip" });
    cands = [];
    cands = await api(`/api/candidates?plan=${encodeURIComponent(reel.plan)}&top=200`);
  }
  async function insertAfter(slot) {
    openDrawer({ mode: "insert", after: slot });
    cands = [];
    cands = await api(`/api/candidates?plan=${encodeURIComponent(reel.plan)}&top=200`);
  }
  // a clip longer than the slot: choose which part plays before it goes in
  const slotLen = (p) => (p.mode === "swap" ? p.seg.dur : p.mode === "insert" ? 1.5 : null);
  async function choose(shot, at = null) {
    const p = picking;
    const len = slotLen(p);
    if (at === null && len && shot.kind === "video" && (shot.file_s ?? shot.len_s ?? 0) > len + 0.3) {
      trim = { shot };
      return;
    }
    picking = null;
    trim = null;
    const from = at === null ? {} : { in: at };
    if (p.mode === "part") return void (await edit({ op: "slip", segment: p.seg.slot, in: at }));
    if (p.mode === "custom") return p.done(shot);
    if (p.mode === "swap") await edit({ op: "swap", segment: p.seg.slot, shot_id: shot.id, ...from });
    else if (p.mode === "pip") {
      const res = await edit({ op: "pip_add", shot_id: shot.id, start: frames(Math.max(0, ed.now)), dur: 2 });
      if (res) select({ kind: "pip", index: ed.reel.pips.length });
    } else {
      const res = await edit({ op: "insert", after: p.after, shot_id: shot.id, dur: 1.5, ...from });
      if (res) select({ kind: "clip", slot: p.after + 1 });
    }
  }

  // tabs: arrow keys move between them
  function tabKeys(e) {
    const i = tabs.findIndex(([id]) => id === ed.tab);
    const j = e.key === "ArrowDown" || e.key === "ArrowRight" ? i + 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? i - 1 : null;
    if (j === null) return;
    e.preventDefault();
    e.stopPropagation();
    ed.tab = tabs[(j + tabs.length) % tabs.length][0];
    setTimeout(() => tabsEl?.querySelector(`[aria-selected="true"]`)?.focus(), 0);
  }

  // keys: space plays, ⌘Z / ⇧⌘Z undo and redo, S splits the selected shot, ⌫ removes the selection, ← → step
  function keys(e) {
    if (picking) {
      if (e.key === "Escape") picking = null;
      return;
    }
    if (e.key === "Escape") return void (ed.sel = null);
    const el = e.target;
    const typing = /^(TEXTAREA|SELECT)$/.test(el?.tagName) || el?.isContentEditable ||
      (el?.tagName === "INPUT" && !["range", "checkbox", "radio", "color", "button"].includes(el.type));
    if (typing || !reel || el?.getAttribute?.("role") === "tab") return;
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "z") {
      e.preventDefault();
      e.shiftKey ? redo() : undo();
    } else if (e.key === " " && el?.tagName !== "BUTTON") {
      e.preventDefault();
      togglePlay();
    } else if (ed.expert && e.key.toLowerCase() === "s" && !mod && ed.sel?.kind === "clip") {
      const s = reel.segments[ed.sel.slot - 1];
      const at = ed.now - s.start;
      if (at > 0.07 && at < s.dur - 0.07) edit({ op: "split", segment: s.slot, at: frames(at) });
    } else if (ed.expert && !mod && ed.sel?.kind === "clip" && "fr".includes(e.key.toLowerCase())) {
      const s = reel.segments[ed.sel.slot - 1];
      if (s.kind !== "video" || s.panel || s.ramp || (s.freeze && e.key.toLowerCase() === "f")) return;
      if (e.key.toLowerCase() === "r") edit({ op: "reverse", segment: s.slot, on: !s.reverse });
      else edit({ op: "freeze", segment: s.slot, at: frames(Math.max(0, Math.min(s.dur, ed.now - s.start))), dur: 1 });
    } else if ((e.key === "Backspace" || e.key === "Delete") && ed.sel && !mod) {
      e.preventDefault();
      const sel = ed.sel;
      if (sel.kind === "text") {
        ed.sel = null;
        edit({ op: "delete_text", index: sel.index });
      } else if (sel.kind === "pip") {
        ed.sel = null;
        edit({ op: "pip_delete", index: sel.index });
      } else if (ed.expert && reel.segments.length > 1) {
        ed.sel = null;
        edit({ op: "delete", segment: sel.slot });
      }
    } else if (e.key.toLowerCase() === "n" && !mod) {
      e.preventDefault();
      noteHere();
    } else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && el?.type !== "range") {
      e.preventDefault();
      seek(ed.now + (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 1 : 1 / 30));
    }
  }
</script>

<svelte:window onkeydown={keys} />

<div class="editor">
  <header class="bar">
    <button class="btn ghost" onclick={() => (app.view = "reels")}><Icon name="back" /> Projects</button>
    {#if reel}
      <div class="title">
        <h1 class="ellipsis">{reel.name}</h1>
        <span class="meta">{[tc(reel.duration), reel.width > reel.height ? "16:9" : "9:16", reel.qa?.total ? `QA ${reel.qa.passed}/${reel.qa.total}` : ""].filter(Boolean).join(" · ")}</span>
      </div>
      <div class="spacer"></div>
      <div class="hist" role="group" aria-label="History">
        <button class="btn ghost icon" onclick={undo} disabled={!reel.history?.undo} title="Undo (⌘Z)" aria-label="Undo"><Icon name="undo" /></button>
        <button class="btn ghost icon" onclick={redo} disabled={!reel.history?.redo} title="Redo (⇧⌘Z)" aria-label="Redo"><Icon name="redo" /></button>
      </div>
      <label class="switch" title="Timeline editing: shot lengths and order, splits, speed, framing, music">
        <input type="checkbox" role="switch" checked={ed.expert} onchange={(e) => setExpert(e.currentTarget.checked)} />
        <span class="track" aria-hidden="true"><span class="knob"></span></span> Expert
      </label>
      <button class="btn ghost icon" onclick={() => revealItemInDir(reel.video || reel.plan)} title="Show in folder" aria-label="Show in folder"><Icon name="folder" /></button>
      <button class="btn primary" onclick={render} disabled={!!renderJob}>
        {#if renderJob}<span class="spin"></span> Rendering{:else}<Icon name="play" /> {reel.rendered ? (reel.stale ? "Render the changes" : "Render again") : "Render"}{/if}
      </button>
    {/if}
  </header>

  {#if ed.error}<p class="err-text pad">{ed.error}</p>{/if}
  {#if reel}
    <div class="main">
      <div class="left">
      <div class="stage">
        <div class="screen">
          <div class="player" style="--ar: {reel.width / reel.height}">
            {#if reel.video || (showDraft && reel.draft)}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video bind:this={video} class:hidden={ed.preview} src={media(showDraft && reel.draft ? reel.draft : reel.video, bust)} controls playsinline
                     poster={showDraft ? undefined : media(reel.cover, bust)}></video>
            {/if}
            {#if (ed.preview || !reel.video) && still}
              <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions (text is also placed with the Place buttons) -->
              <img class="still" class:placing={!!selText} src={still} alt="The reel as edited, at the playhead"
                   onload={() => (stillBusy = false)} onerror={() => (stillBusy = false)} onclick={place} />
              {#if ed.mask}<span class="badge">Mask: {ed.mask}</span>{/if}
              {#if ed.split && !ed.raw && !ed.mask}
                <!-- before | after: the shot as filmed on the left of the divider, your edit on the right -->
                <img class="still before" src={still + "&raw=1"} alt="" style="clip-path: inset(0 {(1 - ed.splitAt) * 100}% 0 0)" />
                <div class="divider" style="left: {ed.splitAt * 100}%" role="slider" tabindex="0" aria-label="Before and after divider"
                     aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(ed.splitAt * 100)}
                     onpointerdown={splitDown} onpointermove={splitMove} onpointerup={() => (splitting = false)}
                     onkeydown={splitKeys}><span class="grip"><Icon name="split" size={14} /></span></div>
                <span class="badge">As filmed</span><span class="badge right">Your edit</span>
              {/if}
              {#if stillBusy}<span class="spin loading" aria-label="Loading the frame"></span>{/if}
              {#if ed.raw}<span class="badge">As filmed</span>{/if}
            {/if}
          </div>
        </div>
        <div class="under">
          <div class="seg" role="radiogroup" aria-label="The viewer shows">
            <button role="radio" aria-checked={ed.preview} onclick={() => (video?.pause(), (ed.preview = true), (showDraft = false))}><Icon name="eye" size={14} /> Your edit</button>
            <button role="radio" aria-checked={!ed.preview && showDraft} onclick={playEdit} disabled={!!previewJob}
                    title="Play your edits in motion: a quick render without sound effects or animated text">
              {#if previewJob}<span class="spin"></span> Preparing{:else}<Icon name="film" size={14} /> Preview{/if}</button>
            <button role="radio" aria-checked={!ed.preview && !showDraft} disabled={!reel.video} onclick={() => ((ed.preview = false), (showDraft = false))}><Icon name="play" size={14} /> Last render</button>
          </div>
          <span class="meta now">{tc(ed.now)} / {tc(reel.duration)}</span>
          <button class="btn sm ghost" onclick={noteHere} title="Pause and note what should change here (N)"><Icon name="message" size={14} /> Note</button>
          <span class="quiet small hint-line">{showDraft && !ed.preview ? "Preview: no sound effects, text without motion" : ed.preview ? (ed.split ? "Drag the divider to compare" : selText ? "Click the picture to place the text" : "A still of your edit, without motion") : reel.stale ? "Older than your edits" : ""}</span>
        </div>
      </div>
      <section class="tl" aria-label="Timeline">
        <Timeline onseek={seek} onpick={pick} />
        <p class="quiet keys">
          <kbd>Space</kbd> play · <kbd>N</kbd> note · <kbd>⌘Z</kbd> undo · <kbd>⌫</kbd> remove · <kbd>←</kbd><kbd>→</kbd> a frame{#if ed.expert} · <kbd>S</kbd> split · <kbd>F</kbd> freeze · <kbd>R</kbd> reverse · drag a shot to move it, its edges to trim it{/if}
        </p>
      </section>
      </div>

      <aside class="inspector surface" aria-label="Inspector">
        <!-- svelte-ignore a11y_interactive_supports_focus -->
        <div class="rail" role="tablist" aria-label="Tools" aria-orientation="vertical" bind:this={tabsEl} onkeydown={tabKeys}>
          {#each tabs as [id, label, icon]}
            <button role="tab" id={`tab-${id}`} aria-selected={ed.tab === id} aria-controls="tabpanel" tabindex={ed.tab === id ? 0 : -1}
                    onclick={() => (ed.tab = id)} title={label}>
              <Icon name={icon} size={18} />
              <span class="rl">{label}</span>
              {#if id === "notes" && ed.notes.length}<span class="count">{ed.notes.length}</span>{/if}
            </button>
          {/each}
        </div>
        <div class="pane" id="tabpanel" role="tabpanel" aria-labelledby={`tab-${ed.tab}`}>
          {#if ed.tab === "shot"}<ShotPanel onpick={pick} oninsert={insertAfter} onontop={addOnTop} onpart={choosePart} />
          {:else if ed.tab === "text"}<TextPanel />
          {:else if ed.tab === "colour"}<ColourPanel />
          {:else if ed.tab === "sound"}<SoundPanel />
          {:else if ed.tab === "notes"}<NotesPanel onseek={seek} pause={() => video?.pause()} />
          {:else if ed.tab === "carousel"}<CarouselPanel onpickshot={pickShot} />
          {:else}<PostPanel />{/if}
        </div>
      </aside>
    </div>

  {:else if !ed.error}
    <div class="empty"><span class="spin"></span></div>
  {/if}
</div>

{#if picking}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (Escape closes it too) -->
  <div class="overlay" onclick={(e) => e.target === e.currentTarget && (picking = null)}>
    <div class="drawer" role="dialog" aria-modal="true" aria-label="Choose a shot" tabindex="-1">
      <div class="row">
        <h2>{picking.mode === "custom" ? picking.title : picking.mode === "part" ? `The part of shot ${picking.seg.slot} that plays` : picking.mode === "swap" ? `Replace shot ${picking.seg.slot}` : picking.mode === "pip" ? "Put a shot on top" : `Add a shot after shot ${picking.after}`}</h2>
        {#if picking.mode === "swap" || picking.mode === "part"}<span class="meta">{tc(picking.seg.dur)}</span>{/if}
        <div class="spacer"></div>
        <button class="btn ghost icon" onclick={() => (picking = null)} aria-label="Close"><Icon name="x" /></button>
      </div>
      {#if trim}
        <ClipTrim plan={reel.plan} shot={trim.shot} slot={picking.seg?.slot ?? null} dur={picking.mode === "insert" ? 1.5 : null}
                  start={trim.start ?? null} back={picking.mode === "part" ? "Close" : "All shots"}
                  onback={() => (picking.mode === "part" ? (picking = null) : (trim = null))}
                  onuse={(at) => choose(trim.shot, at)} />
      {:else}
      <p class="muted">{picking.mode === "custom" ? picking.note : picking.mode === "swap" ? `${source === "all" ? "Every shot of this reel's footage" : "The best shots of this reel's footage"}. The slot keeps its length and its place on the beat; for a longer clip you choose the part that plays next`
        : picking.mode === "pip" ? "It appears in a corner at the playhead for 2 s; move it, size it and set its length in the Shot tab"
        : "It comes in for 1.5 s; change its length in the Shot tab"}</p>
      <div class="row cfilter">
        <div class="seg" role="radiogroup" aria-label="Which shots">
          {#each [["suggested", "Suggested"], ["all", "All footage"]] as [id, label]}
            <button role="radio" aria-checked={source === id} onclick={() => (source = id)}>{label}</button>
          {/each}
        </div>
        {#if source === "all"}
          <select bind:value={sortBy} aria-label="Order">
            <option value="best">Best first</option><option value="time">When filmed</option><option value="file">File name</option>
          </select>
        {/if}
      </div>
      <div class="row cfilter">
        <div class="seg" role="radiogroup" aria-label="Show">
          {#each [["all", "All"], ["video", "Clips"], ["photo", "Photos"]] as [id, label]}
            <button role="radio" aria-checked={kindShown === id} onclick={() => (kindShown = id)}>{label}
              {#if source === "suggested"}<span class="meta">{id === "all" ? cands.length : cands.filter((c) => c.kind === id).length}</span>{/if}</button>
          {/each}
        </div>
        <input type="search" placeholder="Find: bison, aerial, serene, close…" bind:value={candQ} aria-label="Find a shot" />
      </div>
      {#if source === "all"}<p class="meta">{all.loading && !all.items.length ? "Looking…" : `${all.total} clip${all.total === 1 ? "" : "s"} and photo${all.total === 1 ? "" : "s"} of this trip's footage`}</p>{/if}
      {#if source === "suggested" && !cands.length}<div class="empty"><span class="spin"></span></div>
      {:else if (source === "suggested" ? shownCands : all.items).length === 0 && !all.loading}<p class="quiet">No {kindShown === "video" ? "clips" : kindShown === "photo" ? "photos" : "shots"} match</p>{/if}
      <div class="cands">
        {#each source === "suggested" ? shownCands : all.items as c (c.id)}
          <button class="cand" onclick={() => choose(c)} disabled={c.used && picking.mode === "swap" && source === "suggested"}>
            <span class="pic">
              {#if c.thumb}<img src={media(c.thumb)} alt="" loading="lazy" />{/if}
              {#if c.kind === "video"}<span class="vbadge"><Icon name="play" size={10} /> {c.file_s ?? c.len_s}s</span>{:else}<span class="vbadge photo">Photo</span>{/if}
              {#if c.words}<span class="vbadge warn" title="Words are drawn on this picture (an edited export or a screenshot)">Text on it</span>{/if}
            </span>
            <span class="row"><span class="tc score">{c.score.toFixed(1)}</span>{#if c.used}<span class="meta">in this reel</span>{/if}</span>
            <span class="note">{c.caption || c.note}</span>
            {#if c.vibes?.length || c.size}<span class="chips2">{#each [c.size, c.angle === "aerial" ? "aerial" : null, ...(c.vibes || [])].filter(Boolean) as v}<span class="vchip">{v}</span>{/each}</span>{/if}
          </button>
        {/each}
      </div>
      {#if source === "all" && all.items.length < all.total}
        <button class="btn ghost more" onclick={() => loadAll(true)} disabled={all.loading}>{all.loading ? "Loading" : `Show more (${all.total - all.items.length} left)`}</button>
      {/if}
      {/if}
    </div>
  </div>
{/if}

<style>
  .editor { height: 100%; display: flex; flex-direction: column; padding: 40px 24px 12px; gap: 16px; min-height: 0; }
  .bar { display: flex; align-items: center; gap: 8px; min-height: 40px; flex: none; }
  .title { display: flex; align-items: baseline; gap: 12px; min-width: 0; margin-left: 4px; }
  .title h1 { font-size: 22px; line-height: 28px; }
  .hist { display: flex; }
  .switch { display: flex; align-items: center; gap: 8px; margin: 0 8px; font-size: 13px; font-weight: 500; }
  .switch input { position: absolute; opacity: 0; width: 0; height: 0; }
  .track { width: 32px; height: 20px; border-radius: 10px; background: var(--line-strong); position: relative; transition: background-color var(--fast) var(--ease); }
  .knob { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: var(--card); box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2); transition: transform 200ms var(--ease); }
  .switch input:checked + .track { background: var(--accent); }
  .switch input:checked + .track .knob { transform: translateX(12px); }
  .switch input:focus-visible + .track { outline: 2px solid var(--accent); outline-offset: 2px; }
  .pad { padding: 0 4px; }

  /* the viewer and the timeline on the left, the inspector the whole height on the right (as editors lay it out) */
  .main { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 440px; gap: 16px; }
  .left { min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
  .stage { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
  .screen { flex: 1; min-height: 0; display: grid; place-items: center; container-type: size; }
  .player {
    position: relative; aspect-ratio: var(--ar); width: min(100cqw, calc(100cqh * var(--ar)));
    border-radius: var(--r-panel); overflow: hidden; background: var(--player); box-shadow: inset 0 0 0 1px var(--line);
  }
  .player video, .player .still { position: absolute; inset: 0; width: 100%; height: 100%; display: block; object-fit: contain; background: var(--player); }
  .player video.hidden { visibility: hidden; }
  .still.placing { cursor: crosshair; }
  .loading { position: absolute; bottom: 12px; right: 12px; color: #ededed; }
  .before { pointer-events: none; }
  .divider { position: absolute; top: 0; bottom: 0; width: 24px; margin-left: -12px; cursor: ew-resize; touch-action: none; outline: none; }
  .divider::before { content: ""; position: absolute; left: 11px; top: 0; bottom: 0; width: 2px; background: #ededed; box-shadow: 0 0 0 1px rgba(15, 15, 16, 0.3); }
  .grip {
    position: absolute; top: 50%; left: 50%; width: 32px; height: 32px; margin: -16px 0 0 -16px; border-radius: 50%;
    display: grid; place-items: center; background: #ededed; color: #171717; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  }
  .divider:focus-visible .grip { outline: 2px solid var(--accent); outline-offset: 2px; }
  .badge.right { left: auto; right: 12px; }
  .badge { position: absolute; left: 12px; top: 12px; padding: 2px 8px; border-radius: 4px; background: rgba(15, 15, 16, 0.72); color: #ededed; font-size: 12px; }
  .under { display: flex; align-items: center; gap: 12px; flex: none; min-width: 0; }
  .now { flex: none; }
  .hint-line { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .inspector { min-height: 0; display: flex; flex-direction: row; overflow: hidden; }
  .rail { flex: none; width: 64px; display: flex; flex-direction: column; gap: 2px; padding: 8px 6px; border-right: 1px solid var(--line); overflow-y: auto; }
  .rail > button {
    position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px 2px; border: 0;
    border-radius: var(--r-sm); background: transparent; color: var(--text-3); font-size: 10.5px; line-height: 12px; font-weight: 500;
    transition: background-color var(--fast) var(--ease), color var(--fast) var(--ease);
  }
  .rail > button:hover { background: var(--raised); color: var(--text); }
  .rail > button[aria-selected="true"] { background: var(--accent-soft); color: var(--accent); }
  .rail > button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .rl { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .count { position: absolute; top: 4px; right: 6px; display: grid; place-items: center; min-width: 16px; height: 16px; padding: 0 4px; border-radius: 8px; background: var(--accent); color: var(--accent-ink); font-size: 10px; font-weight: 600; }
  .pane { flex: 1; min-width: 0; min-height: 0; overflow: auto; overscroll-behavior: contain; }

  .tl { flex: none; }
  .keys { font-size: 12px; margin-top: 4px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
  .keys kbd { height: 18px; min-width: 18px; font-size: 10px; }

  .overlay { position: fixed; inset: 0; background: var(--scrim); display: flex; justify-content: flex-end; z-index: 40; animation: fade var(--menu) var(--ease); }
  .drawer {
    width: min(640px, 92vw); height: 100%; overflow: auto; padding: 40px 24px 24px;
    background: var(--card); border-left: 1px solid var(--line); box-shadow: var(--float);
    display: flex; flex-direction: column; gap: 12px; animation: slide-in var(--enter) var(--ease);
  }
  .cands { display: grid; grid-template-columns: repeat(auto-fill, minmax(136px, 1fr)); gap: 12px; }
  .cand {
    display: flex; flex-direction: column; gap: 4px; padding: 6px; text-align: left;
    border: 1px solid var(--line); border-radius: var(--r-card); background: var(--card); color: inherit;
    transition: border-color var(--fast) var(--ease);
  }
  .cand:hover:not(:disabled) { border-color: var(--accent); }
  .cand:disabled { opacity: 0.45; }
  .pic { position: relative; display: block; margin-bottom: 4px; }
  .cand img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: var(--r-sm); display: block; }
  .vbadge { position: absolute; left: 6px; bottom: 6px; display: inline-flex; align-items: center; gap: 3px; padding: 1px 6px; border-radius: 4px;
            background: rgba(15, 15, 16, 0.78); color: #ededed; font-size: 11px; font-family: var(--mono, monospace); }
  .vbadge.photo { font-family: inherit; color: #cfcfcf; }
  .vbadge.warn { left: auto; right: 6px; font-family: inherit; color: #ffcf8a; }
  .chips2 { display: flex; flex-wrap: wrap; gap: 3px; }
  .vchip { font-size: 10px; line-height: 14px; padding: 0 5px; border-radius: 7px; background: var(--raised); color: var(--text-2); }
  .cfilter { gap: 12px; }
  .more { align-self: center; }
  .cfilter select { width: auto; flex: none; min-height: 32px; height: 32px; padding-block: 0; }
  .cfilter input { flex: 1; min-width: 0; min-height: 32px; height: 32px; }
  .score { font-size: 13px; }
  .note { font-size: 12px; line-height: 16px; color: var(--text-3); display: -webkit-box; line-clamp: 2; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  @media (max-width: 1080px) { .main { grid-template-columns: minmax(0, 1fr) 380px; } }
</style>
