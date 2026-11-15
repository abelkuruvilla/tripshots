<script>
  import { onMount } from "svelte";
  import { app, api, startJob, toast } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let styles = $state([]);
  let links = $state("");
  let name = $state("");
  let add = $state(false);

  onMount(async () => (styles = await api("/api/styles")));

  async function learn() {
    const refs = links.split(/\s+/).map((s) => s.trim()).filter(Boolean);
    if (!refs.length || !name.trim()) return toast("Paste reel links and give the style a name", "error");
    await startJob("learn", { refs, name, add }, `Learn ${name}`);
    links = "";
  }
</script>

<div class="page">
  <div class="page-head"><h1>Styles</h1><span class="meta">{styles.length}</span></div>
  <p class="page-sub">How a reel is cut: pace, shot lengths, words on screen and colour. Learn one from reels you like</p>

  <section class="surface learn">
    <div class="field">
      <label for="links">Reel links <span class="hint">· Instagram reels or video files, one per line</span></label>
      <textarea id="links" rows="3" bind:value={links} placeholder="instagram.com/reel/…"></textarea>
    </div>
    <div class="row">
      <input type="text" placeholder="Style name" bind:value={name} aria-label="Style name" style="max-width: 240px" />
      <label class="check"><input type="checkbox" bind:checked={add} /> Add to an existing style</label>
      <div class="spacer"></div>
      <button class="btn primary" onclick={learn}>Learn the style</button>
    </div>
    <p class="quiet note">Each reel becomes a recipe with its cut, picture shape and words. Making a reel with one of these links as its sound follows that reel's recipe</p>
  </section>

  <div class="list">
    {#each styles as s (s.name)}
      <article class="surface st">
        <div class="row">
          <h2>{s.name}</h2>
          <div class="spacer"></div>
          <span class="meta">{[s.user ? "yours" : "built in", s.recipes && `${s.recipes} recipes`].filter(Boolean).join(" · ")}</span>
        </div>
        <p>{s.description || "No description"}</p>
        <button class="btn sm" onclick={() => (app.view = "make")}><Icon name="plus" size={14} /> New reel</button>
      </article>
    {/each}
  </div>
</div>

<style>
  .spacer { flex: 1; }
  .learn { max-width: 860px; padding: 20px 24px; margin-bottom: 40px; display: flex; flex-direction: column; gap: 12px; }
  .learn .field { margin-bottom: 0; }
  .check { display: flex; align-items: center; gap: 8px; margin: 0; font-weight: 400; }
  .check input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
  .note { margin: 0; font-size: 13px; }
  .list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
  .st { padding: 16px 20px 20px; display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
  .st .row { width: 100%; }
  .st p { margin: 0 0 4px; font-size: 13px; color: var(--text-2); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
</style>
