<script>
  import { app, media, openReel, refreshReels, seconds, ago } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let q = $state("");
  let shown = $derived(
    app.reels.filter((r) => !q || `${r.name} ${r.folder} ${r.sound || ""} ${r.style || ""}`.toLowerCase().includes(q.toLowerCase())),
  );
  // grouped by folder, newest folder first (reels arrive sorted newest first)
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
    <span class="muted">{app.reels.length}</span>
    <div class="spacer"></div>
    <div class="search">
      <Icon name="search" size={15} />
      <input type="text" placeholder="Search reels" bind:value={q} />
    </div>
    <button class="btn" onclick={refreshReels}><Icon name="refresh" size={15} /></button>
    <button class="btn primary" onclick={() => (app.view = "make")}><Icon name="plus" size={15} /> New reel</button>
  </div>

  {#if !app.reels.length}
    <div class="empty">
      <p>No reels yet.</p>
      <button class="btn primary" onclick={() => (app.view = "make")}>Make your first reel</button>
    </div>
  {/if}

  {#each groups as [folder, reels]}
    <h2 class="folder muted" title={folder}><Icon name="folder" size={14} /> {short(folder)}</h2>
    <div class="grid">
      {#each reels as r (r.plan)}
        <button class="tile" onclick={() => openReel(r.plan)}>
          <div class="thumb" class:wide={r.width > r.height}>
            {#if r.cover || r.storyboard}
              <img loading="lazy" src={media(r.cover || r.storyboard, r.modified)} alt="" />
            {/if}
            <span class="dur">{seconds(r.duration)}</span>
            {#if !r.rendered}<span class="draft">plan</span>{/if}
          </div>
          <div class="meta">
            <div class="name ellipsis">{r.name}</div>
            <div class="sub muted ellipsis">{r.sound || r.style || ""}</div>
            <div class="sub muted">{ago(r.modified)}{#if r.qa?.total} · QA {r.qa.passed}/{r.qa.total}{/if}</div>
          </div>
        </button>
      {/each}
    </div>
  {/each}
</div>

<style>
  .search { display: flex; align-items: center; gap: 6px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 0 9px; width: 240px; }
  .search input { border: 0; padding: 7px 0; background: transparent; box-shadow: none; }
  .folder { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; margin: 22px 0 10px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 16px; }
  .tile { border: 0; padding: 0; background: none; text-align: left; cursor: pointer; color: inherit; }
  .thumb {
    position: relative; aspect-ratio: 9 / 16; border-radius: 10px; overflow: hidden; background: var(--sunken);
    box-shadow: var(--shadow); transition: transform 0.12s;
  }
  .thumb.wide { aspect-ratio: 9 / 16; }
  .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .tile:hover .thumb { transform: translateY(-2px); }
  .dur, .draft { position: absolute; bottom: 7px; font-size: 11px; padding: 1px 7px; border-radius: 99px; background: rgba(0, 0, 0, 0.6); color: #fff; }
  .dur { right: 7px; }
  .draft { left: 7px; background: var(--accent); }
  .meta { padding: 8px 2px 0; }
  .name { font-weight: 600; }
  .sub { font-size: 12px; }
</style>
