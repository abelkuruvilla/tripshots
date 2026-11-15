<script>
  // Styles: how a reel is cut. Yours first (learned from reels you like), then the built-in ones. Learning a new one
  // opens in a sheet.
  import { onMount } from "svelte";
  import { app, api, startJob, toast } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";
  import Sheet from "../lib/Sheet.svelte";

  let styles = $state([]);
  let learning = $state(false);
  let links = $state("");
  let name = $state("");
  let addTo = $state("");
  let err = $state("");

  onMount(async () => (styles = await api("/api/styles").catch(() => [])));
  let mine = $derived(styles.filter((s) => s.user));
  let builtin = $derived(styles.filter((s) => !s.user));
  const nice = (n) => n.replace(/[-_]+/g, " ").replace(/^./, (c) => c.toUpperCase());
  const facts = (s) => [s.user ? "Yours" : "Built in", s.recipes && `${s.recipes} ${s.recipes === 1 ? "recipe" : "recipes"}`].filter(Boolean).join(" · ");

  function make(style) {
    app.prefill = { style: style.name };
    app.view = "make";
  }
  async function learn() {
    const refs = links.split(/\s+/).map((s) => s.trim()).filter(Boolean);
    const target = addTo || name.trim();
    err = !refs.length ? "Paste at least one reel link or video file" : !target ? "Give the style a name" : "";
    if (err) return;
    try {
      await startJob("learn", { refs, name: target, add: !!addTo }, `Learn ${target}`);
      learning = false;
      links = name = addTo = "";
    } catch (e) {
      toast(String(e.message || e), "error");
    }
  }
</script>

<div class="page">
  <div class="page-head">
    <h1>Styles</h1>
    <span class="meta">{styles.length}</span>
    <div class="spacer"></div>
    <button class="btn primary" onclick={() => (learning = true)}><Icon name="plus" /> Learn a style</button>
  </div>
  <p class="page-sub">How a reel is cut: its pace, shot lengths, words on screen and colour. Learn one from reels you like, and each of them becomes a recipe to follow</p>

  {#each [["Yours", mine], ["Built in", builtin]] as [title, list]}
    {#if list.length}
      <section>
        <h2 class="group">{title}</h2>
        <ul class="list surface">
          {#each list as s (s.name)}
            <li>
              <div class="what">
                <div class="row"><h3>{nice(s.name)}</h3><span class="meta">{facts(s)}</span></div>
                <p class="muted">{s.description || "Learned from reels you liked"}</p>
              </div>
              <div class="acts">
                {#if s.user}<button class="btn sm ghost" onclick={() => { addTo = s.name; learning = true; }}>Add examples</button>{/if}
                <button class="btn sm" onclick={() => make(s)}>Make a reel</button>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {:else}
    <div class="empty"><span class="spin"></span></div>
  {/each}
</div>

{#if learning}
  <Sheet title={addTo ? `Add examples to ${nice(addTo)}` : "Learn a style"} onclose={() => ((learning = false), (addTo = ""), (err = ""))}>
    <div class="form">
      <p class="muted">Paste links to reels whose cut, words and colour you like. TripShots watches each one and keeps it as a recipe: a reel made on that reel's sound follows it shot for shot</p>
      <div class="field">
        <label for="links">Reels <span class="hint">· Instagram links or video files, one per line</span></label>
        <textarea id="links" rows="6" bind:value={links} placeholder="instagram.com/reel/…"></textarea>
      </div>
      {#if !addTo}
        <div class="field">
          <label for="sn">Name</label>
          <input id="sn" type="text" placeholder="west coast" bind:value={name} />
        </div>
      {/if}
      {#if err}<p class="err-text" role="alert">{err}</p>{/if}
      <p class="quiet small">Learning takes a few minutes per reel; Activity shows how far it is. Instagram links need your Instagram login, borrowed from the browser set in Settings</p>
    </div>
    {#snippet foot()}
      <div class="spacer"></div>
      <button class="btn ghost" onclick={() => ((learning = false), (addTo = ""))}>Cancel</button>
      <button class="btn primary" onclick={learn}>{addTo ? "Add them" : "Learn the style"}</button>
    {/snippet}
  </Sheet>
{/if}

<style>
  section + section { margin-top: 32px; }
  .group { font-size: 13px; color: var(--text-2); margin-bottom: 12px; }
  .list { list-style: none; margin: 0; padding: 0; max-width: 1040px; }
  .list li { display: flex; align-items: center; gap: 24px; padding: 16px 20px; }
  .list li + li { border-top: 1px solid var(--line); }
  .what { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .what .row { gap: 12px; }
  .what p { font-size: 13px; display: -webkit-box; line-clamp: 2; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; max-width: 720px; }
  .acts { display: flex; gap: 8px; flex: none; }
  .form { display: flex; flex-direction: column; gap: 20px; }
  .form .field { margin: 0; }
</style>
