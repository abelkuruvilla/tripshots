<script>
  // The post: caption, hashtags, search keywords and alt text, written for reach (social.py) and editable.
  import { revealItemInDir, openUrl } from "@tauri-apps/plugin-opener";
  import Icon from "../../lib/Icon.svelte";
  import { app, api, startJob, toast } from "../../lib/store.svelte.js";
  import { ed, load } from "./editor.svelte.js";

  const FIRST = 125;
  let caption = $state("");
  let saved = $state("");
  let tone = $state("");
  let jobId = $state(null);
  let showTone = $state(false);
  let lastPlan = "";
  $effect(() => {
    const r = ed.reel;
    if (r && (r.plan !== lastPlan || r.caption !== saved)) {
      lastPlan = r.plan;
      caption = saved = r.caption || "";
    }
  });

  let social = $derived(ed.reel?.social || null);
  let first = $derived(caption.split("\n")[0] || "");
  let writing = $derived(!!jobId && app.jobs.some((j) => j.id === jobId && j.state === "running"));
  // a caption job of this reel finished: show what it wrote
  $effect(() => {
    const j = jobId && app.jobs.find((x) => x.id === jobId);
    if (j && j.state !== "running") {
      jobId = null;
      if (j.state === "done") load();
    }
  });

  async function write() {
    try {
      const st = await startJob("caption", { plan: ed.reel.plan, tone: tone.trim() || null }, "Write the caption");
      jobId = st.id;
    } catch (e) {
      toast(String(e.message || e), "error");
    }
  }
  async function save() {
    await api("/api/caption", { plan: ed.reel.plan, text: caption });
    saved = caption;
    toast("Caption saved", "ok");
  }
  async function copy(text, what) {
    await navigator.clipboard.writeText(text);
    toast(`${what} copied`, "ok");
  }
  function useFirst(line) {
    const rest = caption.split("\n").slice(1).join("\n");
    caption = rest ? `${line}\n${rest}` : line;
  }
  const tags = (s) => (s?.hashtags || []).map((h) => "#" + h).join(" ");
  const file = (p) => (p || "").split(/[\\/]/).pop();
  let reel = $derived(ed.reel);
</script>

