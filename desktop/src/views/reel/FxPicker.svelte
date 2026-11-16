<script>
  // A grid from the effects library (fxlib.py), each item drawn on this reel's own shots: a transition as three
  // moments into the next shot, a shot effect as before | after. Filter by energy; the first tile clears it.
  import { app, api } from "../../lib/store.svelte.js";
  import { ed } from "./editor.svelte.js";

  let { kind = "transition", slot, value = null, onpick, none = "None" } = $props();
  let energy = $state("all");
  let lib = $state(null);

  $effect(() => {
    if (!lib) api("/api/effects").then((l) => (lib = l)).catch(() => (lib = { transitions: [], shot_effects: [] }));
  });
  let items = $derived((kind === "transition" ? lib?.transitions : lib?.shot_effects) || []);
  let shown = $derived(items.filter((x) => energy === "all" || x.energy === energy));
  const nice = (id) => id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const thumb = (id) => app.engine
    ? `${app.engine.url}/api/fxthumb?t=${app.engine.token}&plan=${encodeURIComponent(ed.reel.plan)}&slot=${slot}&kind=${kind}&id=${id}`
    : "";
</script>

<div class="seg energy" role="radiogroup" aria-label="Energy">
  {#each [["all", "All"], ["calm", "Calm"], ["medium", "Medium"], ["intense", "Intense"]] as [id, name]}
    <button role="radio" aria-checked={energy === id} onclick={() => (energy = id)}>{name}</button>
  {/each}
</div>
<div class="grid" class:wide={kind === "transition"}>
  <button class="tile" class:on={!value} onclick={() => onpick(null)}>
    <span class="blank">{none}</span>
    <span class="name">{none}</span>
  </button>
  {#each shown as x (x.id)}
    <button class="tile" class:on={value === x.id} onclick={() => onpick(x.id)} title={`${x.mood}. Suits ${x.suits}`}>
      <img src={thumb(x.id)} alt="" loading="lazy" />
      <span class="name">{nice(x.id)}</span>
    </button>
  {/each}
</div>

<style>
  .energy { margin-bottom: 8px; }
  .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; max-height: 340px; overflow: auto; padding: 2px; }
  .grid.wide { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tile {
    display: flex; flex-direction: column; gap: 4px; padding: 4px; border: 1px solid var(--line); border-radius: var(--r-sm);
    background: var(--card); color: inherit; cursor: pointer; text-align: left; transition: border-color var(--fast) var(--ease);
  }
  .tile:hover { border-color: var(--line-strong); }
  .tile.on { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .tile img, .blank { width: 100%; aspect-ratio: 9 / 8; object-fit: cover; border-radius: 3px; display: block; background: var(--raised); }
  .grid.wide .tile img, .grid.wide .blank { aspect-ratio: 27 / 16; }
  .blank { display: grid; place-items: center; color: var(--text-3); font-size: 12px; }
  .name { font-size: 12px; line-height: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
