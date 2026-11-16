<script>
  // A picture in picture: another shot on top of the reel for a while, in a corner (plan `pips`, render.Pips).
  import Icon from "../../lib/Icon.svelte";
  import { tc } from "../../lib/store.svelte.js";
  import { ed, edit, frames } from "./editor.svelte.js";

  let q = $derived(ed.sel?.kind === "pip" ? ed.reel?.pips?.find((x) => x.index === ed.sel.index) : null);
  let x = $state(0.72);
  let y = $state(0.28);
  let scale = $state(0.4);
  let len = $state(2);
  let key = "";
  $effect(() => {
    const k = q ? `${q.index}|${q.x}|${q.y}|${q.scale}|${q.dur}` : "";
    if (k !== key) {
      key = k;
      if (q) ((x = q.x), (y = q.y), (scale = q.scale), (len = q.dur));
    }
  });
  const set = (o) => edit({ op: "pip_edit", index: q.index, ...o }, true);
  const corners = [["Top left", 0.28, 0.24], ["Top right", 0.72, 0.24], ["Bottom left", 0.28, 0.66], ["Bottom right", 0.72, 0.66], ["Middle", 0.5, 0.45]];
</script>

{#if q}
  <section class="panel">
    <div class="row">
      <h2>On top {q.index}</h2>
      <span class="meta">{tc(q.start)} · {q.shot_id}</span>
      <div class="spacer"></div>
      <button class="btn sm ghost danger" onclick={() => ((ed.sel = null), edit({ op: "pip_delete", index: q.index }))}><Icon name="trash" size={14} /> Remove</button>
    </div>
    <div class="field">
      <span class="lbl">Where</span>
      <div class="corners">
        {#each corners as [name, cx, cy]}
          <button class="btn sm" class:on={Math.abs(x - cx) < 0.02 && Math.abs(y - cy) < 0.02} onclick={() => set({ x: cx, y: cy })}>{name}</button>
        {/each}
      </div>
    </div>
    <div class="grid2">
      <div class="field">
        <label for="px">Across <span class="hint">· {Math.round(x * 100)}%</span></label>
        <input id="px" type="range" min="0" max="1" step="0.01" bind:value={x} onchange={() => set({ x: +x })} />
      </div>
      <div class="field">
        <label for="py">Down <span class="hint">· {Math.round(y * 100)}%</span></label>
        <input id="py" type="range" min="0" max="1" step="0.01" bind:value={y} onchange={() => set({ y: +y })} />
      </div>
    </div>
    <div class="grid2">
      <div class="field">
        <label for="ps">Size <span class="hint">· {Math.round(scale * 100)}% wide</span></label>
        <input id="ps" type="range" min="0.15" max="1" step="0.01" bind:value={scale} onchange={() => set({ scale: +scale })} />
      </div>
      <div class="field">
        <label for="pl">Lasts <span class="hint">· s</span></label>
        <input id="pl" type="number" step="0.1" min="0.5" bind:value={len} onchange={() => set({ dur: frames(+len) })} />
      </div>
    </div>
    <button class="btn sm ghost" onclick={() => set({ start: frames(ed.now) })}>Start at the playhead</button>
    <p class="quiet small">Drag it on the timeline to move it, its right edge to change how long it stays. ⌫ removes it</p>
  </section>
{/if}

<style>
  .panel { padding: 20px; display: flex; flex-direction: column; gap: 12px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .field { margin: 0; min-width: 0; }
  .corners { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
  .btn.on { box-shadow: inset 0 0 0 1px var(--accent); color: var(--accent); }
  input[type="range"] { margin-top: 8px; }
</style>
