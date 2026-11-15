<script>
  // The reel on a timeline: shots, the words on screen, and (expert) the beats. Click to jump. In expert mode,
  // drag a shot to reorder it, drag its right edge to change its length (snapped to the beat; hold Alt for frames),
  // drag a line of text to move it or its right edge to change how long it stays.
  import Icon from "../../lib/Icon.svelte";
  import { media, tc } from "../../lib/store.svelte.js";
  import { ed, edit, frames, select } from "./editor.svelte.js";

  let { onseek, onpick } = $props();
  let width = $state(800);
  let zoom = $state(1);
  let drag = $state(null); // what is being dragged, and where to

  let reel = $derived(ed.reel);
  let total = $derived(reel?.duration || 1);
  let pps = $derived(Math.max(8, ((width - 2) / total) * (ed.expert ? zoom : 1))); // pixels per second
  let inner = $derived(Math.max(width - 2, total * pps));
  let step = $derived(pps > 120 ? 0.5 : pps > 50 ? 1 : pps > 20 ? 2 : 5); // ruler labels

  // the words, in as few rows as fit without overlapping
  let lanes = $derived.by(() => {
    const ends = [];
    return (reel?.texts || []).map((t) => {
      let l = ends.findIndex((e) => e <= t.start + 0.01);
      if (l < 0) l = ends.length;
      ends[l] = t.start + t.duration;
      return { ...t, lane: Math.min(l, 3) };
    });
  });
  let nLanes = $derived(Math.max(1, ...lanes.map((t) => t.lane + 1)));

  const x = (s) => s * pps;
  const fromX = (px) => Math.max(0, Math.min(total, px / pps));
  const snapBeat = (t) => {
    const b = reel?.beats || [];
    if (!b.length) return frames(t);
    let best = b[0];
    for (const v of b) if (Math.abs(v - t) < Math.abs(best - t)) best = v;
    return Math.abs(best - t) * pps < 14 ? best : frames(t);
  };

  // ---- pointer drags (expert): reorder a shot, change a shot's length, move or stretch a text
  function begin(e, kind, item) {
    if (e.button !== 0) return;
    const box = e.currentTarget.closest(".tracks").getBoundingClientRect();
    drag = { kind, item, x0: e.clientX, left: box.left, moved: false, value: null };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.stopPropagation();
  }
  function move(e) {
    if (!drag) return;
    const dx = e.clientX - drag.x0;
    if (Math.abs(dx) > 4) drag.moved = true;
    if (!drag.moved) return;
    const t = fromX(e.clientX - drag.left);
    const it = drag.item;
    if (drag.kind === "reorder") {
      let to = reel.segments.findIndex((s) => t < s.start + s.dur);
      drag.value = to < 0 ? reel.segments.length : to + 1;
    } else if (drag.kind === "trim") {
      const end = e.altKey ? frames(it.start + it.dur + dx / pps) : snapBeat(it.start + it.dur + dx / pps);
      drag.value = Math.max(4 / 30, end - it.start);
    } else if (drag.kind === "tmove") {
      drag.value = Math.max(0, Math.min(total - it.duration, frames(it.start + dx / pps)));
    } else if (drag.kind === "tlen") {
      drag.value = Math.max(0.2, Math.min(total - it.start, frames(it.duration + dx / pps)));
    }
  }
  function end(e, click) {
    const d = drag;
    drag = null;
    if (!d) return;
    if (!d.moved) return click?.();
    if (d.value == null) return;
    if (d.kind === "reorder" && d.value !== d.item.slot) edit({ op: "move", from: d.item.slot, to: d.value });
    if (d.kind === "trim" && Math.abs(d.value - d.item.dur) > 0.01) edit({ op: "duration", segment: d.item.slot, dur: d.value });
    if (d.kind === "tmove") edit({ op: "edit_text", index: d.item.index, start: d.value }, true);
    if (d.kind === "tlen") edit({ op: "edit_text", index: d.item.index, duration: d.value }, true);
  }

  function clickShot(s) {
    onseek(s.start + 0.04);
    select({ kind: "clip", slot: s.slot });
  }
  function clickText(t) {
    select({ kind: "text", index: t.index });
    onseek(t.start + Math.min(1, t.duration / 2));
  }
  const wOf = (s) => (drag?.kind === "trim" && drag.item.slot === s.slot && drag.value != null ? drag.value : s.dur);
