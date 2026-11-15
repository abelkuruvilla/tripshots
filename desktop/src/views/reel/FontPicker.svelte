<script>
  // Pick a font, each shown in its own face. Library fonts are fetched the first time they come into view.
  import { onMount } from "svelte";
  import Icon from "../../lib/Icon.svelte";
  import { ed, loadFonts, fontFamily } from "./editor.svelte.js";

  let { value = null, fallback = "montserrat", onpick } = $props();
  let open = $state(false);
  let q = $state("");
  let list = $state(null);
  const looks = ["bundled", "sans", "grotesque", "condensed", "rounded", "serif", "display", "script", "hand", "mono"];
  const lookName = { bundled: "In the app", sans: "Sans", grotesque: "Grotesque", condensed: "Condensed", rounded: "Rounded",
                     serif: "Serif", display: "Display", script: "Script", hand: "Handwritten", mono: "Typewriter" };
  onMount(loadFonts);

  let current = $derived(value || fallback);
  let label = $derived(ed.fonts.find((f) => f.id === current)?.label || current);
  let groups = $derived.by(() => {
    const term = q.trim().toLowerCase();
    const latin = ed.fonts.filter((f) => f.bundled || (f.scripts || []).includes("latin"));
    const hit = latin.filter((f) => !term || f.label.toLowerCase().includes(term) || f.look.includes(term));
    return looks.map((l) => ({ look: l, fonts: hit.filter((f) => f.look === l) })).filter((g) => g.fonts.length);
  });

  // load a face only once its row is on screen
  const shown = $state({});
  function lazy(node, id) {
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) {
        shown[id] = true;
        io.disconnect();
      }
    }, { root: list });
    io.observe(node);
    return { destroy: () => io.disconnect() };
  }
  function pick(id) {
    open = false;
    q = "";
    onpick?.(id);
  }
</script>

<svelte:window onkeydown={(e) => open && e.key === "Escape" && (open = false)} />

<div class="picker">
  <button class="current" onclick={() => (open = !open)} aria-haspopup="listbox" aria-expanded={open}>
    <span class="ellipsis" style="font-family: {fontFamily(current)}">{label}</span>
    <span class="quiet">{value ? "" : "style default"}</span>
  </button>
  {#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div class="scrim" onclick={() => (open = false)}></div>
    <div class="pop surface">
      <div class="search"><Icon name="search" size={14} /><input type="text" placeholder="Find a font" bind:value={q} aria-label="Find a font" /></div>
      <div class="list" bind:this={list} role="listbox" aria-label="Fonts">
        {#if value}<button class="opt reset" onclick={() => pick(null)}>Style default</button>{/if}
        {#each groups as g}
          <div class="group meta">{lookName[g.look] || g.look}</div>
          {#each g.fonts as f (f.id)}
            <button class="opt" class:on={f.id === current} role="option" aria-selected={f.id === current} onclick={() => pick(f.id)} use:lazy={f.id}>
              <span class="sample ellipsis" style="font-family: {shown[f.id] ? fontFamily(f.id) : 'inherit'}">{f.label}</span>
            </button>
          {/each}
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .picker { position: relative; }
  .current {
    width: 100%; height: 36px; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 12px;
    border: 1px solid var(--line-strong); border-radius: var(--r-ctl); background: var(--card); cursor: pointer; text-align: left;
  }
  .current span:first-child { font-size: 16px; }
  .current .quiet { font-size: 12px; flex: none; }
  .scrim { position: fixed; inset: 0; z-index: 30; }
  .pop { position: absolute; z-index: 31; left: 0; right: 0; top: 40px; box-shadow: var(--float); overflow: hidden; }
  .search { display: flex; align-items: center; gap: 8px; padding: 0 12px; border-bottom: 1px solid var(--line); color: var(--text-3); }
  .search input { border: 0; box-shadow: none; padding: 8px 0; background: transparent; }
  .list { max-height: 320px; overflow: auto; padding: 4px; }
  .group { padding: 12px 8px 4px; }
  .opt { width: 100%; display: flex; align-items: center; height: 36px; padding: 0 8px; border: 0; border-radius: var(--r-sm); background: none; cursor: pointer; text-align: left; }
  .opt:hover { background: var(--raised); }
  .opt.on { background: var(--accent-soft); }
  .opt.reset { color: var(--text-2); }
  .sample { font-size: 17px; }
</style>
