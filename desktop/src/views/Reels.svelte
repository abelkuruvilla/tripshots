<script>
  // Projects: every reel, with a sidebar to move between the library (all, pinned, favourites, plans, edited), your
  // collections (a trip, a series: drag a reel onto one to file it) and the folders reels sit in. Each card has
  // quick pin and favourite buttons and a menu (rename, duplicate, collection, trash). projects.py on the engine.
  import { app, api, media, openReel, refreshReels, tc, ago, toast } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  const VIEW_KEY = "tripshots.projects.view";
  let view = $state("all"); // all | pinned | favorites | plans | edited | c:<collection> | f:<folder>
  try {
    view = localStorage.getItem(VIEW_KEY) || "all";
  } catch {}
  $effect(() => {
    try {
      localStorage.setItem(VIEW_KEY, view);
    } catch {}
  });
  let q = $state("");
  let sort = $state("recent");
  let shape = $state("any");
  let named = $state([]); // collections, including empty ones
  const loadCollections = async () => (named = await api("/api/collections").catch(() => named));
  $effect(() => {
    app.reels;
    loadCollections();
  });

  let collections = $derived([...new Set([...named, ...app.reels.map((r) => r.collection).filter(Boolean)])].sort((a, b) => a.localeCompare(b)));
  let folders = $derived([...new Set(app.reels.map((r) => r.folder))]);
  const count = (f) => app.reels.filter(f).length;
  const inView = (r) => view === "all" || (view === "pinned" && r.pinned) || (view === "favorites" && r.favorite)
    || (view === "plans" && !r.rendered) || (view === "edited" && r.stale)
    || (view.startsWith("c:") && r.collection === view.slice(2)) || (view.startsWith("f:") && r.folder === view.slice(2));
  const fitsShape = (r) => shape === "any" || (shape === "upright" && r.height >= r.width) || (shape === "wide" && r.width > r.height);
  const sorters = {
    recent: (a, b) => b.modified - a.modified,
    name: (a, b) => a.name.localeCompare(b.name),
    length: (a, b) => b.duration - a.duration,
  };
  let shown = $derived(app.reels
    .filter((r) => inView(r) && fitsShape(r) && (!q || `${r.name} ${r.collection || ""} ${r.sound || ""} ${r.style || ""}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => (view === "all" ? b.pinned - a.pinned : 0) || sorters[sort](a, b)));
  const short = (f) => f.split(/[\\/]/).slice(-2).join("/");
  let title = $derived(view === "all" ? "All projects" : view === "pinned" ? "Pinned" : view === "favorites" ? "Favourites"
    : view === "plans" ? "Plans to render" : view === "edited" ? "Edited since rendering" : view.startsWith("c:") ? view.slice(2) : short(view.slice(2)));

  // actions on one reel
  let menu = $state(null);
  let ask = $state(null); // { kind: rename | collection | delete | new | renamecol | removecol, reel?, value }
  async function act(r, action, value = null) {
    menu = null;
    try {
      const res = await api("/api/reel/manage", { plan: r.plan, action, value });
      await refreshReels();
      if (action === "delete") toast(`${r.name} moved to the Trash`, "info");
      if (action === "duplicate") toast(`Copied as ${res.plan.split(/[\\/]/).pop().replace(".plan.json", "")}: render it to see it`, "info");
      if (action === "collection" && value) toast(`${r.name} is in ${value}`, "info");
    } catch (e) {
      toast(String(e.message || e), "error");
    }
  }
  async function col(action, name, to = null) {
    try {
      named = await api("/api/collections", { action, name, to });
      await refreshReels();
      if (action === "rename" && view === "c:" + name) view = "c:" + to;
      if (action === "remove" && view === "c:" + name) view = "all";
    } catch (e) {
      toast(String(e.message || e), "error");
    }
  }
  function confirmAsk() {
    const a = ask;
    ask = null;
    const v = (a.value || "").trim();
    if (a.kind === "rename" && v) act(a.reel, "rename", v);
    if (a.kind === "collection") act(a.reel, "collection", v || null);
    if (a.kind === "delete") act(a.reel, "delete");
    if (a.kind === "new" && v) col("add", v).then(() => (view = "c:" + v));
    if (a.kind === "renamecol" && v && v !== a.name) col("rename", a.name, v);
    if (a.kind === "removecol") col("remove", a.name);
  }

  // drag a card onto a collection to file it there
  let dragging = $state(null);
  let over = $state(null);
  function drop(e, name) {
    e.preventDefault();
    over = null;
    const r = app.reels.find((x) => x.plan === e.dataTransfer.getData("text/plain"));
    if (r && r.collection !== name) act(r, "collection", name);
  }
  let colMenu = $state(null);
</script>

<svelte:window onclick={(e) => (!e.target.closest?.(".menu, .more, .cmore") && ((menu = null), (colMenu = null)))} />

<div class="projects">
  <aside class="side" aria-label="Projects">
    <div class="group">
      {#each [["all", "All projects", "film", () => true], ["pinned", "Pinned", "pin", (r) => r.pinned], ["favorites", "Favourites", "heart", (r) => r.favorite],
              ["plans", "Plans to render", "layers", (r) => !r.rendered], ["edited", "Edited", "sliders", (r) => r.stale]] as [id, label, icon, f]}
        <button class="item" class:on={view === id} onclick={() => (view = id)}>
          <Icon name={icon} size={15} /><span class="ellipsis">{label}</span><span class="n meta">{count(f)}</span>
        </button>
      {/each}
    </div>

    <div class="ghead"><span>Collections</span><button class="btn sm ghost icon" onclick={() => (ask = { kind: "new", value: "" })} title="New collection" aria-label="New collection"><Icon name="plus" size={14} /></button></div>
    <div class="group">
      {#each collections as c (c)}
        <div class="citem" class:over={over === c} role="listitem"
             ondragover={(e) => (e.preventDefault(), (over = c))} ondragleave={() => over === c && (over = null)} ondrop={(e) => drop(e, c)}>
          <button class="item" class:on={view === "c:" + c} onclick={() => (view = "c:" + c)}>
            <Icon name="folder" size={15} /><span class="ellipsis">{c}</span><span class="n meta">{count((r) => r.collection === c)}</span>
          </button>
          <button class="cmore" onclick={() => (colMenu = colMenu === c ? null : c)} aria-label={`More for ${c}`}>⋯</button>
          {#if colMenu === c}
            <div class="menu surface cmenu" role="menu">
              <button role="menuitem" onclick={() => ((colMenu = null), (ask = { kind: "renamecol", name: c, value: c }))}>Rename…</button>
              <button role="menuitem" class="danger" onclick={() => ((colMenu = null), (ask = { kind: "removecol", name: c }))}>Remove the collection…</button>
            </div>
          {/if}
        </div>
      {:else}
        <p class="quiet small hint">Make one for a trip or a series, then drag reels onto it</p>
      {/each}
    </div>

    {#if folders.length > 1}
      <div class="ghead"><span>Folders</span></div>
      <div class="group">
        {#each folders as f (f)}
          <button class="item" class:on={view === "f:" + f} onclick={() => (view = "f:" + f)} title={f}>
            <Icon name="folder" size={15} /><span class="ellipsis">{short(f)}</span><span class="n meta">{count((r) => r.folder === f)}</span>
          </button>
        {/each}
      </div>
    {/if}
  </aside>

  <div class="main page">
    <div class="page-head">
      <h1 class="ellipsis">{title}</h1>
      <span class="meta">{shown.length}</span>
      <div class="spacer"></div>
      <label class="search">
        <Icon name="search" />
        <input type="search" placeholder="Search" bind:value={q} aria-label="Search projects" />
      </label>
      <button class="btn icon" onclick={refreshReels} aria-label="Look for new reels" title="Look for new reels"><Icon name="refresh" /></button>
      <button class="btn primary" onclick={() => (app.view = "make")}><Icon name="plus" /> Make a reel</button>
    </div>
    <div class="row bar">
      <div class="seg" role="radiogroup" aria-label="Shape">
        {#each [["any", "Any shape"], ["upright", "Upright"], ["wide", "Wide"]] as [id, label]}<button role="radio" aria-checked={shape === id} onclick={() => (shape = id)}>{label}</button>{/each}
      </div>
      <div class="spacer"></div>
      <label class="sortl meta" for="psort">Sort</label>
      <select id="psort" class="sort" bind:value={sort}>
        <option value="recent">Recent</option><option value="name">Name</option><option value="length">Length</option>
      </select>
    </div>

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
        <p>{q ? `Nothing matches “${q}”` : view.startsWith("c:") ? "No reels in this collection yet: drag one onto it in the sidebar, or use a reel's ⋯ menu" : "Nothing here"}</p>
        {#if q || view !== "all"}<button class="btn" onclick={() => ((q = ""), (view = "all"), (shape = "any"))}>Show all projects</button>{/if}
      </div>
    {/if}

    <div class="grid">
      {#each shown as r (r.plan)}
        <div class="card" class:wide={r.width > r.height} class:dragging={dragging === r.plan} draggable="true" role="listitem"
             ondragstart={(e) => ((dragging = r.plan), e.dataTransfer.setData("text/plain", r.plan), (e.dataTransfer.effectAllowed = "move"))}
             ondragend={() => ((dragging = null), (over = null))}>
          <button class="tile" onclick={() => openReel(r.plan)} aria-label={`Open ${r.name}`}>
            <div class="thumb">
              {#if r.cover || r.storyboard}<img loading="lazy" src={media(r.cover || r.storyboard, r.modified)} alt="" draggable="false" />{/if}
              <span class="play" aria-hidden="true"><Icon name="play" size={18} /></span>
              {#if !r.rendered}<span class="tag">Plan</span>{:else if r.stale}<span class="tag">Edited</span>{/if}
              <span class="tcbox tc">{tc(r.duration)}</span>
            </div>
            <div class="name ellipsis">{r.name}</div>
            <div class="meta ellipsis">{[r.collection, r.width > r.height ? "16:9" : "9:16", ago(r.modified)].filter(Boolean).join(" · ")}</div>
          </button>
          <div class="quick" class:shown={r.pinned || r.favorite}>
            <button class="qb" class:on={r.pinned} onclick={() => act(r, r.pinned ? "unpin" : "pin")} aria-label={r.pinned ? "Unpin" : "Pin"} title={r.pinned ? "Unpin" : "Pin to the top"}><Icon name="pin" size={14} /></button>
            <button class="qb" class:on={r.favorite} onclick={() => act(r, r.favorite ? "unfavorite" : "favorite")} aria-label={r.favorite ? "Not a favourite" : "Favourite"} title="Favourite"><Icon name="heart" size={14} /></button>
          </div>
          <button class="more" onclick={() => (menu = menu === r.plan ? null : r.plan)} aria-label={`More for ${r.name}`} aria-expanded={menu === r.plan}>⋯</button>
          {#if menu === r.plan}
            <div class="menu surface" role="menu">
              <button role="menuitem" onclick={() => openReel(r.plan)}>Open</button>
              <button role="menuitem" onclick={() => ((menu = null), (ask = { kind: "rename", reel: r, value: r.name }))}>Rename…</button>
              <button role="menuitem" onclick={() => act(r, "duplicate")}>Duplicate</button>
              <button role="menuitem" onclick={() => ((menu = null), (ask = { kind: "collection", reel: r, value: r.collection || "" }))}>Collection…</button>
              {#if r.collection}<button role="menuitem" onclick={() => act(r, "collection", null)}>Take out of {r.collection}</button>{/if}
              <button role="menuitem" class="danger" onclick={() => ((menu = null), (ask = { kind: "delete", reel: r }))}>Move to the Trash…</button>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  </div>
</div>

{#if ask}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (Escape and Cancel close it) -->
  <div class="scrim" onclick={(e) => e.target === e.currentTarget && (ask = null)}>
    <div class="dialog surface" role="dialog" aria-modal="true" aria-label={ask.kind} tabindex="-1"
         onkeydown={(e) => (e.key === "Escape" && (ask = null), e.key === "Enter" && confirmAsk())}>
      {#if ask.kind === "delete"}
        <h2>Move {ask.reel.name} to the Trash?</h2>
        <p class="muted">Its video, plan and every file made with it go to the Trash, where you can put them back</p>
      {:else if ask.kind === "removecol"}
        <h2>Remove the collection {ask.name}?</h2>
        <p class="muted">Its reels stay where they are, outside any collection</p>
      {:else}
        <h2>{{ rename: "Rename", collection: "Collection", new: "New collection", renamecol: "Rename the collection" }[ask.kind]}</h2>
        <!-- svelte-ignore a11y_autofocus -->
        <input type="text" bind:value={ask.value} autofocus list="cols"
               placeholder={ask.kind === "collection" ? "e.g. Iceland 2026 (empty: none)" : ask.kind === "new" ? "e.g. West Coast 2026" : ""} />
        {#if ask.kind === "collection"}<datalist id="cols">{#each collections as c}<option value={c}></option>{/each}</datalist>{/if}
      {/if}
      <div class="row foot">
        <div class="spacer"></div>
        <button class="btn ghost" onclick={() => (ask = null)}>Cancel</button>
        <button class={ask.kind === "delete" || ask.kind === "removecol" ? "btn danger" : "btn primary"} onclick={confirmAsk}>
          {ask.kind === "delete" ? "Move to the Trash" : ask.kind === "removecol" ? "Remove" : ask.kind === "new" ? "Create" : "Save"}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .projects { height: 100%; display: grid; grid-template-columns: 224px minmax(0, 1fr); min-height: 0; }
  .side { border-right: 1px solid var(--line); padding: 48px 12px 24px; overflow: auto; display: flex; flex-direction: column; gap: 4px; }
  .group { display: flex; flex-direction: column; gap: 1px; }
  .ghead { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 4px; padding: 0 4px 0 10px;
           font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-3); }
  .item { flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; height: 32px; padding: 0 10px; border: 0; border-radius: var(--r-sm);
          background: transparent; color: var(--text-2); font-size: 13px; text-align: left; }
  .item:hover { background: var(--raised); color: var(--text); }
  .item.on { background: var(--accent-soft); color: var(--text); font-weight: 500; }
  .item .ellipsis { flex: 1; min-width: 0; }
  .n { font-size: 11px; }
  .citem { position: relative; display: flex; align-items: center; border-radius: var(--r-sm); }
  .citem.over { box-shadow: inset 0 0 0 2px var(--accent); background: var(--accent-soft); }
  .cmore { width: 24px; height: 24px; border: 0; background: transparent; color: var(--text-3); opacity: 0; border-radius: var(--r-sm); }
  .citem:hover .cmore, .cmore:focus-visible { opacity: 1; }
  .cmenu { left: 24px; right: auto; top: 30px; }
  .hint { padding: 4px 10px; margin: 0; }
  .main { min-width: 0; }
  .search {
    display: flex; align-items: center; gap: 8px; width: 220px; height: 36px; margin: 0; padding: 0 12px;
    background: var(--card); border: 1px solid var(--line-strong); border-radius: var(--r-ctl); color: var(--text-3); font-weight: 400;
  }
  .search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .search input { border: 0; padding: 0; min-height: 0; height: 34px; background: transparent; box-shadow: none; color: var(--text); }
  .search input:focus-visible { box-shadow: none; }
  .bar { margin: 12px 0 28px; gap: 8px; }
  .sortl { margin: 0; }
  .sort { width: auto; min-height: 32px; height: 32px; padding: 0 28px 0 10px; }
  .notice { margin: 0 0 24px; }
  /* fixed columns so an upright reel is one column and a wide one two, at the same height */
  .grid { display: grid; grid-template-columns: repeat(auto-fill, 160px); grid-auto-flow: dense; gap: 24px 16px; }
  .card { position: relative; border-radius: var(--r-card); }
  .card.wide { grid-column: span 2; }
  .card.dragging { opacity: 0.4; }
  .tile { width: 100%; border: 0; padding: 0; background: none; text-align: left; cursor: pointer; color: inherit; border-radius: var(--r-card); }
  .thumb { position: relative; height: 284px; border-radius: var(--r-card); overflow: hidden; background: var(--raised);
           box-shadow: inset 0 0 0 1px var(--line); margin-bottom: 8px; transition: box-shadow 150ms var(--ease); }
  .card:hover .thumb { box-shadow: inset 0 0 0 1px var(--line), 0 0 0 2px var(--line-strong); }
  .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .play { position: absolute; left: 50%; top: 50%; width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%;
          display: grid; place-items: center; background: rgba(15, 15, 16, 0.6); color: #ededed; opacity: 0; transition: opacity var(--fast) var(--ease); }
  .card:hover .play { opacity: 1; }
  .tag { position: absolute; left: 8px; bottom: 8px; font-size: 11px; line-height: 16px; padding: 2px 6px; border-radius: 4px; background: rgba(15, 15, 16, 0.72); color: #ededed; font-weight: 500; }
  .tcbox { position: absolute; right: 8px; bottom: 8px; font-size: 11px; line-height: 16px; padding: 2px 6px; border-radius: 4px; background: rgba(15, 15, 16, 0.72); color: #ededed; }
  .name { font-weight: 500; }
  .quick { position: absolute; left: 8px; top: 8px; display: flex; gap: 4px; opacity: 0; transition: opacity var(--fast) var(--ease); }
  .card:hover .quick, .quick.shown, .quick:focus-within { opacity: 1; }
  .qb { width: 28px; height: 28px; display: grid; place-items: center; border: 0; border-radius: var(--r-sm); background: rgba(15, 15, 16, 0.72); color: #cfcfcf; }
  .qb:hover { color: #fff; }
  .qb.on { color: var(--accent); }
  .quick.shown .qb:not(.on) { display: none; }
  .card:hover .quick.shown .qb { display: grid; }
  .more { position: absolute; right: 8px; top: 8px; width: 28px; height: 28px; border: 0; border-radius: var(--r-sm);
          background: rgba(15, 15, 16, 0.72); color: #ededed; opacity: 0; transition: opacity var(--fast) var(--ease); }
  .card:hover .more, .more:focus-visible, .more[aria-expanded="true"] { opacity: 1; }
  .menu { position: absolute; right: 8px; top: 40px; z-index: 20; display: flex; flex-direction: column; min-width: 200px; padding: 4px; box-shadow: var(--float); }
  .menu button { text-align: left; border: 0; background: transparent; padding: 8px 10px; border-radius: var(--r-sm); color: var(--text); font-size: 13px; }
  .menu button:hover { background: var(--raised); }
  .menu .danger { color: var(--err); }
  .scrim { position: fixed; inset: 0; background: var(--scrim); display: grid; place-items: center; z-index: 50; }
  .dialog { width: min(440px, 92vw); padding: 24px; display: flex; flex-direction: column; gap: 12px; box-shadow: var(--float); }
  .dialog .foot { gap: 8px; }
  @media (max-width: 960px) { .projects { grid-template-columns: 180px minmax(0, 1fr); } }
</style>