<section class="panel">
  <h2>Post it</h2>
  {#if reel?.upload}
    <ol class="how">
      <li>Upload <button class="link" onclick={() => revealItemInDir(reel.upload)}>{file(reel.upload)}</button></li>
      {#if reel.sound}<li>Add the sound <b>{reel.sound}</b> in Instagram, starting at <span class="tc">0:00.0</span>
        {#if reel.sound_url}<button class="link" onclick={() => openUrl(reel.sound_url)}>Open it</button>{/if}</li>{/if}
      <li>Paste the caption below</li>
    </ol>
  {:else if reel?.video}
    <ol class="how">
      <li>Upload <button class="link" onclick={() => revealItemInDir(reel.video)}>{file(reel.video)}</button></li>
      <li>Paste the caption below</li>
    </ol>
  {:else}
    <p class="muted">Render the reel first; then it's ready to upload</p>
  {/if}
</section>

<section class="panel">
  <div class="row">
    <h2>Caption</h2>
    <div class="spacer"></div>
    <button class="btn sm ghost" onclick={() => copy(caption, "Caption")} disabled={!caption}><Icon name="copy" size={14} /> Copy</button>
    <button class="btn sm" disabled={caption === saved} onclick={save}>Save</button>
  </div>
  <textarea rows="7" bind:value={caption} aria-label="Caption" placeholder="Write it yourself, or let TripShots write one made for reach"></textarea>
  <div class="row counts">
    <span class="meta" class:over={first.length > FIRST}>first line {first.length}/{FIRST}</span>
    <span class="quiet small">{first.length > FIRST ? "Only about 125 characters show before “more”" : "The first line shows before “more”: make it the hook"}</span>
  </div>

  <div class="row">
    <button class="btn sm primary" onclick={write} disabled={writing}>
      {#if writing}<span class="spin"></span> Writing{:else}<Icon name="sparkle" size={14} /> {social ? "Write again" : "Write it for reach"}{/if}
    </button>
    <button class="btn sm ghost" onclick={() => (showTone = !showTone)}>{showTone ? "Hide voice" : "Voice"}</button>
  </div>
  {#if showTone}
    <input type="text" bind:value={tone} placeholder="e.g. funny and short, or calm and poetic" aria-label="Voice of the caption" />
  {/if}

  {#if social}
    <div class="out">
      {#if social.alternatives?.length}
        <div class="block">
          <div class="head meta">Other first lines</div>
          {#each social.alternatives as a}
            <button class="alt" onclick={() => useFirst(a)} title="Use this as the first line">{a}</button>
          {/each}
        </div>
      {/if}

      {#if social.hashtags?.length}
        <div class="block">
          <div class="row head"><span class="meta">Hashtags · {social.hashtags.length} of 5 allowed</span><div class="spacer"></div>
            <button class="btn sm ghost" onclick={() => copy(tags(social), "Hashtags")}><Icon name="copy" size={14} /></button></div>
          <div class="chips">{#each social.hashtags as h}<span class="chip">#{h}</span>{/each}</div>
        </div>
      {/if}

      {#if social.keywords?.length}
        <div class="block">
          <div class="row head"><span class="meta">Search keywords</span><div class="spacer"></div>
            <button class="btn sm ghost" onclick={() => copy(social.keywords.join(", "), "Keywords")}><Icon name="copy" size={14} /></button></div>
          <div class="chips">{#each social.keywords as k}<span class="chip kw">{k}</span>{/each}</div>
          <p class="quiet small">Instagram search reads the caption: these work best said in it, and on screen in the first second{social.on_screen_keywords ? `, e.g. “${social.on_screen_keywords}”` : ""}</p>
        </div>
      {/if}

      {#if social.alt_text}
        <div class="block">
          <div class="row head"><span class="meta">Alt text</span><div class="spacer"></div>
            <button class="btn sm ghost" onclick={() => copy(social.alt_text, "Alt text")}><Icon name="copy" size={14} /></button></div>
          <p class="selectable">{social.alt_text}</p>
          <p class="quiet small">In Instagram: Advanced settings, Accessibility, Write alt text</p>
        </div>
      {/if}

      {#if social.first_comment}
        <div class="block">
          <div class="row head"><span class="meta">First comment to pin</span><div class="spacer"></div>
            <button class="btn sm ghost" onclick={() => copy(social.first_comment, "Comment")}><Icon name="copy" size={14} /></button></div>
          <p class="selectable">{social.first_comment}</p>
        </div>
      {/if}

      {#if social.checks?.length}<p class="warn small">{social.checks.join(". ")}</p>{/if}
      {#if social.why}<p class="quiet small">{social.why}</p>{/if}
    </div>
  {/if}
</section>

<style>
  .panel { padding: 20px; display: flex; flex-direction: column; gap: 12px; border-bottom: 1px solid var(--line); }
  .panel:last-child { border-bottom: 0; }
  .how { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; color: var(--text-2); }
  .how b { color: var(--text); }
  .panel p { margin: 0; }
  .spacer { flex: 1; }
  .counts { margin-top: -4px; gap: 12px; align-items: flex-start; }
  .counts .meta { white-space: nowrap; }
  .over { color: var(--err); }
  .small { font-size: 12px; line-height: 16px; }
  .out { display: flex; flex-direction: column; gap: 16px; border-top: 1px solid var(--line); padding-top: 16px; }
  .block { display: flex; flex-direction: column; gap: 8px; }
  .head { min-height: 28px; }
  .alt {
    text-align: left; padding: 8px 12px; border: 1px solid var(--line); border-radius: var(--r-ctl); background: none;
    cursor: pointer; font-size: 13px; color: var(--text-2); transition: border-color 150ms var(--ease), color 150ms var(--ease);
  }
  .alt:hover { border-color: var(--accent); color: var(--text); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { padding: 0 10px; user-select: text; }
  .chip.kw { background: transparent; box-shadow: inset 0 0 0 1px var(--line-strong); }
  .warn { color: var(--err); }
</style>
