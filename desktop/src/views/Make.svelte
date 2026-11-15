<script>
  import { open } from "@tauri-apps/plugin-dialog";
  import { app, startJob, toast } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let sources = $state([...(app.status?.footage_folders || [])]);
  let sound = $state("");
  let style = $state("");
  let name = $state("");
  let orientation = $state("auto");
  let variants = $state(1);
  let planOnly = $state(false);
  let hook = $state("");
  let busy = $state(false);

  async function add(directory) {
    const got = await open(directory ? { directory: true, multiple: true, title: "Footage folders" } : { multiple: true, title: "Photos and clips" });
    for (const f of [got].flat().filter(Boolean)) if (!sources.includes(f)) sources.push(f);
  }
  async function pickAudio() {
    const got = await open({ title: "Music", filters: [{ name: "Audio", extensions: ["mp3", "m4a", "wav", "aac", "flac", "ogg"] }] });
    if (got) sound = got;
  }
  async function make() {
    if (!sources.length) return toast("Add a folder of photos and clips first", "error");
    busy = true;
    try {
      await startJob("make", {
        sources, music: sound.trim() || null, style: style || null, name: name.trim() || null,
        orientation, variants, dry_run: planOnly, hook: hook.trim() || null,
      }, name || "New reel");
      app.view = "jobs";
    } catch (e) {
      toast(String(e.message || e), "error");
    } finally {
      busy = false;
    }
  }
  const short = (p) => p.split(/[\\/]/).pop() || p;
</script>

<div class="page">
  <div class="page-head"><h1>New reel</h1></div>

  <div class="form">
    <section class="surface block">
      <div class="field">
        <label for="src">Footage <span class="hint">· folders are searched inside</span></label>
        <div class="chips" id="src">
          {#each sources as s, i}
            <span class="chip" title={s}><span class="ellipsis">{short(s)}</span>
              <button onclick={() => sources.splice(i, 1)} aria-label={`Remove ${short(s)}`}><Icon name="x" size={14} /></button></span>
          {/each}
          <button class="btn sm" onclick={() => add(true)}><Icon name="folder" size={14} /> Add folder</button>
          <button class="btn sm ghost" onclick={() => add(false)}>Add files</button>
        </div>
      </div>

      <div class="field last">
        <label for="snd">Sound <span class="hint">· a reel link uses its sound and its cut; an audio file is cut to its beat</span></label>
        <div class="row">
          <input id="snd" type="text" placeholder="instagram.com/reel/… or an audio file" bind:value={sound} />
          <button class="btn" onclick={pickAudio}><Icon name="music" /> Choose file</button>
        </div>
      </div>
    </section>

    <section class="surface block">
      <div class="grid2">
        <div class="field">
          <label for="sty">Style</label>
          <select id="sty" bind:value={style}>
            <option value="">Default</option>
            {#each app.status?.styles || [] as s}<option value={s}>{s}</option>{/each}
          </select>
        </div>
        <div class="field">
          <label for="nm">Name <span class="hint">· the file name</span></label>
          <input id="nm" type="text" placeholder="yellowstone" bind:value={name} />
        </div>
        <div class="field">
          <label for="shape">Shape</label>
          <select id="shape" bind:value={orientation}>
            <option value="auto">Automatic: upright, or wide when the footage is</option>
            <option value="vertical">Upright 9:16</option>
            <option value="horizontal">Wide 16:9</option>
          </select>
        </div>
        <div class="field">
          <label for="ver">Versions</label>
          <select id="ver" bind:value={variants}>
            {#each [1, 2, 3, 4] as n}<option value={n}>{n === 1 ? "One reel" : `${n} versions to compare`}</option>{/each}
          </select>
        </div>
      </div>
      <div class="field last">
        <label for="hook">Opening line <span class="hint">· optional, up to 7 words</span></label>
        <input id="hook" type="text" maxlength="60" bind:value={hook} />
      </div>
    </section>

    <div class="actions">
      <button class="btn primary lg" onclick={make} disabled={busy}>
        {#if busy}<span class="spin"></span>{:else}<Icon name="play" />{/if} {planOnly ? "Plan the reel" : "Make the reel"}
      </button>
      <label class="check"><input type="checkbox" bind:checked={planOnly} /> Plan only <span class="hint">· a storyboard in about a minute</span></label>
    </div>
    <p class="quiet note">Making a reel takes a few minutes. Activity shows its progress, and the reel opens from there</p>
  </div>
</div>

<style>
  .form { max-width: 760px; display: flex; flex-direction: column; gap: 16px; }
  .block { padding: 20px 24px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
  .field.last { margin-bottom: 0; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .chip { max-width: 280px; }
  .actions { display: flex; align-items: center; gap: 16px; margin-top: 8px; }
  .check { display: flex; align-items: center; gap: 8px; margin: 0; font-weight: 400; }
  .check input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
  .note { margin: 0; font-size: 13px; }
</style>
