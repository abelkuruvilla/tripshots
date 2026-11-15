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

  async function addFolder() {
    const got = await open({ directory: true, multiple: true, title: "Footage folders" });
    for (const f of [got].flat().filter(Boolean)) if (!sources.includes(f)) sources.push(f);
  }
  async function addFiles() {
    const got = await open({ multiple: true, title: "Photos and clips" });
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
</script>

<div class="page">
  <div class="page-head"><h1>New reel</h1></div>
  <div class="form card">
    <div class="field">
      <label>Footage <span class="hint">· folders or files; folders are searched inside</span></label>
      <div class="chips">
        {#each sources as s, i}
          <span class="chip" title={s}><span class="ellipsis">{s.split(/[\\/]/).pop() || s}</span>
            <button onclick={() => sources.splice(i, 1)} aria-label="remove"><Icon name="x" size={12} /></button></span>
        {/each}
        <button class="btn small" onclick={addFolder}><Icon name="folder" size={13} /> Add folder</button>
        <button class="btn small" onclick={addFiles}>Add files</button>
      </div>
    </div>

    <div class="field">
      <label>Sound <span class="hint">· a reel link (its sound and its cut are used), an audio file, or empty for silence</span></label>
      <div class="row">
        <input type="text" placeholder="https://www.instagram.com/reel/…" bind:value={sound} />
        <button class="btn" onclick={pickAudio}><Icon name="music" size={14} /> File</button>
      </div>
    </div>

    <div class="grid2">
      <div class="field">
        <label>Style</label>
        <select bind:value={style}>
          <option value="">Default</option>
          {#each app.status?.styles || [] as s}<option value={s}>{s}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Name <span class="hint">· file name of the reel</span></label>
        <input type="text" placeholder="e.g. yellowstone" bind:value={name} />
      </div>
      <div class="field">
        <label>Shape</label>
        <select bind:value={orientation}>
          <option value="auto">Automatic (upright, or wide when the footage is)</option>
          <option value="vertical">Upright 9:16</option>
          <option value="horizontal">Wide 16:9</option>
        </select>
      </div>
      <div class="field">
        <label>Versions</label>
        <select bind:value={variants}>
          {#each [1, 2, 3, 4] as n}<option value={n}>{n === 1 ? "One reel" : `${n} versions to compare`}</option>{/each}
        </select>
      </div>
    </div>

    <div class="field">
      <label>Opening line <span class="hint">· optional, 7 words max; empty lets TripShots write one when the style uses one</span></label>
      <input type="text" maxlength="60" bind:value={hook} />
    </div>

    <label class="check"><input type="checkbox" bind:checked={planOnly} /> Plan only <span class="hint">· a storyboard in about a minute; render it from the reel screen</span></label>

    <div class="actions">
      <button class="btn primary big" onclick={make} disabled={busy}>
        {#if busy}<span class="spin"></span>{:else}<Icon name="play" size={14} />{/if} {planOnly ? "Plan the reel" : "Make the reel"}
      </button>
      <span class="muted small">Takes a few minutes. You can keep using the app; it tells you when it's ready.</span>
    </div>
  </div>
</div>

<style>
  .form { max-width: 780px; padding: 22px 24px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .chip { max-width: 260px; }
  .check { display: flex; align-items: center; gap: 8px; font-weight: 500; margin: 4px 0 18px; }
  .check input { width: auto; }
  .actions { display: flex; align-items: center; gap: 14px; }
  .big { padding: 10px 18px; }
  .small { font-size: 12.5px; }
</style>
