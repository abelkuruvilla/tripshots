<script>
  // Expert: the selected shot. Its length, which part of the clip plays, speed, transition, framing, and moving,
  // splitting, repeating, replacing or removing it. Every drag on the timeline has a button here too.
  import Icon from "../../lib/Icon.svelte";
  import { tc } from "../../lib/store.svelte.js";
  import { ed, edit, frames, select } from "./editor.svelte.js";
  import FxPicker from "./FxPicker.svelte";

  let { onpick, oninsert } = $props();
  const ramps = [[null, "None"], ["velocity", "Velocity"], ["slam", "Slam"], ["bullet", "Bullet"], ["rush", "Rush"], ["impact", "Impact"], ["surge", "Surge"]];
  const layouts = [["crop", "Crop to the subject"], ["pan", "Pan across"], ["blur_fill", "Whole frame, blurred behind"], ["fill", "Fill (already upright)"]];
  const roles = { hook: "Opening", setup: "Setup", build: "Build", peak: "Peak", release: "Release", ending: "Ending" };

  let reel = $derived(ed.reel);
  let s = $derived(ed.sel?.kind === "clip" ? reel?.segments[ed.sel.slot - 1] : null);
  let video = $derived(s?.kind === "video" && !s.panel);
  let inside = $derived(s ? ed.now - s.start : 0);
  let canSplit = $derived(s && inside >= 0.07 && inside <= s.dur - 0.07 && !s.panel && !s.ramp);
  let plain = $derived(video && !s.ramp && !s.freeze); // a moving clip without a ramp: it can be held or turned round

  let amount = $state(0.6);
  let dur = $state(1);
  let speed = $state(1);
  let from = $state(0);
  let sx = $state(0.5);
  let snap = $state(true);
  let key = "";
  $effect(() => {
    const k = s ? `${s.slot}|${s.dur}|${s.speed}|${s.in}|${s.subject_x}|${s.effect?.amount}` : "-";
    if (k !== key) {
      key = k;
      if (s) {
        dur = s.dur;
        speed = s.speed || 1;
        from = s.in || 0;
        sx = s.subject_x ?? 0.5;
        amount = s.effect?.amount ?? 0.6;
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
    <p>Select a shot on the timeline to change its length, speed, framing, transition or effect</p>
    <p class="quiet small">Drag a shot to move it, drag its edges to trim it</p>
  </div>
  <section class="panel">
    <h3>Effects</h3>
    {#if reel?.effects?.summary}<p class="quiet small">{reel.effects.summary} <span class="meta">({reel.effects.by === "ai" ? "AI" : "rules"})</span></p>{/if}
    <button class="btn sm" onclick={() => edit({ op: "auto_effects" })} disabled={ed.busy}
            title="The AI picks transitions, text motion and looks, and a shot effect or two, for this reel's shots and music">
      <Icon name="sparkle" size={14} /> Choose effects with AI</button>
    {#if reel?.effects?.why?.length}
      <ul class="why quiet small">{#each reel.effects.why.slice(0, 6) as w}<li>{w}</li>{/each}</ul>
    {/if}
  </section>
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
      <button class="btn sm" onclick={() => op({ op: "freeze", at: frames(Math.max(0, Math.min(s.dur, inside))), dur: 1 })}
              disabled={!plain} title="Hold the frame at the playhead for a second"><Icon name="pause" size={14} /> Freeze <kbd>F</kbd></button>
      <button class="btn sm" class:on={s.reverse} onclick={() => op({ op: "reverse", on: !s.reverse })} disabled={!plain && !s.reverse}
              aria-pressed={!!s.reverse} title="Play this clip backwards"><Icon name="undo" size={14} /> Reverse <kbd>R</kbd></button>
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
      {#if s.slot < reel.segments.length}
        <FxPicker kind="transition" slot={s.slot} value={s.transition} none="Hard cut" onpick={(id) => op({ op: "transition", to: id })} />
        <p class="quiet small help">Hard cuts land on the beat; save transitions for a change of place or mood</p>
      {:else}
        <p class="quiet small">The last shot: the reel ends here</p>
      {/if}
    </div>
  </section>

  {#if !s.panel}
    <section class="panel">
      <h3>Effect</h3>
      <FxPicker kind="effect" slot={s.slot} value={s.effect?.id} onpick={(id) => op({ op: "effect", id, amount: +amount })} />
      {#if s.effect}
        <div class="field">
          <label for="iam">Amount <span class="hint">· {Math.round(amount * 100)}%</span></label>
          <input id="iam" type="range" min="0.1" max="1" step="0.05" bind:value={amount} onchange={() => op({ op: "effect", id: s.effect.id, amount: +amount })} />
        </div>
      {/if}
    </section>
  {/if}

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
      <h3>Steadiness</h3>
      <label class="check"><input type="checkbox" checked={s.stabilize} onchange={(e) => op({ op: "stabilize", on: e.currentTarget.checked })} />
        Stabilise this clip</label>
      <p class="quiet small help">Takes the shake out of a handheld clip (a deliberate pan stays); the picture is zoomed in a little to hide the moving edges</p>
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
  .btn.on { box-shadow: inset 0 0 0 1px var(--accent); color: var(--accent); }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .field { margin: 0; min-width: 0; }
  .marks { display: flex; justify-content: space-between; font-size: 10px; margin-top: 4px; }
  .sub { margin-top: 8px; font-size: 12px; color: var(--text-2); }
  .help { margin-top: 8px; }
  .why { margin: 0; padding-left: 16px; display: flex; flex-direction: column; gap: 2px; }
  input[type="range"] { margin-top: 8px; }
  kbd { height: 16px; min-width: 16px; font-size: 10px; }
</style>
