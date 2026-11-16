<script>
  // Notes on the reel: stop where something is off, say what you see, send them all at once. The engine turns
  // them into edits (a still of each moment goes with it) and renders the reel again (revise.py).
  import { tick } from "svelte";
  import Icon from "../../lib/Icon.svelte";
  import { app, startJob, tc } from "../../lib/store.svelte.js";
  import { ed, addNote, removeNote, clearNotes } from "./editor.svelte.js";

  let { onseek, pause } = $props();
  let text = $state("");
  let box = $state(null);
  let reel = $derived(ed.reel);
  let job = $derived(app.jobs.find((j) => j.kind === "revise" && j.state === "running" && reel && j.label === reel.name + ".plan.json"));
  let last = $derived(reel?.revised);

  $effect(() => {
    if (ed.noting && box) tick().then(() => box?.focus());
  });

  const thumb = (t) => app.engine && reel
    ? `${app.engine.url}/api/still?t=${app.engine.token}&plan=${encodeURIComponent(reel.plan)}&at=${Math.max(0, Math.min(t, reel.duration - 0.04)).toFixed(2)}&v=${ed.version}`
    : "";

  function add() {
    if (!text.trim()) return;
    addNote(ed.now, text);
    text = "";
    ed.noting = false;
  }
  function keys(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      add();
    } else if (e.key === "Escape") {
      e.stopPropagation();
      ed.noting = false;
      box?.blur();
    }
  }
  async function send() {
    await startJob("revise", { plan: reel.plan, notes: ed.notes }, `${ed.notes.length} note${ed.notes.length > 1 ? "s" : ""}`);
    clearNotes();
  }
</script>

<div class="notes">
  <p class="muted small">Stop where something looks off and say what you see: "too dark", "swap this for the canyon", "the words cover her face". Send them together; the reel is edited and rendered again.</p>

  <div class="add">
    <div class="row">
      <span class="tc at">{tc(ed.now)}</span>
      <span class="quiet small">Note at the playhead</span>
      <div class="spacer"></div>
      <span class="quiet small"><kbd>N</kbd></span>
    </div>
    <label class="sr-only" for="note-box">Note at {tc(ed.now)}</label>
    <textarea id="note-box" bind:this={box} bind:value={text} rows="2" placeholder="What should change here?"
              onfocus={() => pause?.()} onkeydown={keys}></textarea>
    <div class="row">
      <div class="spacer"></div>
      <button class="btn sm" onclick={add} disabled={!text.trim()}><Icon name="plus" size={14} /> Add note</button>
    </div>
  </div>

  {#if ed.notes.length}
    <ul>
      {#each ed.notes as n, i (i + ":" + n.t + n.text)}
        <li>
          <button class="when" onclick={() => onseek(n.t)} title="Go to this moment">
            {#if thumb(n.t)}<img src={thumb(n.t)} alt="" loading="lazy" />{/if}
            <span class="tc">{tc(n.t)}</span>
          </button>
          <span class="what">{n.text}</span>
          <button class="btn sm ghost icon" onclick={() => removeNote(i)} aria-label={`Remove the note at ${tc(n.t)}`}><Icon name="x" size={14} /></button>
        </li>
      {/each}
    </ul>
  {/if}

  {#if job}
    <p class="state"><span class="spin"></span> Working on your notes: editing, then rendering again</p>
  {:else}
    <button class="btn primary" onclick={send} disabled={!ed.notes.length}>
      <Icon name="send" size={14} /> {ed.notes.length ? `Send ${ed.notes.length} note${ed.notes.length > 1 ? "s" : ""}` : "Send notes"}
    </button>
  {/if}

  {#if last?.answers?.length}
    <section class="done">
      <h3>Your last notes</h3>
      <ol>
        {#each last.answers as a}
          {@const n = last.notes?.[(a.note || 1) - 1]}
          <li>
            {#if n}<button class="link tc" onclick={() => onseek(n.t)}>{tc(n.t)}</button> <span class="quiet">"{n.text}"</span><br />{/if}
            {a.did}
          </li>
        {/each}
      </ol>
      {#if last.failed?.length}<p class="err-text small">{last.failed.length} change{last.failed.length > 1 ? "s" : ""} couldn't be made: {last.failed[0].why}</p>{/if}
    </section>
  {/if}
</div>

<style>
  .notes { display: flex; flex-direction: column; gap: 12px; padding: 16px; }
  .add { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: var(--r-card); box-shadow: inset 0 0 0 1px var(--line); }
  .add .row { gap: 8px; }
  .at { font-size: 13px; color: var(--accent); }
  textarea { resize: vertical; min-height: 56px; font: inherit; }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  li { display: flex; align-items: center; gap: 10px; }
  .when { display: flex; flex-direction: column; align-items: center; gap: 2px; border: 0; padding: 0; background: none; color: inherit; cursor: pointer; flex: none; }
  .when img { width: 40px; height: 72px; object-fit: cover; border-radius: 4px; background: var(--player); display: block; }
  .when .tc { font-size: 11px; }
  .what { flex: 1; min-width: 0; font-size: 13px; line-height: 18px; }
  .state { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .done { border-top: 1px solid var(--line); padding-top: 12px; }
  .done ol { margin: 8px 0 0; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; font-size: 13px; line-height: 18px; }
  .link { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; font-size: 12px; }
</style>
