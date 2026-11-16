<script>
  import { app, api, media, openReel, refreshReels, tc, ago, toast } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  // a reel as a project: pin, favourite, collection, rename, duplicate, delete (projects.py)
  let menu = $state(null); // the reel whose menu is open
  let ask = $state(null); // { kind: "rename" | "collection" | "delete", reel, value }
  async function act(r, action, value = null) {
    menu = null;
    try {
      const res = await api("/api/reel/manage", { plan: r.plan, action, value });
      await refreshReels();
      if (action === "delete") toast(`${r.name} moved to the Trash`, "info");
      if (action === "duplicate") toast(`Copied as ${res.plan.split(/[\\/]/).pop().replace(".plan.json", "")}: render it to see it`, "info");
    } catch (e) {
      toast(String(e.message || e), "error");
    }
  }
  function confirmAsk() {
    const a = ask;
    ask = null;
    if (a.kind === "rename" && a.value.trim()) act(a.reel, "rename", a.value.trim());
    if (a.kind === "collection") act(a.reel, "collection", a.value.trim() || null);
    if (a.kind === "delete") act(a.reel, "delete");
  }
  let collections = $derived([...new Set(app.reels.map((r) => r.collection).filter(Boolean))].sort());

  let q = $state("");
  let filter = $state("all");
  const filters = [["all", "All"], ["upright", "Upright"], ["wide", "Wide"], ["plans", "Plans"], ["edited", "Edited"]];
  const fits = (r) => filter === "all" || (filter === "upright" && r.height >= r.width) || (filter === "wide" && r.width > r.height)
    || (filter === "plans" && !r.rendered) || (filter === "edited" && r.stale) || (filter === "favorites" && r.favorite)
    || (filter.startsWith("c:") && r.collection === filter.slice(2));
  let shown = $derived(
    app.reels.filter((r) => fits(r) && (!q || `${r.name} ${r.folder} ${r.sound || ""} ${r.style || ""}`.toLowerCase().includes(q.toLowerCase()))),
  );
  // pinned first, then by collection, then by folder; reels arrive newest first, so the newest group leads
  let groups = $derived.by(() => {
    const m = new Map();
    for (const r of shown) {
      const g = r.pinned ? "\u0000Pinned" : r.collection ? `\u0001${r.collection}` : r.folder;
      if (!m.has(g)) m.set(g, []);
      m.get(g).push(r);
    }
    return [...m.entries()];
  });
  const groupName = (g) => (g.startsWith("\u0000") || g.startsWith("\u0001") ? g.slice(1) : null);
  const short = (f) => f.split(/[\\/]/).slice(-2).join("/");
</script>

