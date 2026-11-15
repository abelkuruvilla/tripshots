<script>
  import { app, api, startJob, openReel, toast, clock } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let request = $state("");
  let jobId = $state(null);
  let job = $state(null);
  const examples = ["a reel about my days in Yellowstone", "the photos I'm in, set to something calm", "our road trip, fast, horizontal"];

  async function go() {
    if (!request.trim()) return;
    try {
      const st = await startJob("ask", { request }, request.slice(0, 40));
      jobId = st.id;
    } catch (e) {
      toast(String(e.message || e), "error");
    }
  }
  $effect(() => {
    if (!jobId) return;
    const t = setInterval(async () => {
      job = await api(`/api/jobs/${jobId}?lines=14`).catch(() => job);
      if (job && job.state !== "running") clearInterval(t);
    }, 1500);
    return () => clearInterval(t);
  });
  let plan = $derived(job?.result?.plan || job?.result?.reel?.plan || null);
</script>

<div class="page">
  <div class="page-head"><h1>Ask</h1></div>
  <p class="page-sub">Describe the reel. TripShots finds the footage in your folders, picks the shots and makes it</p>

  <div class="wrap">
    <div class="surface box">
      <textarea rows="3" placeholder="A reel about…" bind:value={request} aria-label="What reel to make"
                onkeydown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && go()}></textarea>
      <div class="examples">
        {#each examples as ex}<button class="ex" onclick={() => (request = ex)}>{ex}</button>{/each}
      </div>
      <div class="row actions">
        <span class="quiet small"><kbd>⌘</kbd> <kbd>↵</kbd> to start</span>
        <div class="spacer"></div>
        <button class="btn primary" onclick={go} disabled={!request.trim() || job?.state === "running"}>Make the reel</button>
      </div>
    </div>
    {#if !app.status?.footage_folders?.length}
      <p class="quiet tip">Set your footage folders in Settings so TripShots knows where to look</p>
    {/if}

    {#if job}
      <div class="surface box">
        <div class="row">
          <span class="dot {job.state === 'running' ? 'run' : job.state === 'done' ? 'ok' : 'err'}"></span>
          <h2>{job.state === "running" ? "Working" : job.state === "done" ? "Done" : "Stopped"}</h2>
          <span class="meta">{clock(job.elapsed_s)}</span>
          <div class="spacer"></div>
          {#if plan}<button class="btn primary sm" onclick={() => openReel(plan)}>Open the reel</button>{/if}
        </div>
        <pre class="log selectable">{(job.log || []).join("\n")}{job.error ? "\n" + job.error : ""}</pre>
      </div>
    {/if}
  </div>
</div>

<style>
  .wrap { max-width: 800px; display: flex; flex-direction: column; gap: 16px; }
  .box { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .box textarea { border: 0; padding: 4px; min-height: 72px; background: transparent; box-shadow: none; font-size: 15px; line-height: 22px; }
  .spacer { flex: 1; }
  .examples { display: flex; flex-wrap: wrap; gap: 8px; }
  .ex {
    height: 28px; padding: 0 12px; border: 1px solid var(--line); border-radius: var(--r-sm); background: transparent;
    color: var(--text-2); cursor: pointer; font-size: 13px; transition: background-color 150ms var(--ease), color 150ms var(--ease);
  }
  .ex:hover { background: var(--raised); color: var(--text); }
  .tip { margin: 0; font-size: 13px; }
  .actions { padding-top: 12px; border-top: 1px solid var(--line); }
  .small { font-size: 12px; }
  kbd {
    display: inline-grid; place-items: center; min-width: 20px; height: 20px; padding: 0 4px; border-radius: 4px;
    font: 11px/1 var(--mono); color: var(--text-2); background: var(--raised); box-shadow: inset 0 -1px 0 var(--line-strong);
  }
  .log { margin: 0; padding: 12px; max-height: 320px; overflow: auto; white-space: pre-wrap; border-radius: var(--r-ctl); background: var(--raised); font: 12px/18px var(--mono); color: var(--text-2); }
</style>
