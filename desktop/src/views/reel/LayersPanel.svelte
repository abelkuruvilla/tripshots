<script>
  // A shot's colour layers: corrections on parts of the frame (sky, subject, skin, greens, water, ground, edges), like
  // a colourist's windows and qualifiers after the primary grade. The colourist proposes them per frame; each can be
  // turned off, changed, removed, or added, and its mask shown on the picture.
  import Icon from "../../lib/Icon.svelte";
  import { ed, edit } from "./editor.svelte.js";

  let { shot } = $props();
  const names = { sky: "Sky", subject: "Subject", skin: "Skin", greens: "Greens", water: "Water", ground: "Ground", edges: "Edges" };
  const about = { sky: "above the skyline, clouds included", subject: "the person or main subject, found in every frame",
    skin: "skin tones on the people", greens: "foliage and grass", water: "sea, lakes and rivers below the sky",
    ground: "the lower frame, feathered from the horizon", edges: "everything around the subject" };
  const sliders = [
    ["exposure", "Exposure", -1.5, 1.5, 0.05, 0, (v) => `${v > 0 ? "+" : ""}${(+v).toFixed(2)}`],
    ["contrast", "Contrast", 0.6, 1.5, 0.01, 1, (v) => `${Math.round((v - 1) * 100)}`],
    ["saturation", "Saturation", 0, 2, 0.01, 1, (v) => `${Math.round((v - 1) * 100)}`],
    ["warmth", "Warmth", -1, 1, 0.01, 0, (v) => `${Math.round(v * 100)}`],
    ["tint", "Tint", -1, 1, 0.01, 0, (v) => `${Math.round(v * 100)}`],
    ["hue", "Hue", -45, 45, 1, 0, (v) => `${Math.round(v)}°`],
  ];

  let layers = $derived(shot?.layers || []);
  let open = $state(null); // the region being edited
  let vals = $state({});
  let key = "";
  $effect(() => {
    const l = layers.find((x) => x.region === open);
    const k = `${shot?.slot}|${open}|${JSON.stringify(l)}`;
    if (k !== key) {
      key = k;
      vals = Object.fromEntries(sliders.map(([s, , , , , n]) => [s, l?.[s] ?? n]));
    }
  });
  $effect(() => () => (ed.mask = null)); // leaving: no mask on the picture
  let missing = $derived(Object.keys(names).filter((r) => !layers.some((l) => l.region === r)));
  const summary = (l) => sliders.filter(([s, , , , , n]) => l[s] != null && l[s] !== n).map(([s, name, , , , , f]) => `${name} ${f(l[s])}`).join(" · ");

  const set = (o, quiet = true) => {
    ed.preview = true;
    return edit({ op: "layer", segment: shot.slot, ...o }, quiet);
  };
  async function add(region) {
    if (!region) return;
    await set({ region, exposure: region === "sky" ? -0.2 : region === "subject" ? 0.2 : region === "edges" ? -0.2 : 0,
                saturation: ["greens", "water"].includes(region) ? 1.1 : 1 });
    open = region;
  }
  function toggleMask(region) {
    ed.preview = true;
    ed.mask = ed.mask === region ? null : region;
  }
</script>

<div class="layers">
  <div class="row">
    <span class="quiet small">Sky, skin, water… each with its own correction</span>
    <div class="spacer"></div>
    {#if layers.some((l) => !l.auto)}
      <button class="btn sm ghost" onclick={() => edit({ op: "layers_auto", segment: shot.slot })} title="Back to what the colourist chose">Automatic</button>
    {/if}
  </div>

  {#if !layers.length}<p class="quiet small">No layers on this shot: the look alone grades it</p>{/if}
  <ul>
    {#each layers as l (l.region)}
      <li class:off={l.on === false} class:open={open === l.region}>
        <div class="head">
          <input type="checkbox" checked={l.on !== false} aria-label={`${names[l.region]} layer on`}
                 onchange={(e) => set({ region: l.region, on: e.currentTarget.checked })} />
          <button class="what" onclick={() => (open = open === l.region ? null : l.region)} aria-expanded={open === l.region}>
            <span class="name">{names[l.region]}</span>
            <span class="quiet small ellipsis">{l.why || summary(l)}</span>
          </button>
          <button class="btn sm ghost icon" class:pressed={ed.mask === l.region} aria-pressed={ed.mask === l.region}
                  onclick={() => toggleMask(l.region)} title="Show this layer's mask on the picture" aria-label={`Show the ${names[l.region]} mask`}><Icon name="eye" size={14} /></button>
        </div>
        {#if open === l.region}
          <div class="body">
            <p class="quiet small">{about[l.region]}{l.auto ? " · chosen by the colourist" : ""}</p>
            {#each sliders as [k, name, lo, hi, step, neutral, fmt]}
              <div class="sl">
                <label for={`l-${k}`}>{name}</label>
                <input id={`l-${k}`} type="range" min={lo} max={hi} {step} bind:value={vals[k]}
                       ondblclick={() => ((vals[k] = neutral), set({ region: l.region, [k]: neutral }))}
                       onchange={() => set({ region: l.region, [k]: +vals[k] })} />
                <span class="meta val">{fmt(vals[k])}</span>
              </div>
            {/each}
            <div class="row">
              <button class="btn sm" onclick={() => edit({ op: "layer", segment: "all", region: l.region, ...Object.fromEntries(sliders.map(([s]) => [s, +vals[s]])) })}
                      title="This layer, with these values, on every shot">Use on every shot</button>
              <div class="spacer"></div>
              <button class="btn sm ghost danger" onclick={() => { if (ed.mask === l.region) ed.mask = null; open = null; set({ region: l.region, remove: true }, false); }}>
                <Icon name="trash" size={14} /> Remove</button>
            </div>
          </div>
        {/if}
      </li>
    {/each}
  </ul>

  {#if missing.length}
    <label class="sr-only" for="addl">Add a layer</label>
    <select id="addl" class="add" value="" onchange={(e) => { add(e.currentTarget.value); e.currentTarget.value = ""; }}>
      <option value="">Add a layer…</option>
      {#each missing as r}<option value={r}>{names[r]}: {about[r]}</option>{/each}
    </select>
  {/if}
</div>

<style>
  .layers { display: flex; flex-direction: column; gap: 8px; }
  .layers .row { gap: 8px; }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  li { border-radius: var(--r-ctl); box-shadow: inset 0 0 0 1px var(--line); }
  li.open { box-shadow: inset 0 0 0 1px var(--line-strong); }
  li.off .what { opacity: 0.5; }
  .head { display: flex; align-items: center; gap: 8px; padding: 4px 4px 4px 12px; }
  .what { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 8px; height: 32px; border: 0; background: none; text-align: left; padding: 0; }
  .name { font-weight: 500; font-size: 13px; flex: none; }
  .body { padding: 4px 12px 12px; display: flex; flex-direction: column; gap: 6px; }
  .sl { display: grid; grid-template-columns: 76px 1fr 48px; gap: 12px; align-items: center; }
  .sl label { margin: 0; font-weight: 400; color: var(--text-2); }
  .val { text-align: right; }
  .pressed { background: var(--accent-soft); color: var(--text); }
  .add { min-height: 32px; padding: 4px 10px; font-size: 13px; }
</style>