<div class="page">
  <div class="page-head">
    <h1>Reels</h1>
    <span class="meta">{app.reels.length}</span>
    <div class="spacer"></div>
    <label class="search">
      <Icon name="search" />
      <input type="search" placeholder="Search" bind:value={q} aria-label="Search reels" />
    </label>
    <button class="btn icon" onclick={refreshReels} aria-label="Look for new reels" title="Look for new reels"><Icon name="refresh" /></button>
    <button class="btn primary" onclick={() => (app.view = "make")}><Icon name="plus" /> Make a reel</button>
  </div>
  {#if app.reels.length}
    <div class="seg filters" role="radiogroup" aria-label="Show">
      {#each filters as [id, label]}<button role="radio" aria-checked={filter === id} onclick={() => (filter = id)}>{label}</button>{/each}
      <button role="radio" aria-checked={filter === "favorites"} onclick={() => (filter = "favorites")}>Favourites</button>
      {#each collections as c}<button role="radio" aria-checked={filter === "c:" + c} onclick={() => (filter = "c:" + c)}>{c}</button>{/each}
    </div>
  {/if}

  {#if app.ai && !app.ai.using && app.ai.backend !== "none"}
    <div class="notice">
      <span>No AI is set up, so shots are picked on sharpness and exposure only and no words or captions are written</span>
      <button class="btn sm" onclick={() => { app.focus = "ai"; app.view = "settings"; }}>Set up an AI</button>
    </div>
  {/if}

  {#if !app.reels.length}
    <div class="empty">
      <h2>No reels yet</h2>
      <p>Reels you make here, on the command line or with an AI agent show up in this list</p>
      <button class="btn primary" onclick={() => (app.view = "make")}>Make your first reel</button>
    </div>
  {:else if !shown.length}
    <div class="empty">
      <p>{q ? `Nothing matches “${q}”` : "No reels of this kind"}</p>
      <button class="btn" onclick={() => ((q = ""), (filter = "all"))}>Show all reels</button>
    </div>
  {/if}

  {#each groups as [folder, reels]}
    <section>
      <h2 class="folder" title={folder}><Icon name={groupName(folder) === "Pinned" ? "pin" : "folder"} size={14} /> <span>{groupName(folder) ?? short(folder)}</span><span class="meta">{reels.length}</span></h2>
      <div class="grid">
        {#each reels as r (r.plan)}
          <div class="tilewrap" class:wide={r.width > r.height}>
          <button class="tile" onclick={() => openReel(r.plan)} aria-label={`Open ${r.name}`}>
            <div class="thumb">
              {#if r.cover || r.storyboard}<img loading="lazy" src={media(r.cover || r.storyboard, r.modified)} alt="" />{/if}
              <span class="play" aria-hidden="true"><Icon name="play" size={18} /></span>
              {#if !r.rendered}<span class="tag">Plan</span>{:else if r.stale}<span class="tag">Edited</span>{/if}
              <span class="tcbox tc">{tc(r.duration)}</span>
            </div>
            <div class="name ellipsis">{#if r.favorite}<span class="fav" aria-label="Favourite">♥</span> {/if}{r.name}</div>
            <div class="meta ellipsis">
              {[r.width > r.height ? "16:9" : "9:16", r.qa?.total && r.qa.passed < r.qa.total ? `QA ${r.qa.passed}/${r.qa.total}` : "", ago(r.modified)].filter(Boolean).join(" · ")}
            </div>
          </button>
          <button class="more" onclick={() => (menu = menu === r.plan ? null : r.plan)} aria-label={`More for ${r.name}`} aria-expanded={menu === r.plan}>⋯</button>
          {#if menu === r.plan}
            <div class="menu surface" role="menu">
              <button role="menuitem" onclick={() => act(r, r.pinned ? "unpin" : "pin")}>{r.pinned ? "Unpin" : "Pin to the top"}</button>
              <button role="menuitem" onclick={() => act(r, r.favorite ? "unfavorite" : "favorite")}>{r.favorite ? "Not a favourite" : "Favourite"}</button>
              <button role="menuitem" onclick={() => ((menu = null), (ask = { kind: "collection", reel: r, value: r.collection || "" }))}>Collection…</button>
              <button role="menuitem" onclick={() => ((menu = null), (ask = { kind: "rename", reel: r, value: r.name }))}>Rename…</button>
              <button role="menuitem" onclick={() => act(r, "duplicate")}>Duplicate</button>
              <button role="menuitem" class="danger" onclick={() => ((menu = null), (ask = { kind: "delete", reel: r }))}>Move to the Trash…</button>
            </div>
          {/if}
          </div>
        {/each}
      </div>
    </section>
  {/each}
</div>

{#if ask}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (Escape and Cancel close it) -->
  <div class="scrim" onclick={(e) => e.target === e.currentTarget && (ask = null)}>
    <div class="dialog surface" role="dialog" aria-modal="true" aria-label={ask.kind} tabindex="-1"
         onkeydown={(e) => (e.key === "Escape" && (ask = null), e.key === "Enter" && confirmAsk())}>
      {#if ask.kind === "delete"}
        <h2>Move {ask.reel.name} to the Trash?</h2>
        <p class="muted">Its video, plan and every file made with it go to the Trash, where you can put them back</p>
      {:else}
        <h2>{ask.kind === "rename" ? "Rename" : "Collection"}</h2>
        <!-- svelte-ignore a11y_autofocus -->
        <input type="text" bind:value={ask.value} autofocus list="cols" placeholder={ask.kind === "collection" ? "e.g. Iceland 2026 (empty: none)" : ""} />
        {#if ask.kind === "collection"}<datalist id="cols">{#each collections as c}<option value={c}></option>{/each}</datalist>{/if}
      {/if}
      <div class="row foot">
        <div class="spacer"></div>
        <button class="btn ghost" onclick={() => (ask = null)}>Cancel</button>
        <button class={ask.kind === "delete" ? "btn danger" : "btn primary"} onclick={confirmAsk}>{ask.kind === "delete" ? "Move to the Trash" : "Save"}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .tilewrap { position: relative; }
  .tilewrap.wide { grid-column: span 2; }
  .tilewrap .tile { width: 100%; }
  .more {
    position: absolute; right: 8px; top: 8px; width: 28px; height: 28px; border: 0; border-radius: var(--r-sm);
    background: rgba(15, 15, 16, 0.72); color: #ededed; cursor: pointer; opacity: 0; transition: opacity var(--fast) var(--ease);
  }
  .tilewrap:hover .more, .more:focus-visible, .more[aria-expanded="true"] { opacity: 1; }
  .menu { position: absolute; right: 8px; top: 40px; z-index: 20; display: flex; flex-direction: column; min-width: 190px; padding: 4px; box-shadow: var(--float); }
  .menu button { text-align: left; border: 0; background: transparent; padding: 8px 10px; border-radius: var(--r-sm); color: var(--text); cursor: pointer; font-size: 13px; }
  .menu button:hover { background: var(--raised); }
  .menu .danger { color: var(--danger, #d64545); }
  .fav { color: var(--accent); }
  .scrim { position: fixed; inset: 0; background: var(--scrim); display: grid; place-items: center; z-index: 50; }
  .dialog { width: min(440px, 92vw); padding: 24px; display: flex; flex-direction: column; gap: 12px; box-shadow: var(--float); }
  .dialog .foot { gap: 8px; }
  .search {
    display: flex; align-items: center; gap: 8px; width: 240px; height: 36px; margin: 0; padding: 0 12px;
    background: var(--card); border: 1px solid var(--line-strong); border-radius: var(--r-ctl); color: var(--text-3); font-weight: 400;
  }
  .search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .search input { border: 0; padding: 0; min-height: 0; height: 34px; background: transparent; box-shadow: none; color: var(--text); }
  .search input:focus-visible { box-shadow: none; }
  .filters { margin: 16px 0 32px; }
  section + section { margin-top: 40px; }
  .play {
    position: absolute; left: 50%; top: 50%; width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%;
    display: grid; place-items: center; background: rgba(15, 15, 16, 0.6); color: #ededed; opacity: 0;
    transition: opacity var(--fast) var(--ease);
  }
  .tile:hover .play, .tile:focus-visible .play { opacity: 1; }
  .tag {
    position: absolute; left: 8px; top: 8px; font-size: 11px; line-height: 16px; padding: 2px 6px; border-radius: 4px;
    background: rgba(15, 15, 16, 0.72); color: #ededed; font-weight: 500;
  }
  .notice { margin: 0 0 24px; }
  .folder { display: flex; align-items: center; gap: 8px; color: var(--text-2); font-size: 13px; margin-bottom: 12px; }
  /* fixed columns so an upright reel is one column and a wide one two, at the same height */
  .grid { display: grid; grid-template-columns: repeat(auto-fill, 160px); grid-auto-flow: dense; gap: 24px 16px; }
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
