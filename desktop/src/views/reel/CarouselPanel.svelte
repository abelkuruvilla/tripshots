<script>
  // A carousel post from this reel (carousel.py): make it, then change it slide by slide. Slides are 1080x1350;
  // the first carries the cover title, the last can list the route. Every change redraws only what changed.
  import { revealItemInDir } from "@tauri-apps/plugin-opener";
  import Icon from "../../lib/Icon.svelte";
  import { app, api, media, startJob, toast } from "../../lib/store.svelte.js";
  import { ed } from "./editor.svelte.js";

  let { onpickshot } = $props(); // (title, note, done(shot)) opens the shot drawer

  let car = $state(null);
  let loaded = $state(false);
  let busy = $state(false);
  let v = $state(Date.now());
  let sel = $state(1);
  let cell = $state(1);
  // making it
  let n = $state(8);
  let title = $state("");
  let handle = $state("");
  let route = $state(true);
  try {
    handle = localStorage.getItem("tripshots.handle") || "";
  } catch {}

  async function load() {
    car = await api(`/api/carousel?plan=${encodeURIComponent(ed.reel.plan)}`).catch(() => null);
    loaded = true;
    v = Date.now();
    if (car) {
      title = car.title || "";
      handle = car.handle || handle;
      sel = Math.min(sel, car.slides.length);
    }
  }
  $effect(() => {
    if (ed.reel && !loaded) load();
  });
  // made by a job: show it when it's done
  let lastJob = null;
  $effect(() => {
    const done = app.jobs.find((j) => j.kind === "carousel" && j.state === "done" && ed.reel && j.label === ed.reel.name + ".plan.json");
    if (done && done.id !== lastJob) {
      if (lastJob !== null) load();
      lastJob = done.id;
    }
  });
  let making = $derived(app.jobs.some((j) => j.kind === "carousel" && j.state === "running" && ed.reel && j.label === ed.reel.name + ".plan.json"));

  async function make() {
    try {
      localStorage.setItem("tripshots.handle", handle.trim());
    } catch {}
    await startJob("carousel", { plan: ed.reel.plan, slides: n, title: title.trim() || null, handle: handle.trim() || null, route },
                   `Carousel of ${ed.reel.name}`);
  }
  async function change(ops) {
    busy = true;
    try {
      car = await api("/api/carousel", { plan: ed.reel.plan, ops: Array.isArray(ops) ? ops : [ops] });
      v = Date.now();
      sel = Math.max(1, Math.min(sel, car.slides.length));
    } catch (e) {
      toast(String(e.message || e), "error");
    } finally {
      busy = false;
    }
  }
  let slide = $derived(car?.slides?.[sel - 1] || null);
  let cells = $derived(slide?.kind === "route" ? 0 : { single: 1, duo: 2, trio: 3 }[slide?.layout || "single"]);
  let crop = $derived(slide?.crops?.[slide?.shots?.[cell - 1]] || { zoom: 1, x: 0.5, y: 0.5 });
  let cz = $state(1);
  let cx = $state(0.5);
  let cy = $state(0.5);
  $effect(() => {
    cz = crop.zoom;
    cx = crop.x;
    cy = crop.y;
  });
  $effect(() => {
    if (cell > cells) cell = 1;
  });
  const setCrop = () => change({ op: "crop", slide: sel, cell, zoom: +cz, x: +cx, y: +cy });
</script>

