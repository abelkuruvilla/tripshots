<script>
  // Expert: the selected shot. Its length, which part of the clip plays, speed, transition, framing, and moving,
  // splitting, repeating, replacing or removing it. Every drag on the timeline has a button here too.
  import Icon from "../../lib/Icon.svelte";
  import { tc } from "../../lib/store.svelte.js";
  import { ed, edit, frames, select } from "./editor.svelte.js";

  let { onpick, oninsert } = $props();
  const transitions = [[null, "Hard cut"], ["whip", "Whip"], ["zoom_in", "Zoom in"], ["zoom_out", "Zoom out"], ["spin", "Spin"],
                       ["flash", "Flash"], ["glitch", "Glitch"], ["blur", "Blur"], ["dissolve", "Dissolve"], ["dip", "Dip to black"], ["leak", "Light leak"],
                       ["split", "Line reveal"], ["vsplit", "V reveal"], ["iris", "Circle reveal"],
                       ["slats", "Paper slats"], ["stripes", "Paper stripes"], ["diamond", "Paper diamond"], ["frame", "Framed window"], ["cells", "Grid cells"]];
  const ramps = [[null, "None"], ["velocity", "Velocity"], ["slam", "Slam"], ["bullet", "Bullet"], ["rush", "Rush"], ["impact", "Impact"], ["surge", "Surge"]];
  const layouts = [["crop", "Crop to the subject"], ["pan", "Pan across"], ["blur_fill", "Whole frame, blurred behind"], ["fill", "Fill (already upright)"]];
  const roles = { hook: "Opening", setup: "Setup", build: "Build", peak: "Peak", release: "Release", ending: "Ending" };

  let reel = $derived(ed.reel);
  let s = $derived(ed.sel?.kind === "clip" ? reel?.segments[ed.sel.slot - 1] : null);
  let video = $derived(s?.kind === "video" && !s.panel);
  let inside = $derived(s ? ed.now - s.start : 0);
  let canSplit = $derived(s && inside >= 0.07 && inside <= s.dur - 0.07 && !s.panel && !s.ramp);

  let dur = $state(1);
  let speed = $state(1);
  let from = $state(0);
  let sx = $state(0.5);
  let snap = $state(true);
  let key = "";
  $effect(() => {
    const k = s ? `${s.slot}|${s.dur}|${s.speed}|${s.in}|${s.subject_x}` : "-";
    if (k !== key) {
      key = k;
      if (s) {
        dur = s.dur;
        speed = s.speed || 1;
        from = s.in || 0;
        sx = s.subject_x ?? 0.5;
      }
    }
  });

  const op = (o, quiet = false) => edit({ segment: s.slot, ...o }, quiet);
  async function move(by) {
    const to = s.slot + by;
    if (to < 1 || to > reel.segments.length) return;
    await edit({ op: "move", from: s.slot, to }, true);
    select({ kind: "clip", slot: to });
  }
</script>

