<script>
  // Which part of a long clip plays in a slot: the whole clip under a bar, the slot's length as a window you drag,
  // the window playing on a loop above it, and "Let AI choose" (the AI looks at frames across the whole clip).
  import { onMount } from "svelte";
  import { app, api, media, tc, toast } from "../../lib/store.svelte.js";
  import Icon from "../../lib/Icon.svelte";

  // slot: the slot it plays in (null for a new slot of `dur` seconds); start: where it plays from now, if it's there
  let { plan, shot, slot = null, dur = null, start = null, back = "All shots", onuse, onback } = $props();

  let info = $state(null);
  let err = $state("");
  let at = $state(0);
  let ai = $state(null); // {in, why, by}
  let asking = $state(false);
  let video = $state(null);
  let bar = $state(null);
  let drag = null;

  const q = () => new URLSearchParams({ plan, shot: shot.id, ...(slot ? { slot } : { dur: dur ?? 1.5 }) });
  onMount(async () => {
    try {
      info = await api(`/api/clip?${q()}`);
      at = start ?? info.best_in;
    } catch (e) {
      err = String(e.message || e);
    }
  });

  let hi = $derived(info ? Math.max(0, info.length - info.need) : 0);
  const pct = (t) => `${(100 * t) / (info?.length || 1)}%`;
  const put = (t) => (at = Math.round(Math.max(0, Math.min(hi, t)) * 100) / 100);

  // the chosen part plays on a loop: a small cut of just that part, made when the window stops moving (a copy of a
  // whole long 4K clip would take minutes). While it's being made, the frame under the window shows.
  let playing = $state("");
  let ready = $state(false);
  let timer;
  $effect(() => {
    const t = at;
    if (!info || !app.engine) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      const q = new URLSearchParams({ t: app.engine.token, plan, shot: shot.id, at: t.toFixed(2), need: info.need.toFixed(2) });
      const url = `${app.engine.url}/api/clip/play?${q}`;
      if (url !== playing) ((ready = false), (playing = url));
    }, drag === null ? 150 : 600);
  });
  // the frame of the strip under the window's middle, while the cut is on its way
  let cell = $derived(info?.strip ? Math.min(13, Math.floor(((at + info.need / 2) / info.length) * 14)) : 0);

  // drag the window, or click the bar to put the window there
  function timeAt(e) {
    const r = bar.getBoundingClientRect();
    return (Math.max(0, Math.min(r.width, e.clientX - r.left)) / r.width) * info.length;
  }
  function down(e) {
    if (!info) return;
    const t = timeAt(e);
    drag = t >= at && t <= at + info.need ? t - at : info.need / 2;
    put(t - drag);
    bar.setPointerCapture(e.pointerId);
  }
  const move = (e) => drag !== null && put(timeAt(e) - drag);
  const up = () => (drag = null);
  function keys(e) {
    const step = e.shiftKey ? 1 : 0.1;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") put(at - step);
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") put(at + step);
    else if (e.key === "Home") put(0);
    else if (e.key === "End") put(hi);
    else return;
    e.preventDefault();
    e.stopPropagation();
  }

  async function askAI() {
    asking = true;
    try {
      ai = await api("/api/clip/ai", { plan, shot: shot.id, ...(slot ? { slot } : { dur: dur ?? 1.5 }) });
      if (ai.in != null) put(ai.in);
    } catch (e) {
      toast(String(e.message || e), "error");
    } finally {
      asking = false;
    }
  }
</script>

