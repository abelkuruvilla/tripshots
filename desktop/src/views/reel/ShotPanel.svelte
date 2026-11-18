<script>
  // Expert: the selected shot. Its length, which part of the clip plays, speed, transition, framing, and moving,
  // splitting, repeating, replacing or removing it. Every drag on the timeline has a button here too.
  import Icon from "../../lib/Icon.svelte";
  import { tc, toast } from "../../lib/store.svelte.js";
  import { ed, edit, frames, select } from "./editor.svelte.js";
  import FxPicker from "./FxPicker.svelte";
  import PipPanel from "./PipPanel.svelte";
  import Section from "../../lib/Section.svelte";

  let { onpick, oninsert, onontop, onpart, onpreview } = $props();

  // the effects director again; then say what it changed and offer to see it moving (the still shows only some of it)
  let choosing = $state(false);
  async function chooseEffects() {
    choosing = true;
    try {
      const res = await edit({ op: "auto_effects" }, true);
      const n = ed.reel?.effects?.changes?.length || 0;
      if (res) toast(n ? `${n} effect${n === 1 ? "" : "s"} chosen. Transitions and moves show in motion: Preview to see them` : "No change: the reel already suits its effects",
                     "ok", n && onpreview ? { label: "Preview", run: onpreview } : null);
    } finally {
      choosing = false;
    }
  }
  const ramps = [[null, "None"], ["velocity", "Velocity"], ["slam", "Slam"], ["bullet", "Bullet"], ["rush", "Rush"], ["impact", "Impact"], ["surge", "Surge"]];
  const layouts = [["crop", "Crop to the subject"], ["pan", "Pan across"], ["blur_fill", "Whole frame, blurred behind"], ["fill", "Fill (already upright)"]];
  const nice = (id) => id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const roles = { hook: "Opening", setup: "Setup", build: "Build", peak: "Peak", release: "Release", ending: "Ending" };

  let reel = $derived(ed.reel);
  let s = $derived(ed.sel?.kind === "clip" ? reel?.segments[ed.sel.slot - 1] : null);
  let video = $derived(s?.kind === "video" && !s.panel);
  let inside = $derived(s ? ed.now - s.start : 0);
  let canSplit = $derived(s && inside >= 0.07 && inside <= s.dur - 0.07 && !s.panel && !s.ramp);
  let plain = $derived(video && !s.ramp && !s.freeze); // a moving clip without a ramp: it can be held or turned round

  let amount = $state(0.6);
  // zoom and position at the playhead (keyframes): what the picture is set to there
  let kz = $state(1);
  let kx = $state(0.5);
  let ky = $state(0.5);
  let keyAt = $derived(s ? (s.keys || []).find((k) => Math.abs(k.t - inside) < 0.02) : null);
  $effect(() => {
    if (keyAt) ((kz = keyAt.zoom), (kx = keyAt.x), (ky = keyAt.y));
  });
  const keyHere = () => op({ op: "keyframe", t: frames(Math.max(0, Math.min(s.dur, inside))), zoom: +kz, x: +kx, y: +ky }, true);
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

