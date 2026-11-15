<script>
  import { onMount } from "svelte";
  import { revealItemInDir, openUrl } from "@tauri-apps/plugin-opener";
  import { app, api, media, startJob, toast, tc } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let reel = $state(null);
  let error = $state("");
  let caption = $state("");
  let savedCaption = $state("");
  let picking = $state(null); // the slot being re-cast
  let cands = $state([]);
  let video = $state(null);
  let bust = $state(Date.now());
  let now = $state(0); // playhead, seconds
  let slotEls = $state([]);

  async function load() {
    try {
      reel = await api(`/api/reel?plan=${encodeURIComponent(app.reel)}`);
      caption = savedCaption = reel.caption || "";
      bust = Date.now();
    } catch (e) {
      error = String(e.message || e);
    }
  }
  onMount(load);

  // a render of this plan finished: show the new video
  let lastRender = null;
  $effect(() => {
    const done = app.jobs.find((j) => j.kind === "render" && j.state === "done" && reel && j.label === reel.name + ".plan.json");
    if (done && done.id !== lastRender) {
      if (lastRender !== null) load();
      lastRender = done.id;
    }
  });

  // the playhead follows the video smoothly while it plays
  $effect(() => {
    if (!video) return;
    let raf = 0;
    const tick = () => {
      now = video.currentTime;
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

  let rendering = $derived(app.jobs.some((j) => j.kind === "render" && j.state === "running" && reel && j.label === reel.name + ".plan.json"));
  let current = $derived(reel ? reel.segments.findIndex((s) => now >= s.start && now < s.start + s.dur) : -1);
  let playX = $derived.by(() => {
    const el = slotEls[current];
    if (!el || current < 0) return null;
    const s = reel.segments[current];
    return el.offsetLeft + ((now - s.start) / s.dur) * el.offsetWidth;
  });

  async function saveCaption() {
    await api("/api/caption", { plan: reel.plan, text: caption });
    savedCaption = caption;
    toast("Caption saved", "ok");
  }
  async function copyCaption() {
    await navigator.clipboard.writeText(caption);
    toast("Caption copied", "ok");
  }
  async function pick(slot) {
    picking = slot;
    cands = await api(`/api/candidates?plan=${encodeURIComponent(reel.plan)}&top=48`);
  }
  async function swap(shot) {
    const slot = picking.slot;
    await api("/api/edit", { plan: reel.plan, edits: [{ op: "swap", segment: slot, shot_id: shot.id }] });
    picking = null;
    await load();
    reel.stale = true;
    toast(`Shot ${slot} replaced. Render to see it`, "info");
  }
  async function render() {
    await startJob("render", { plan: reel.plan }, `Render ${reel.name}`);
  }
  function seek(s) {
    if (!video) return;
    video.currentTime = s.start + 0.04;
    video.play();
  }
  const file = (p) => (p || "").split(/[\\/]/).pop();
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && (picking = null)} />

<div class="page">
  <div class="page-head">
    <button class="btn ghost" onclick={() => (app.view = "reels")}><Icon name="back" /> Reels</button>
    {#if reel}
      <h1 class="ellipsis">{reel.name}</h1>
      <span class="meta">{[tc(reel.duration), `${reel.width}×${reel.height}`, reel.qa?.total ? `QA ${reel.qa.passed}/${reel.qa.total}` : ""].filter(Boolean).join(" · ")}</span>
      <div class="spacer"></div>
      <button class="btn" onclick={() => revealItemInDir(reel.video || reel.plan)}><Icon name="folder" /> Show in folder</button>
      <button class="btn primary" onclick={render} disabled={rendering}>
        {#if rendering}<span class="spin"></span> Rendering{:else}<Icon name="play" /> {reel.rendered ? "Render again" : "Render"}{/if}
      </button>
    {/if}
  </div>

  {#if error}<p class="muted">{error}</p>{/if}
  {#if reel}
    {#if reel.stale}<p class="notice">This plan changed after its last render. Render again to see the changes</p>{/if}
    <div class="layout" class:wide={reel.width > reel.height}>
      <div class="player">
        {#if reel.video}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video bind:this={video} src={media(reel.video, bust)} controls playsinline poster={media(reel.cover, bust)}></video>
        {:else if reel.storyboard}
          <img src={media(reel.storyboard, bust)} alt="Storyboard" />
        {/if}
      </div>

      <div class="side">
        <section class="surface panel">
          <h2>Post it</h2>
          {#if reel.upload}
            <p>Upload <button class="link" onclick={() => revealItemInDir(reel.upload)}>{file(reel.upload)}</button>{#if reel.sound}, then add the sound <b>{reel.sound}</b> in Instagram, starting at <span class="tc">0:00.0</span>{/if}</p>
            {#if reel.sound_url}<button class="btn sm" onclick={() => openUrl(reel.sound_url)}><Icon name="music" size={14} /> Open the sound's reel</button>{/if}
          {:else if reel.video}
            <p>Upload <button class="link" onclick={() => revealItemInDir(reel.video)}>{file(reel.video)}</button></p>
          {:else}
            <p class="muted">Planned, not rendered yet</p>
          {/if}
        </section>

        <section class="surface panel">
          <div class="row">
            <h2>Caption</h2>
            <div class="spacer"></div>
            <button class="btn sm ghost" onclick={copyCaption}><Icon name="copy" size={14} /> Copy</button>
            <button class="btn sm" disabled={caption === savedCaption} onclick={saveCaption}>Save</button>
          </div>
          <textarea rows="7" bind:value={caption} aria-label="Caption"></textarea>
        </section>

        {#if reel.texts.length}
          <section class="surface panel">
            <h2>On screen</h2>
            <ul class="texts">
              {#each reel.texts as t}<li><span class="meta">{tc(t.start)}</span><span>{t.text}</span></li>{/each}
            </ul>
          </section>
        {/if}
      </div>
    </div>

    <div class="tl-head">
      <h2>Timeline</h2>
      <span class="meta">{[`${reel.segments.length} shots`, reel.recipe && `recipe ${reel.recipe}`, reel.style].filter(Boolean).join(" · ")}</span>
    </div>
    <div class="timeline">
      {#each reel.segments as s, i}
        <div class="slot" bind:this={slotEls[i]} style="flex-grow: {s.dur}" class:current={i === current}>
          <button class="shot" onclick={() => seek(s)} title={`${s.slot}. ${s.file}${s.note ? ": " + s.note : ""}`}>
            {#if s.thumb}<img src={media(s.thumb)} alt="" loading="lazy" />{/if}
          </button>
          <button class="swapbtn" onclick={() => pick(s)} aria-label={`Replace shot ${s.slot}`} title="Replace this shot"><Icon name="swap" size={14} /></button>
          <div class="cut meta">{tc(s.start)}</div>
        </div>
      {/each}
      {#if playX !== null}<div class="playhead" style="transform: translateX({playX}px)"></div>{/if}
    </div>
  {/if}
</div>

{#if picking}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (Escape closes it too) -->
  <div class="overlay" onclick={(e) => e.target === e.currentTarget && (picking = null)}>
    <div class="drawer" role="dialog" aria-modal="true" aria-label="Replace a shot" tabindex="-1">
      <div class="row">
        <h2>Replace shot {picking.slot}</h2>
        <span class="meta">{tc(picking.dur)}</span>
        <div class="spacer"></div>
        <button class="btn ghost" onclick={() => (picking = null)} aria-label="Close"><Icon name="x" /></button>
      </div>
      <p class="muted">The best shots from this reel's footage. The slot keeps its length and its place on the beat</p>
      <div class="cands">
        {#each cands as c}
          <button class="cand" onclick={() => swap(c)} disabled={c.used}>
            {#if c.thumb}<img src={media(c.thumb)} alt="" loading="lazy" />{/if}
            <div class="row"><span class="tc score">{c.score.toFixed(1)}</span>{#if c.used}<span class="meta">in this reel</span>{/if}</div>
            <div class="note">{c.note}</div>
          </button>
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .spacer { flex: 1; }
  .notice { margin: -8px 0 16px; padding: 8px 12px; border-radius: var(--r-ctl); background: var(--accent-soft); color: var(--text); font-size: 13px; }
  .layout { display: grid; grid-template-columns: minmax(280px, 360px) minmax(320px, 1fr); gap: 24px; align-items: start; }
  .layout.wide { grid-template-columns: minmax(440px, 1.5fr) minmax(320px, 1fr); }
  .player { border-radius: var(--r-panel); overflow: hidden; background: var(--player); box-shadow: inset 0 0 0 1px var(--line); }
  .player video, .player img { width: 100%; display: block; max-height: 64vh; object-fit: contain; background: var(--player); }
  .side { display: flex; flex-direction: column; gap: 16px; }
  .panel { padding: 16px 20px 20px; display: flex; flex-direction: column; gap: 12px; }
  .panel p { margin: 0; color: var(--text-2); }
  .panel p b { color: var(--text); }
  .panel > .btn { align-self: flex-start; }
  .texts { margin: 0; padding: 0; list-style: none; max-height: 160px; overflow: auto; }
  .texts li { display: grid; grid-template-columns: 56px 1fr; gap: 8px; padding: 6px 0; border-top: 1px solid var(--line); font-size: 13px; }
  .texts li:first-child { border-top: 0; }
  .texts .meta { line-height: 20px; }
  .tl-head { display: flex; align-items: baseline; gap: 12px; margin: 40px 0 12px; }
  .timeline { position: relative; display: flex; gap: 2px; overflow-x: auto; padding-bottom: 8px; }
  .slot { position: relative; flex-basis: 0; min-width: 44px; display: flex; flex-direction: column; }
  .shot { height: 80px; border: 0; padding: 0; border-radius: 4px; overflow: hidden; cursor: pointer; background: var(--raised); }
  .shot img { width: 100%; height: 100%; object-fit: cover; display: block; transition: opacity 150ms var(--ease); }
  .slot.current .shot { box-shadow: inset 0 0 0 2px var(--accent); }
  .swapbtn {
    position: absolute; top: 4px; right: 4px; width: 24px; height: 24px; display: grid; place-items: center;
    border: 0; border-radius: var(--r-sm); background: rgba(15, 15, 16, 0.72); color: #ededed; cursor: pointer;
    opacity: 0; transition: opacity 150ms var(--ease);
  }
  .slot:hover .swapbtn, .swapbtn:focus-visible { opacity: 1; }
  .cut { margin-top: 4px; padding-left: 4px; border-left: 1px solid var(--line-strong); overflow: hidden; white-space: nowrap; }
  .playhead { position: absolute; top: -4px; left: 0; width: 2px; height: 88px; margin-left: -1px; background: var(--accent); border-radius: 1px; pointer-events: none; }
  .overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.32); display: flex; justify-content: flex-end; z-index: 40; animation: fade 200ms var(--ease); }
  .drawer {
    width: min(640px, 92vw); height: 100%; overflow: auto; padding: 40px 24px 24px;
    background: var(--card); border-left: 1px solid var(--line); box-shadow: var(--float);
    display: flex; flex-direction: column; gap: 12px; animation: slide 300ms var(--ease);
  }
  .drawer p { margin: 0 0 8px; }
  .cands { display: grid; grid-template-columns: repeat(auto-fill, minmax(136px, 1fr)); gap: 12px; }
  .cand {
    display: flex; flex-direction: column; gap: 4px; padding: 6px; text-align: left; cursor: pointer;
    border: 1px solid var(--line); border-radius: var(--r-card); background: var(--card); color: inherit;
    transition: border-color 150ms var(--ease);
  }
  .cand:hover:not(:disabled) { border-color: var(--accent); }
  .cand:disabled { opacity: 0.45; cursor: default; }
  .cand img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: var(--r-sm); display: block; margin-bottom: 4px; }
  .score { font-size: 13px; }
  .note { font-size: 12px; line-height: 16px; color: var(--text-3); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  @keyframes fade { from { opacity: 0; } }
  @keyframes slide { from { transform: translateX(12px); opacity: 0.6; } }
</style>