{#if !s}
  <div class="none">
    <Icon name="film" size={18} />
    <p>Select a shot on the timeline to change its length, speed, framing or transition</p>
    <p class="quiet small">Drag a shot to move it, drag its right edge to change its length</p>
  </div>
{:else}
  <section class="panel">
    <div class="row">
      <h2>Shot {s.slot}</h2>
      <span class="meta">{[tc(s.start), roles[s.role], s.kind === "video" ? "clip" : "photo"].filter(Boolean).join(" · ")}</span>
      <div class="spacer"></div>
      <button class="btn sm ghost icon" onclick={() => move(-1)} disabled={s.slot < 2} aria-label="Move earlier" title="Move earlier"><Icon name="arrow-left" size={14} /></button>
      <button class="btn sm ghost icon" onclick={() => move(1)} disabled={s.slot >= reel.segments.length} aria-label="Move later" title="Move later"><Icon name="arrow-right" size={14} /></button>
    </div>
    <p class="quiet ellipsis" title={s.note}>{s.file}{s.note ? ` · ${s.note}` : ""}</p>

    <div class="actions">
      <button class="btn sm" onclick={() => op({ op: "split", at: frames(inside) })} disabled={!canSplit}
              title="Cut this shot in two at the playhead"><Icon name="scissors" size={14} /> Split <kbd>S</kbd></button>
      <button class="btn sm" onclick={() => op({ op: "duplicate" })}><Icon name="copy" size={14} /> Repeat</button>
      <button class="btn sm" onclick={() => onpick(s)}><Icon name="swap" size={14} /> Replace</button>
      <button class="btn sm" onclick={() => oninsert(s.slot)}><Icon name="plus" size={14} /> Add after</button>
      <div class="spacer"></div>
      <button class="btn sm ghost danger" onclick={() => op({ op: "delete" })} disabled={reel.segments.length < 2}><Icon name="trash" size={14} /> Remove</button>
    </div>
  </section>

  <section class="panel">
    <h3>Timing</h3>
    <div class="grid2">
      <div class="field">
        <label for="id">Length <span class="hint">· seconds</span></label>
        <input id="id" type="number" step={1 / 30} min="0.13" bind:value={dur} disabled={!!s.panel}
               onchange={() => op({ op: "duration", dur: +dur, snap: snap ? "beat" : "frame" })} />
        <label class="check sub"><input type="checkbox" bind:checked={snap} /> End on a beat</label>
      </div>
      <div class="field">
        <label for="isp">Speed <span class="hint">· {video ? (s.ramp ? s.ramp : `${(+speed).toFixed(2)}×`) : "photos don't play"}</span></label>
        <input id="isp" type="range" min="0.25" max="4" step="0.05" bind:value={speed} disabled={!video}
               onchange={() => op({ op: "speed", speed: +speed })} />
        <div class="marks meta" aria-hidden="true"><span>slow</span><span>1×</span><span>fast</span></div>
      </div>
    </div>
    {#if video && s.clip?.[1] != null}
      <div class="field">
        <label for="ifr">Plays from <span class="hint">· {tc(from)} of the clip</span></label>
        <input id="ifr" type="range" min={s.clip[0]} max={Math.max(s.clip[0], s.clip[1] - s.dur * (s.speed || 1))} step="0.05"
               bind:value={from} onchange={() => op({ op: "slip", in: +from })} />
      </div>
    {/if}
    <div class="field">
      <label for="irp">Speed ramp</label>
      <select id="irp" value={s.ramp ?? ""} disabled={!video} onchange={(e) => op({ op: "ramp", ramp: e.currentTarget.value || null, hit: e.currentTarget.value ? frames(s.dur / 2) : undefined })}>
        {#each ramps as [id, name]}<option value={id ?? ""}>{name}</option>{/each}
      </select>
    </div>
  </section>

  <section class="panel">
    <h3>Into the next shot</h3>
    <div class="field">
      <label for="itr" class="sr-only">Transition</label>
      <select id="itr" value={s.transition ?? ""} onchange={(e) => op({ op: "transition", to: e.currentTarget.value || null })}>
        {#each transitions as [id, name]}<option value={id ?? ""}>{name}</option>{/each}
      </select>
      <p class="quiet small help">Hard cuts land on the beat; save transitions for a change of place or mood</p>
    </div>
  </section>

  {#if !s.panel && s.kind === "video"}
    <section class="panel">
      <h3>Framing</h3>
      <div class="field">
        <label for="ily" class="sr-only">Framing</label>
        <select id="ily" value={s.layout || "crop"} onchange={(e) => op({ op: "frame", layout: e.currentTarget.value })}>
          {#each layouts as [id, name]}<option value={id}>{name}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label for="isx">Looks at <span class="hint">· {sx < 0.4 ? "left" : sx > 0.6 ? "right" : "middle"}</span></label>
        <input id="isx" type="range" min="0" max="1" step="0.01" bind:value={sx} onchange={() => op({ op: "frame", subject_x: +sx })} />
      </div>
    </section>
    <section class="panel">
      <h3>Behind the person</h3>
      <div class="field">
        <label for="ibd" class="sr-only">Background</label>
        <select id="ibd" value={s.backdrop || "off"} onchange={(e) => op({ op: "backdrop", mode: e.currentTarget.value })}>
          <option value="off">Their own background</option>
          <option value="places">Other places of the trip, one per beat</option>
          <option value="colour">Flat colours from the shot, one per beat</option>
        </select>
        <p class="quiet small help">{s.people ? "The person stays; the world behind them changes on the beat, and the last beat is the real place again. Works best on a clip of you facing the camera, held still" : "Needs a clip with a person in it: the cut-out keeps only an upright figure"}</p>
      </div>
    </section>
  {/if}
{/if}

<style>
  .none { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 24px 20px; color: var(--text-2); }
  .panel { padding: 20px; display: flex; flex-direction: column; gap: 12px; border-bottom: 1px solid var(--line); }
  .panel:last-child { border-bottom: 0; }
  .actions { display: flex; flex-wrap: wrap; gap: 6px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .field { margin: 0; min-width: 0; }
  .marks { display: flex; justify-content: space-between; font-size: 10px; margin-top: 4px; }
  .sub { margin-top: 8px; font-size: 12px; color: var(--text-2); }
  .help { margin-top: 8px; }
  input[type="range"] { margin-top: 8px; }
  kbd { height: 16px; min-width: 16px; font-size: 10px; }
</style>