</script>

<div class="tl-head">
  <h2>Timeline</h2>
  <span class="meta">{[`${reel.segments.length} shots`, tc(total), reel.recipe && `recipe ${reel.recipe}`, reel.style].filter(Boolean).join(" · ")}</span>
  <div class="spacer"></div>
  {#if ed.expert}
    <label class="zoom meta" for="zm">Zoom</label>
    <input id="zm" class="range" type="range" min="1" max="8" step="0.25" bind:value={zoom} aria-label="Zoom the timeline" />
  {/if}
</div>

<div class="scroll" bind:clientWidth={width}>
  <div class="tracks" style="width: {inner}px" role="presentation" onpointermove={move}>
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (the player and the shots are the keyboard way) -->
    <div class="ruler" onclick={(e) => onseek(fromX(e.clientX - e.currentTarget.getBoundingClientRect().left))}>
      {#each Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step) as s}
        <span class="tick" style="left: {x(s)}px"><span class="meta">{tc(s).replace(/\.0$/, "")}</span></span>
      {/each}
      {#if ed.expert}
        {#each reel.beats || [] as b}<span class="beat" style="left: {x(b)}px"></span>{/each}
      {/if}
    </div>

    <div class="clips">
      {#each reel.segments as s (s.slot + ":" + s.shot_id + ":" + s.start)}
        <div class="slot" class:current={ed.now >= s.start && ed.now < s.start + s.dur}
             class:sel={ed.sel?.kind === "clip" && ed.sel.slot === s.slot}
             class:lifted={drag?.kind === "reorder" && drag.moved && drag.item.slot === s.slot}
             style="left: {x(s.start)}px; width: {Math.max(6, x(wOf(s)) - 2)}px">
          <button class="shot" title={`${s.slot}. ${s.file}${s.note ? ": " + s.note : ""}`}
                  onpointerdown={(e) => ed.expert && begin(e, "reorder", s)} onpointerup={(e) => (drag ? end(e, () => clickShot(s)) : null)}
                  onclick={() => !ed.expert && clickShot(s)}>
            {#if s.thumb}<img src={media(s.thumb)} alt="" loading="lazy" draggable="false" />{/if}
            {#if ed.expert && (s.speed && s.speed !== 1 || s.ramp)}<span class="badge meta">{s.ramp || `${s.speed}×`}</span>{/if}
          </button>
          <button class="swapbtn" onclick={() => onpick(s)} aria-label={`Replace shot ${s.slot}`} title="Replace this shot"><Icon name="swap" size={14} /></button>
          {#if ed.expert}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="handle" title="Drag to change the length (snaps to the beat, Alt for frames)"
                 onpointerdown={(e) => begin(e, "trim", s)} onpointerup={(e) => end(e)}></div>
            {#if s.transition}<span class="trans meta" title={`Transition: ${s.transition}`}>{s.transition}</span>{/if}
          {/if}
        </div>
      {/each}
      {#if drag?.kind === "reorder" && drag.moved && drag.value}
        {@const tgt = reel.segments[drag.value - 1]}
        {#if tgt}<div class="drop" style="left: {x(tgt.start)}px; width: {x(tgt.dur)}px"></div>{/if}
      {/if}
    </div>

    <div class="words" style="height: {nLanes * 28 + 4}px">
      {#each lanes as t (t.index)}
        {@const st = drag?.kind === "tmove" && drag.item.index === t.index && drag.value != null ? drag.value : t.start}
        {@const du = drag?.kind === "tlen" && drag.item.index === t.index && drag.value != null ? drag.value : t.duration}
        <div class="word" class:sel={ed.sel?.kind === "text" && ed.sel.index === t.index} class:cap={t.type === "caption"}
             style="left: {x(st)}px; width: {Math.max(8, x(du) - 2)}px; top: {t.lane * 28 + 2}px">
          <button class="wbody ellipsis" title={t.text}
                  onpointerdown={(e) => begin(e, "tmove", t)} onpointerup={(e) => end(e, () => clickText(t))}>{t.text}</button>
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div class="whandle" onpointerdown={(e) => begin(e, "tlen", t)} onpointerup={(e) => end(e)}></div>
        </div>
      {/each}
    </div>

    <div class="playhead" style="transform: translateX({x(ed.now)}px)"></div>
  </div>
</div>

<style>
  .tl-head { display: flex; align-items: center; gap: 12px; margin: 0 0 8px; min-height: 28px; }
  .spacer { flex: 1; }
  .zoom { margin: 0; }
  .range { width: 140px; accent-color: var(--accent); }
  .scroll { overflow-x: auto; overflow-y: hidden; padding-bottom: 8px; }
  .tracks { position: relative; touch-action: none; }
  .ruler { position: relative; height: 22px; cursor: pointer; border-bottom: 1px solid var(--line); margin-bottom: 6px; }
  .tick { position: absolute; top: 0; bottom: 0; border-left: 1px solid var(--line-strong); padding-left: 4px; }
  .tick .meta { font-size: 11px; line-height: 14px; }
  .beat { position: absolute; bottom: 0; width: 1px; height: 6px; background: var(--accent); opacity: 0.6; }
  .clips { position: relative; height: 80px; }
  .slot { position: absolute; top: 0; height: 80px; }
  .shot { width: 100%; height: 100%; border: 0; padding: 0; border-radius: 4px; overflow: hidden; cursor: pointer; background: var(--raised); position: relative; }
  .shot img { width: 100%; height: 100%; object-fit: cover; display: block; pointer-events: none; }
  .slot.current .shot { box-shadow: inset 0 0 0 2px var(--accent); }
  .slot.sel .shot { box-shadow: inset 0 0 0 2px var(--accent), 0 0 0 2px var(--accent-soft); }
  .slot.lifted { opacity: 0.5; }
  .badge { position: absolute; left: 4px; bottom: 4px; padding: 0 4px; border-radius: 4px; background: rgba(15, 15, 16, 0.72); color: #ededed; font-size: 10px; }
  .trans { position: absolute; right: 2px; bottom: -16px; font-size: 10px; color: var(--accent); white-space: nowrap; overflow: hidden; max-width: 100%; }
  .swapbtn {
    position: absolute; top: 4px; right: 4px; width: 24px; height: 24px; display: grid; place-items: center;
    border: 0; border-radius: var(--r-sm); background: rgba(15, 15, 16, 0.72); color: #ededed; cursor: pointer;
    opacity: 0; transition: opacity 150ms var(--ease);
  }
  .slot:hover .swapbtn, .swapbtn:focus-visible { opacity: 1; }
  .handle { position: absolute; top: 0; right: -4px; width: 8px; height: 100%; cursor: ew-resize; z-index: 2; }
  .handle::after { content: ""; position: absolute; top: 24px; bottom: 24px; left: 3px; width: 2px; border-radius: 1px; background: #ededed; opacity: 0; transition: opacity 150ms var(--ease); }
  .slot:hover .handle::after { opacity: 0.9; }
  .drop { position: absolute; top: -3px; height: 86px; border: 2px solid var(--accent); border-radius: 6px; pointer-events: none; }
  .words { position: relative; margin-top: 22px; }
  .word { position: absolute; height: 24px; }
  .wbody {
    width: 100%; height: 100%; border: 0; border-radius: 4px; padding: 0 8px; text-align: left; cursor: grab; font-size: 12px;
    background: var(--accent-soft); color: var(--text); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 35%, transparent);
  }
  .word.cap .wbody { background: var(--raised); box-shadow: inset 0 0 0 1px var(--line-strong); color: var(--text-2); }
  .word.sel .wbody { background: var(--accent); color: var(--accent-ink); }
  .whandle { position: absolute; top: 0; right: -3px; width: 8px; height: 100%; cursor: ew-resize; }
  .playhead { position: absolute; top: 0; bottom: 0; left: 0; width: 2px; margin-left: -1px; background: var(--accent); border-radius: 1px; pointer-events: none; }
</style>