{#snippet reelFx()}
  <Section id="shot-ai" title="Effects for the whole reel" open={!s} summary={reel?.effects ? (reel.effects.by === "ai" ? "chosen by AI" : "by rules") : ""}>
    {#if reel?.effects?.summary}<p class="quiet small">{reel.effects.summary}</p>{/if}
    <div class="row wrap">
      <button class="btn sm" onclick={chooseEffects} disabled={ed.busy || choosing}
              title="The AI picks transitions, text motion and looks, a shot effect or two and a signature move, for this reel's shots and music">
        {#if choosing}<span class="spin"></span> Choosing{:else}<Icon name="sparkle" size={14} /> Choose effects with AI{/if}</button>
      {#if reel?.effects?.changes?.length && onpreview}<button class="btn sm ghost" onclick={onpreview}><Icon name="play" size={14} /> Preview</button>{/if}
    </div>
    {#if reel?.effects?.changes?.length}
      <ul class="why small">{#each reel.effects.changes.slice(0, 10) as c}<li>{c.replace(/^move: /, "")}</li>{/each}</ul>
    {/if}
    {#if reel?.effects?.why?.length}
      <details class="small"><summary class="quiet">Why</summary>
        <ul class="why quiet small">{#each reel.effects.why.slice(0, 8) as w}<li>{w}</li>{/each}</ul></details>
    {/if}
    <p class="quiet small">Transitions and moves show in motion: <b>Preview</b> or render to see them. The still above shows colour, effects and framing.</p>
  </Section>
{/snippet}

{#if ed.sel?.kind === "pip"}
  <PipPanel />
{:else if !s}
  <div class="none">
    <Icon name="film" size={18} />
    <p>Select a shot on the timeline to edit it</p>
    <p class="quiet small">Drag a shot to move it, drag its edges to trim it</p>
  </div>
  {@render reelFx()}
{:else}
  <div class="head">
    <div class="row">
      <h2>Shot {s.slot}</h2>
      <span class="meta ellipsis">{[tc(s.start), roles[s.role], s.kind === "video" ? "clip" : "photo"].filter(Boolean).join(" · ")}</span>
      <div class="spacer"></div>
      <button class="btn sm ghost icon" onclick={() => move(-1)} disabled={s.slot < 2} aria-label="Move earlier" title="Move earlier"><Icon name="arrow-left" size={14} /></button>
      <button class="btn sm ghost icon" onclick={() => move(1)} disabled={s.slot >= reel.segments.length} aria-label="Move later" title="Move later"><Icon name="arrow-right" size={14} /></button>
    </div>
    <p class="quiet small ellipsis" title={s.note}>{s.file}{s.note ? ` · ${s.note}` : ""}</p>
    {#if s.size || s.vibes?.length}<p class="meta small ellipsis">{[s.size, s.angle, ...(s.vibes || [])].filter(Boolean).join(" · ")}</p>{/if}
    <div class="tools" role="toolbar" aria-label="Shot tools">
      <button class="tool" onclick={() => op({ op: "split", at: frames(inside) })} disabled={!canSplit} title="Split at the playhead (S)"><Icon name="scissors" size={16} /><span>Split</span></button>
      <button class="tool" onclick={() => op({ op: "freeze", at: frames(Math.max(0, Math.min(s.dur, inside))), dur: 1 })} disabled={!plain} title="Hold the frame at the playhead for a second (F)"><Icon name="pause" size={16} /><span>Freeze</span></button>
      <button class="tool" class:on={s.reverse} onclick={() => op({ op: "reverse", on: !s.reverse })} disabled={!plain && !s.reverse} aria-pressed={!!s.reverse} title="Play backwards (R)"><Icon name="undo" size={16} /><span>Reverse</span></button>
      <button class="tool" onclick={() => op({ op: "duplicate" })} title="Repeat this shot"><Icon name="copy" size={16} /><span>Repeat</span></button>
      <button class="tool" onclick={() => onpick(s)} title="Replace with another shot"><Icon name="swap" size={16} /><span>Replace</span></button>
      <button class="tool" onclick={() => oninsert(s.slot)} title="Add a shot after this one"><Icon name="plus" size={16} /><span>After</span></button>
      <button class="tool" onclick={() => onontop?.()} title="Put another shot on top, in a corner, from the playhead"><Icon name="layers" size={16} /><span>On top</span></button>
      <button class="tool danger" onclick={() => op({ op: "delete" })} disabled={reel.segments.length < 2} title="Remove this shot (⌫)"><Icon name="trash" size={16} /><span>Remove</span></button>
    </div>
  </div>

  <Section id="shot-timing" title="Timing" open={true}
           summary={`${(+s.dur).toFixed(2)} s${video ? ` · ${s.ramp || `${(+(s.speed || 1)).toFixed(2)}×`}` : ""}`}>
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
        <button class="btn sm ghost part" onclick={() => onpart?.(s)} disabled={!!s.panel || !!s.ramp}>
          <Icon name="scissors" size={14} /> Choose the part on the clip, or let AI choose</button>
      </div>
    {/if}
    <div class="field">
      <label for="irp">Speed ramp</label>
      <select id="irp" value={s.ramp ?? ""} disabled={!video} onchange={(e) => op({ op: "ramp", ramp: e.currentTarget.value || null, hit: e.currentTarget.value ? frames(s.dur / 2) : undefined })}>
        {#each ramps as [id, name]}<option value={id ?? ""}>{name}</option>{/each}
      </select>
    </div>
  </Section>

  {#if s.slot < reel.segments.length}
    {#if s.moves?.length}
      <Section id="shot-moves" title="Signature move" open={true} summary={s.moves.map((m) => m.name).join(", ")}>
        {#each s.moves as m}
          <div class="row">
            <span class="sparkle"><Icon name="sparkle" size={14} /></span>
            <span>{m.name}</span>
            <div class="spacer"></div>
            <button class="btn sm ghost" onclick={() => op({ op: "remove_move", id: m.id })}>Remove</button>
          </div>
        {/each}
        <p class="quiet small">Shows in motion: Preview or render to see it.</p>
      </Section>
    {/if}
    <Section id="shot-transition" title="Transition" summary={s.transition ? nice(s.transition) : "Hard cut"}>
      <FxPicker kind="transition" at={s.slot} value={s.transition} none="Hard cut" onpick={(id) => op({ op: "transition", to: id })} />
      <p class="quiet small">Into the next shot. Hard cuts land on the beat; save transitions for a change of place or mood</p>
    </Section>
  {/if}

  {#if !s.panel}
    <Section id="shot-effect" title="Effect" summary={s.effect ? `${nice(s.effect.id)} · ${Math.round((s.effect.amount ?? 0.6) * 100)}%` : "None"}>
      <FxPicker kind="effect" at={s.slot} value={s.effect?.id} onpick={(id) => op({ op: "effect", id, amount: +amount })} />
      {#if s.effect}
        <div class="field">
          <label for="iam">Amount <span class="hint">· {Math.round(amount * 100)}%</span></label>
          <input id="iam" type="range" min="0.1" max="1" step="0.05" bind:value={amount} onchange={() => op({ op: "effect", id: s.effect.id, amount: +amount })} />
        </div>
      {/if}
    </Section>

    <Section id="shot-keys" title="Zoom and position" summary={(s.keys || []).length ? `${s.keys.length} keyframe${s.keys.length > 1 ? "s" : ""}` : "None"}>
      <div class="grid3">
        <div class="field">
          <label for="kz">Zoom <span class="hint">· {(+kz).toFixed(2)}×</span></label>
          <input id="kz" type="range" min="1" max="3" step="0.05" bind:value={kz} onchange={() => (keyAt || s.keys?.length) && keyHere()} />
        </div>
        <div class="field">
          <label for="kx">Across</label>
          <input id="kx" type="range" min="0" max="1" step="0.01" bind:value={kx} onchange={() => (keyAt || s.keys?.length) && keyHere()} />
        </div>
        <div class="field">
          <label for="ky">Down</label>
          <input id="ky" type="range" min="0" max="1" step="0.01" bind:value={ky} onchange={() => (keyAt || s.keys?.length) && keyHere()} />
        </div>
      </div>
      <div class="actions">
        <button class="btn sm" onclick={keyHere} title="Set the zoom and position at the playhead; the picture moves smoothly between keyframes">
          <Icon name="plus" size={14} /> Keyframe here</button>
        {#if keyAt}<button class="btn sm ghost" onclick={() => op({ op: "keyframe", t: keyAt.t, remove: true }, true)}>Remove this one</button>{/if}
        {#if s.keys?.length}<button class="btn sm ghost" onclick={() => op({ op: "keyframe", clear: true }, true)}>Clear all</button>{/if}
      </div>
      {#if s.keys?.length}
        <div class="keys">
          {#each s.keys as k}
            <button class="kchip" class:on={keyAt?.t === k.t} onclick={() => ed.now = s.start + k.t + 0.001}>{tc(k.t)} · {k.zoom}×</button>
          {/each}
        </div>
      {:else}
        <p class="quiet small">Two keyframes make a move: a slow push in onto a face, a pan across a skyline</p>
      {/if}
    </Section>
  {/if}

  {#if !s.panel && s.kind === "video"}
    <Section id="shot-framing" title="Framing" summary={(layouts.find(([id]) => id === (s.layout || "crop")) || [, ""])[1]}>
      <select id="ily" aria-label="Framing" value={s.layout || "crop"} onchange={(e) => op({ op: "frame", layout: e.currentTarget.value })}>
        {#each layouts as [id, name]}<option value={id}>{name}</option>{/each}
      </select>
      <div class="field">
        <label for="isx">Looks at <span class="hint">· {sx < 0.4 ? "left" : sx > 0.6 ? "right" : "middle"}</span></label>
        <input id="isx" type="range" min="0" max="1" step="0.01" bind:value={sx} onchange={() => op({ op: "frame", subject_x: +sx })} />
      </div>
    </Section>
    <Section id="shot-steady" title="Steadiness" summary={s.stabilize ? "Stabilised" : "As filmed"}>
      <label class="check"><input type="checkbox" checked={s.stabilize} onchange={(e) => op({ op: "stabilize", on: e.currentTarget.checked })} />
        Stabilise this clip</label>
      <p class="quiet small">Takes the shake out of a handheld clip (a deliberate pan stays); the picture is zoomed in a little to hide the moving edges</p>
    </Section>
    <Section id="shot-backdrop" title="Behind the person" summary={s.backdrop === "places" ? "Other places" : s.backdrop === "colour" ? "Flat colours" : "Own background"}>
      <select id="ibd" aria-label="Background" value={s.backdrop || "off"} onchange={(e) => op({ op: "backdrop", mode: e.currentTarget.value })}>
        <option value="off">Their own background</option>
        <option value="places">Other places of the trip, one per beat</option>
        <option value="colour">Flat colours from the shot, one per beat</option>
      </select>
      <p class="quiet small">{s.people ? "The person stays; the world behind them changes on the beat, and the last beat is the real place again. Works best on a clip of you facing the camera, held still" : "Needs a clip with a person in it: the cut-out keeps only an upright figure"}</p>
    </Section>
  {/if}
  {@render reelFx()}
{/if}

<style>
  .none { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding: 20px 16px; color: var(--text-2); border-bottom: 1px solid var(--line); }
  .head { padding: 12px 12px 8px 16px; display: flex; flex-direction: column; gap: 4px; border-bottom: 1px solid var(--line);
          position: sticky; top: 0; z-index: 2; background: var(--card); }
  .head h2 { font-size: 15px; }
  .tools { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 2px; margin-top: 2px; }
  .tool { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 0 5px; border: 0; border-radius: var(--r-sm);
          background: transparent; color: var(--text-2); font-size: 9.5px; line-height: 11px; white-space: nowrap; min-width: 0;
          transition: background-color var(--fast) var(--ease), color var(--fast) var(--ease); }
  .tool span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
  .tool.on { background: var(--accent-soft); }
  .tool:hover:not(:disabled) { background: var(--raised); color: var(--text); }
  .tool:disabled { opacity: 0.4; cursor: default; }
  .tool.on { border-color: var(--accent); color: var(--accent); }
  .tool.danger:hover:not(:disabled) { color: var(--err); }
  .actions { display: flex; flex-wrap: wrap; gap: 6px; }
  .btn.on { box-shadow: inset 0 0 0 1px var(--accent); color: var(--accent); }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .field { margin: 0; min-width: 0; }
  .marks { display: flex; justify-content: space-between; font-size: 10px; margin-top: 4px; }
  .sub { margin-top: 8px; font-size: 12px; color: var(--text-2); }
  .grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .keys { display: flex; flex-wrap: wrap; gap: 6px; }
  .kchip { font-size: 11px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--line-strong); background: var(--card); color: var(--text-2); cursor: pointer; }
  .kchip.on { border-color: var(--accent); color: var(--accent); }
  .why { margin: 0; padding-left: 16px; display: flex; flex-direction: column; gap: 2px; }
  input[type="range"] { margin-top: 8px; }
  kbd { height: 16px; min-width: 16px; font-size: 10px; }
  .part { align-self: flex-start; margin-top: 4px; }
  .sparkle { color: var(--accent); display: grid; place-items: center; }
  .row.wrap { flex-wrap: wrap; }
</style>
