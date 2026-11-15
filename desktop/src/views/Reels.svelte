<script>
  import { app, media, openReel, refreshReels, tc, ago } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let q = $state("");
  let shown = $derived(
    app.reels.filter((r) => !q || `${r.name} ${r.folder} ${r.sound || ""} ${r.style || ""}`.toLowerCase().includes(q.toLowerCase())),
  );
  // grouped by folder; reels arrive newest first, so the newest folder leads
  let groups = $derived.by(() => {
    const m = new Map();
    for (const r of shown) {
      if (!m.has(r.folder)) m.set(r.folder, []);
      m.get(r.folder).push(r);
    }
    return [...m.entries()];
  });
  const short = (f) => f.split(/[\\/]/).slice(-2).join("/");
</script>

<div class="page">
  <div class="page-head">
    <h1>Reels</h1>
    <span class="meta">{app.reels.length}</span>
    <div class="spacer"></div>
    <label class="search">
      <Icon name="search" />
      <input type="text" placeholder="Search" bind:value={q} aria-label="Search reels" />
    </label>
    <button class="btn" onclick={refreshReels} aria-label="Refresh"><Icon name="refresh" /></button>
    <button class="btn primary" onclick={() => (app.view = "make")}><Icon name="plus" /> New reel</button>
  </div>

  {#if app.ai && !app.ai.using && app.ai.backend !== "none"}
    <div class="notice">
      <span>No AI is set up, so shots are picked on sharpness and exposure only and no words or captions are written</span>
      <button class="btn sm" onclick={() => { app.focus = "ai"; app.view = "settings"; }}>Set up an AI</button>
    </div>
  {/if}

  {#if !app.reels.length}
    <div class="empty">
      <p>No reels yet</p>
      <button class="btn primary" onclick={() => (app.view = "make")}>Make your first reel</button>
    </div>
  {:else if !shown.length}
    <div class="empty">Nothing matches “{q}”</div>
  {/if}

  {#each groups as [folder, reels]}
    <section>
      <h2 class="folder" title={folder}><Icon name="folder" size={14} /> <span>{short(folder)}</span><span class="meta">{reels.length}</span></h2>
      <div class="grid">
        {#each reels as r (r.plan)}
          <button class="tile" class:wide={r.width > r.height} onclick={() => openReel(r.plan)}>
            <div class="thumb">
              {#if r.cover || r.storyboard}<img loading="lazy" src={media(r.cover || r.storyboard, r.modified)} alt="" />{/if}
              <span class="tcbox tc">{tc(r.duration)}</span>
            </div>
            <div class="name ellipsis">{r.name}</div>
            <div class="meta ellipsis">
              {[!r.rendered && "plan", r.width > r.height ? "16:9" : "9:16", ago(r.modified)].filter(Boolean).join(" · ")}
            </div>
          </button>
        {/each}
      </div>
    </section>
  {/each}
</div>

<style>
  .search {
    display: flex; align-items: center; gap: 8px; width: 240px; height: 32px; margin: 0; padding: 0 12px;
    background: var(--card); border: 1px solid var(--line-strong); border-radius: var(--r-ctl); color: var(--text-3); font-weight: 400;
  }
  .search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .search input { border: 0; padding: 0; min-height: 0; height: 30px; background: transparent; box-shadow: none; color: var(--text); }
  section + section { margin-top: 40px; }
  .notice {
    display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: -8px 0 24px; padding: 12px 16px;
    border-radius: var(--r-card); background: var(--accent-soft); font-size: 13px;
  }
  .folder { display: flex; align-items: center; gap: 8px; color: var(--text-2); font-size: 13px; margin-bottom: 12px; }
  /* fixed columns so an upright reel is one column and a wide one two, at the same height */
  .grid { display: grid; grid-template-columns: repeat(auto-fill, 160px); grid-auto-flow: dense; gap: 24px 16px; }
  .tile.wide { grid-column: span 2; }
  .tile { border: 0; padding: 0; background: none; text-align: left; cursor: pointer; color: inherit; border-radius: var(--r-card); }
  .thumb {
    position: relative; height: 284px; border-radius: var(--r-card); overflow: hidden; background: var(--raised);
    box-shadow: inset 0 0 0 1px var(--line); margin-bottom: 8px;
    transition: box-shadow 150ms var(--ease);
  }
  .tile:hover .thumb { box-shadow: inset 0 0 0 1px var(--line), 0 0 0 2px var(--line-strong); }
  .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .tcbox {
    position: absolute; right: 8px; bottom: 8px; font-size: 11px; line-height: 16px; padding: 2px 6px;
    border-radius: 4px; background: rgba(15, 15, 16, 0.72); color: #ededed;
  }
  .name { font-weight: 500; }
</style>
