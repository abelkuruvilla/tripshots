<script>
  import { onMount } from "svelte";
  import { revealItemInDir, openUrl } from "@tauri-apps/plugin-opener";
  import { app, api, media, startJob, toast, seconds } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let reel = $state(null);
  let error = $state("");
  let caption = $state("");
  let savedCaption = $state("");
  let picking = $state(null); // slot being re-cast
  let cands = $state([]);
  let video = $state(null);
  let bust = $state(Date.now());

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

  // reload when a render of this plan finishes
  let lastRender = null;
  $effect(() => {
    const done = app.jobs.find((j) => j.kind === "render" && j.state === "done" && reel && j.label === reel.name + ".plan.json");
    if (done && done.id !== lastRender) {
      if (lastRender !== null) load();
      lastRender = done.id;
    }
  });

  let total = $derived(reel ? reel.segments.reduce((a, s) => a + s.dur, 0) : 0);
  let rendering = $derived(app.jobs.some((j) => j.kind === "render" && j.state === "running" && reel && j.label === reel.name + ".plan.json"));

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
    const r = await api("/api/edit", { plan: reel.plan, edits: [{ op: "swap", segment: picking.slot, shot_id: shot.id }] });
    picking = null;
    toast(`Slot ${r.changes?.length ? "changed" : "unchanged"}: render to see it`, "info");
    await load();
    reel.stale = true;
  }
  async function render() {
    await startJob("render", { plan: reel.plan }, `Render ${reel.name}`);
  }
  function seek(s) {
    if (video) {
      video.currentTime = s.start + 0.05;
      video.play();
    }
  }
</script>