<div class="trim">
  <div class="row">
    <button class="btn ghost sm" onclick={onback}><Icon name="back" size={14} /> {back}</button>
    <div class="spacer"></div>
    <span class="meta">{shot.file}</span>
  </div>
  {#if err}
    <p class="quiet">Couldn't open this clip: {err}</p>
  {:else if !info}
    <div class="wait"><span class="spin"></span><span class="muted">Reading frames across the clip. A long clip takes a few seconds the first time</span></div>
  {:else}
    <p class="muted">The slot plays {tc(info.need)} of this {tc(info.length)} clip{info.speed < 1 ? ` (in slow motion, ${info.speed}×)` : ""}.
      Drag the window to the part you want, or let the AI choose.</p>
    <div class="stage">
      {#if info.strip}<span class="still" style:background-image={`url("${media(info.strip)}")`}
        style:background-position={`${(cell / 13) * 100}% 0`}></span>{/if}
      {#if playing}
        <!-- svelte-ignore a11y_media_has_caption (a silent cut of the clip) -->
        <video bind:this={video} class="player" class:ready src={playing} muted playsinline autoplay loop
               oncanplay={() => (ready = true)}></video>
      {/if}
      {#if !ready}<span class="loading"><span class="spin"></span></span>{/if}
    </div>
    <!-- svelte-ignore a11y_no_static_element_interactions (the window inside is the slider) -->
    <div class="bar" bind:this={bar} onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up}
         style:background-image={info.strip ? `url("${media(info.strip)}")` : "none"}>
      <span class="shade" style:left="0" style:width={pct(at)}></span>
      <span class="shade" style:left={pct(at + info.need)} style:right="0"></span>
      <span class="win" style:left={pct(at)} style:width={pct(info.need)} role="slider" tabindex="0"
            aria-label="Part of the clip that plays" aria-valuemin="0" aria-valuemax={hi} aria-valuenow={at}
            aria-valuetext={`from ${tc(at)} to ${tc(at + info.need)}`} onkeydown={keys}></span>
      <span class="tick" style:left={pct(info.best_in + info.need / 2)} title="TripShots' pick: the sharpest, steadiest part"></span>
      {#if ai?.in != null}<span class="tick ai" style:left={pct(ai.in + info.need / 2)} title="The AI's pick"></span>{/if}
    </div>
    <div class="row times">
      <span class="tc">{tc(at)} – {tc(at + info.need)}</span>
      <div class="spacer"></div>
      <span class="meta">← → move it · ⇧ by a second</span>
    </div>
    {#if ai?.why}<p class="why"><Icon name="wand" size={14} /> <span>{ai.why}</span></p>{/if}
    <div class="row">
      <button class="btn" onclick={askAI} disabled={asking || hi <= 0.05}>
        {#if asking}<span class="spin"></span> Looking at the clip{:else}<Icon name="wand" size={14} /> Let AI choose{/if}
      </button>
      <button class="btn ghost" onclick={() => put(info.best_in)} disabled={Math.abs(at - info.best_in) < 0.01}>TripShots' pick</button>
      <div class="spacer"></div>
      <button class="btn primary" onclick={() => onuse(at)}>Use this part</button>
    </div>
  {/if}
</div>

<style>
  .trim { display: flex; flex-direction: column; gap: 12px; }
  .wait { display: flex; align-items: center; gap: 12px; padding: 24px 0; }
  .stage { position: relative; height: 44vh; background: #000; border-radius: var(--r-card); overflow: hidden; }
  .still { position: absolute; inset: 0; background-size: 1400% 100%; filter: blur(1px); opacity: 0.7; }
  .player { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; opacity: 0; }
  .player.ready { opacity: 1; }
  .loading { position: absolute; right: 12px; bottom: 12px; }
  .bar {
    position: relative; height: 56px; border-radius: var(--r-sm); background-color: var(--raised);
    background-size: 100% 100%; cursor: pointer; touch-action: none; user-select: none; overflow: hidden;
  }
  .shade { position: absolute; top: 0; bottom: 0; background: rgba(10, 10, 12, 0.62); pointer-events: none; }
  .win {
    position: absolute; top: 0; bottom: 0; min-width: 6px; border: 2px solid var(--accent); border-radius: var(--r-sm);
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.4); cursor: grab;
  }
  .win:focus-visible { outline: 2px solid var(--text); outline-offset: 2px; }
  .tick { position: absolute; bottom: 0; width: 2px; height: 10px; margin-left: -1px; background: #fff; opacity: 0.8; pointer-events: none; }
  .tick.ai { background: var(--accent); height: 14px; opacity: 1; }
  .times { gap: 8px; }
  .why { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; margin: 0; color: var(--text-2); }
</style>
