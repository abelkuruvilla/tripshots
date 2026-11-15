<script>
  import { onMount } from "svelte";
  import { app, api, startJob, toast } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let styles = $state([]);
  let links = $state("");
  let name = $state("");
  let add = $state(false);

  async function load() {
    styles = await api("/api/styles");
  }
  onMount(load);

  async function learn() {
    const refs = links.split(/\s+/).map((s) => s.trim()).filter(Boolean);
    if (!refs.length || !name.trim()) return toast("Paste reel links and give the style a name", "error");
    await startJob("learn", { refs, name, add }, `Learn ${name}`);
    links = "";
  }
</script>

<div class="page">
  <div class="page-head"><h1>Styles</h1><span class="muted">how a reel is cut: pace, shot lengths, text, colour</span></div>

  <div class="card box">
    <h2>Learn a style from reels you like</h2>
    <div class="field">
      <label>Reel links <span class="hint">· one or more Instagram reels or video files, separated by spaces or new lines</span></label>
      <textarea rows="3" bind:value={links} placeholder="https://www.instagram.com/reel/…"></textarea>
    </div>
    <div class="row">
      <input type="text" placeholder="style name" bind:value={name} style="max-width: 240px" />
      <label class="check"><input type="checkbox" bind:checked={add} /> add to an existing style</label>
      <div style="flex:1"></div>
      <button class="btn primary" onclick={learn}><Icon name="spark" size={15} /> Learn</button>
    </div>
    <p class="muted small">Each reel becomes a recipe (its cut, picture shape and words). Making a reel with one of these links as its sound follows that reel's own recipe.</p>
  </div>

  <div class="list">
    {#each styles as s}
      <div class="card st">
        <div class="row"><b>{s.name}</b>{#if s.user}<span class="badge">yours</span>{/if}
          {#if s.recipes}<span class="badge">{s.recipes} recipes</span>{/if}</div>
        <p class="muted">{s.description || "—"}</p>
        <button class="btn small" onclick={() => { app.view = "make"; }}>Use it</button>
      </div>
    {/each}
  </div>
</div>

<style>
  .box { padding: 18px 20px; max-width: 860px; margin-bottom: 20px; }
  .check { display: flex; align-items: center; gap: 6px; margin: 0; font-weight: 500; }
  .check input { width: auto; }
  .small { font-size: 12.5px; }
  .list { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
  .st { padding: 14px 16px; }
  .st p { font-size: 13px; margin: 8px 0 12px; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
</style>