<div class="page">
  <div class="page-head">
    <button class="btn ghost" onclick={() => (app.view = "reels")}><Icon name="back" /> Reels</button>
    {#if reel}
      <h1 class="ellipsis">{reel.name}</h1>
      <span class="badge">{seconds(reel.duration)}</span>
      <span class="badge">{reel.width}×{reel.height}</span>
      {#if reel.qa?.total}<span class="badge {reel.qa.passed === reel.qa.total ? 'ok' : 'err'}">QA {reel.qa.passed}/{reel.qa.total}</span>{/if}
      <div class="spacer"></div>
      <button class="btn" onclick={() => revealItemInDir(reel.video || reel.plan)}><Icon name="folder" size={15} /> Show in folder</button>
      <button class="btn primary" onclick={render} disabled={rendering}>
        {#if rendering}<span class="spin"></span> Rendering…{:else}<Icon name="play" size={14} /> {reel.rendered ? "Re-render" : "Render"}{/if}
      </button>
    {/if}
  </div>

  {#if error}<p class="muted">{error}</p>{/if}
  {#if reel}
    <div class="layout">
      <div class="player card" class:wide={reel.width > reel.height}>
        {#if reel.video}
          <!-- svelte-ignore a11y_media_has_caption -->
          <video bind:this={video} src={media(reel.video, bust)} controls playsinline poster={media(reel.cover, bust)}></video>
        {:else if reel.storyboard}
          <img src={media(reel.storyboard, bust)} alt="storyboard" />
          <p class="muted center">Planned, not rendered yet.</p>
        {/if}
      </div>

      <div class="side">
        <div class="card pad">
          <h2>Post it</h2>
          {#if reel.upload}
            <p class="small">Upload <a onclick={() => revealItemInDir(reel.upload)}>{reel.upload.split(/[\\/]/).pop()}</a>
              {#if reel.sound}, then add the sound <b>{reel.sound}</b> in Instagram, starting at 0:00.{/if}</p>
            {#if reel.sound_url}<button class="btn small" onclick={() => openUrl(reel.sound_url)}><Icon name="music" size={14} /> Open the sound's reel</button>{/if}
          {:else if reel.video}
            <p class="small">Upload <a onclick={() => revealItemInDir(reel.video)}>{reel.video.split(/[\\/]/).pop()}</a>.</p>
          {/if}
        </div>

        <div class="card pad">
          <div class="row"><h2>Caption</h2><div style="flex:1"></div>
            <button class="btn small" onclick={copyCaption}><Icon name="copy" size={13} /> Copy</button>
            <button class="btn small" disabled={caption === savedCaption} onclick={saveCaption}>Save</button>
          </div>
          <textarea rows="8" bind:value={caption}></textarea>
        </div>

        {#if reel.texts.length}
          <div class="card pad">
            <h2>On screen</h2>
            <ul class="texts">
              {#each reel.texts as t}<li><span class="muted mono">{(+t.start).toFixed(1)}s</span> {t.text}</li>{/each}
            </ul>
          </div>
        {/if}
      </div>
    </div>

    <h2 class="tl-head">Timeline <span class="hint">· click a shot to play it, “Swap” to replace it</span></h2>
    <div class="timeline">
      {#each reel.segments as s}
        <div class="slot" style="flex: {Math.max(s.dur, 0.35)}" title={`${s.slot}. ${s.role || ""} ${s.file} ${s.note || ""}`}>
          <button class="shot" onclick={() => seek(s)}>
            {#if s.thumb}<img src={media(s.thumb)} alt="" loading="lazy" />{/if}
            <span class="n">{s.slot}</span>
          </button>
          <div class="cap">
            <span class="ellipsis">{s.role || ""}</span>
            <button class="btn small ghost" onclick={() => pick(s)}><Icon name="swap" size={12} /></button>
          </div>
        </div>
      {/each}
    </div>
    <div class="muted small">{reel.segments.length} shots · {seconds(total)}{#if reel.style} · style {reel.style}{/if}{#if reel.recipe} · recipe {reel.recipe}{/if}</div>
  {/if}
</div>

{#if picking}
  <div class="overlay" onclick={() => (picking = null)} role="presentation">
    <div class="card drawer" onclick={(e) => e.stopPropagation()} role="dialog">
      <div class="row"><h2>Replace shot {picking.slot}</h2><div style="flex:1"></div>
        <button class="btn ghost" onclick={() => (picking = null)}><Icon name="x" /></button></div>
      <p class="muted small">The best shots from this reel's footage. The slot keeps its length and place on the beat.</p>
      <div class="cands">
        {#each cands as c}
          <button class="cand" class:used={c.used} onclick={() => swap(c)} disabled={c.used}>
            {#if c.thumb}<img src={media(c.thumb)} alt="" loading="lazy" />{/if}
            <div class="small"><b>{c.score}</b> {c.used ? "· in reel" : ""}</div>
            <div class="small muted ellipsis">{c.note}</div>
          </button>
        {/each}
      </div>
    </div>
  </div>
{/if}

<style>
  .layout { display: grid; grid-template-columns: minmax(280px, 380px) 1fr; gap: 20px; align-items: start; }
  .layout:has(.player.wide) { grid-template-columns: minmax(420px, 1.4fr) 1fr; }
  .player { overflow: hidden; background: #000; }
  .player video, .player img { width: 100%; display: block; max-height: 64vh; object-fit: contain; background: #000; }
  .center { text-align: center; padding: 8px; }
  .side { display: flex; flex-direction: column; gap: 14px; }
  .pad { padding: 14px 16px; }
  .small { font-size: 12.5px; }
  .texts { margin: 0; padding: 0; list-style: none; max-height: 160px; overflow: auto; }
  .texts li { padding: 3px 0; border-bottom: 1px solid var(--line); font-size: 13px; }
  .tl-head { margin: 24px 0 10px; }
  .timeline { display: flex; gap: 3px; overflow-x: auto; padding-bottom: 6px; }
  .slot { min-width: 54px; display: flex; flex-direction: column; }
  .shot { position: relative; height: 84px; border: 0; padding: 0; border-radius: 6px; overflow: hidden; cursor: pointer; background: var(--sunken); }
  .shot img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .shot .n { position: absolute; top: 3px; left: 4px; font-size: 10.5px; background: rgba(0, 0, 0, 0.55); color: #fff; padding: 0 5px; border-radius: 4px; }
  .cap { display: flex; align-items: center; font-size: 11px; color: var(--muted); }
  .cap .ellipsis { flex: 1; }
  .overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); display: flex; justify-content: flex-end; z-index: 40; }
  .drawer { width: min(640px, 92vw); height: 100%; border-radius: 0; padding: 22px; overflow: auto; }
  .cands { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; }
  .cand { border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 6px; text-align: left; cursor: pointer; }
  .cand:hover:not(:disabled) { border-color: var(--accent); }
  .cand.used { opacity: 0.45; }
  .cand img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 5px; display: block; margin-bottom: 4px; }
</style>