<section class="panel">
  <div class="row">
    <h2>Carousel</h2>
    {#if car}<span class="meta">{car.slides.length} slides · 1080×1350</span>{/if}
    <div class="spacer"></div>
    {#if car}<button class="btn sm ghost icon" onclick={() => revealItemInDir(car.slides[0].file)} title="Show the slides in their folder" aria-label="Show in folder"><Icon name="folder" size={14} /></button>{/if}
  </div>

  {#if !loaded}
    <div class="empty"><span class="spin"></span></div>
  {:else if !car}
    <p class="quiet">The reel's best shots as a swipeable post: the hook on the cover, each slide numbered, and the route at the end</p>
    <div class="field">
      <span class="lbl">Slides</span>
      <div class="seg" role="radiogroup" aria-label="Slides">
        {#each [5, 6, 8, 10] as k}<button role="radio" aria-checked={n === k} onclick={() => (n = k)}>{k}</button>{/each}
      </div>
    </div>
    <div class="field">
      <label for="ct">Cover <span class="hint">· six words or fewer; empty: the reel's hook</span></label>
      <input id="ct" type="text" bind:value={title} maxlength="60" />
    </div>
    <div class="field">
      <label for="ch">Your handle <span class="hint">· small on every slide</span></label>
      <input id="ch" type="text" bind:value={handle} placeholder="@yourname" />
    </div>
    <label class="check"><input type="checkbox" bind:checked={route} /> A last slide with the route</label>
    <button class="btn primary" onclick={make} disabled={making}>{#if making}<span class="spin"></span> Making the slides{:else}Make the carousel{/if}</button>
  {:else}
    <div class="strip" role="listbox" aria-label="Slides">
      {#each car.slides as s, i (s.file + i)}
        <button class="slide" class:on={sel === i + 1} role="option" aria-selected={sel === i + 1} onclick={() => ((sel = i + 1), (cell = 1))}>
          <img src={media(s.file, v)} alt={`Slide ${i + 1}`} loading="lazy" />
          <span class="num meta">{i + 1}</span>
        </button>
      {/each}
      <button class="slide add" onclick={() => onpickshot("Add a slide", "Its picture fills the slide; change the layout after", (sh) => change({ op: "add", shot_id: sh.id, at: car.slides.length + (car.slides.at(-1)?.kind === "route" ? 0 : 1) }))}
              aria-label="Add a slide"><Icon name="plus" /></button>
    </div>
    {#if car.checks?.length}<p class="note small">{car.checks.join(". ")}</p>{/if}

    {#if slide}
      <div class="row">
        <h3>Slide {sel}{slide.kind === "cover" ? " · cover" : slide.kind === "route" ? " · route" : ""}</h3>
        <div class="spacer"></div>
        <button class="btn sm ghost icon" disabled={sel < 2 || busy} onclick={() => change({ op: "move", from: sel, to: sel - 1 }).then(() => (sel -= 1))} aria-label="Move earlier"><Icon name="arrow-left" size={14} /></button>
        <button class="btn sm ghost icon" disabled={sel >= car.slides.length || busy} onclick={() => change({ op: "move", from: sel, to: sel + 1 }).then(() => (sel += 1))} aria-label="Move later"><Icon name="arrow-right" size={14} /></button>
        <button class="btn sm ghost danger icon" disabled={car.slides.length < 2 || busy} onclick={() => change({ op: "remove", slide: sel })} aria-label="Remove this slide"><Icon name="trash" size={14} /></button>
      </div>
      {#if slide.kind !== "route"}
        <div class="field">
          <span class="lbl">Pictures</span>
          <div class="seg" role="radiogroup" aria-label="Layout">
            {#each [["single", "One"], ["duo", "Two"], ["trio", "Three"]] as [id, name]}
              <button role="radio" aria-checked={(slide.layout || "single") === id} disabled={busy} onclick={() => change({ op: "layout", slide: sel, layout: id })}>{name}</button>
            {/each}
          </div>
        </div>
        {#if cells > 1}
          <div class="seg" role="radiogroup" aria-label="Picture">
            {#each Array.from({ length: cells }, (_, k) => k + 1) as k}<button role="radio" aria-checked={cell === k} onclick={() => (cell = k)}>Picture {k}</button>{/each}
          </div>
        {/if}
        <div class="grid3">
          <div class="field"><label for="cz">Zoom <span class="hint">· {(+cz).toFixed(1)}×</span></label>
            <input id="cz" type="range" min="1" max="3" step="0.05" bind:value={cz} onchange={setCrop} /></div>
          <div class="field"><label for="cx">Across</label><input id="cx" type="range" min="0" max="1" step="0.01" bind:value={cx} onchange={setCrop} /></div>
          <div class="field"><label for="cy">Down</label><input id="cy" type="range" min="0" max="1" step="0.01" bind:value={cy} onchange={setCrop} /></div>
        </div>
        <button class="btn sm" disabled={busy} onclick={() => onpickshot(`Picture for slide ${sel}`, "Any shot of this trip", (sh) => change({ op: "swap", slide: sel, cell, shot_id: sh.id }))}>
          <Icon name="swap" size={14} /> Replace picture {cells > 1 ? cell : ""}</button>
      {/if}
    {/if}

    <div class="field">
      <label for="ct2">Cover</label>
      <input id="ct2" type="text" bind:value={title} maxlength="60" onblur={() => title.trim() !== (car.title || "") && change({ op: "title", text: title })}
             onkeydown={(e) => e.key === "Enter" && e.currentTarget.blur()} />
    </div>
    <div class="grid2">
      <div class="field">
        <label for="ch2">Handle</label>
        <input id="ch2" type="text" bind:value={handle} placeholder="@yourname" onblur={() => handle.trim().replace(/^@/, "") !== (car.handle || "") && change({ op: "handle", text: handle })} />
      </div>
      <div class="field">
        <span class="lbl">Route</span>
        <label class="check"><input type="checkbox" checked={car.slides.some((s) => s.kind === "route")} disabled={busy || (car.places || []).length < 2}
                                    onchange={(e) => change({ op: "route", on: e.currentTarget.checked })} /> Last slide</label>
      </div>
    </div>
    <button class="btn sm ghost" onclick={make} disabled={making}>Start again from the reel</button>
  {/if}
</section>

<style>
  .panel { padding: 20px; display: flex; flex-direction: column; gap: 12px; }
  .empty { padding: 24px; display: grid; place-items: center; }
  .strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
  .slide { position: relative; padding: 0; border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--raised); cursor: pointer; overflow: hidden; aspect-ratio: 4 / 5; }
  .slide img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .slide.on { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .slide.add { display: grid; place-items: center; color: var(--text-3); }
  .num { position: absolute; left: 4px; bottom: 4px; padding: 0 4px; border-radius: 3px; background: rgba(15, 15, 16, 0.72); color: #ededed; font-size: 10px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .field { margin: 0; min-width: 0; }
  .lbl { display: block; font-weight: 500; font-size: 13px; margin-bottom: 6px; }
  .note { color: var(--text-2); }
</style>
