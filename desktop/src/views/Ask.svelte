<script>
  import { app, api, startJob, openReel, toast } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let request = $state("");
  let jobId = $state(null);
  let job = $state(null);
  const examples = ["a reel about my days in Yellowstone", "the photos I'm in, set to something calm", "our road trip, fast and punchy, horizontal"];

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
      job = await api(`/api/jobs/${jobId}?lines=12`).catch(() => job);
      if (job && job.state !== "running") clearInterval(t);
    }, 1500);
    return () => clearInterval(t);
  });
  let plan = $derived(job?.result?.plan || job?.result?.reel?.plan || null);
</script>

<div class="page">
  <div class="page-head"><h1>Ask</h1><span class="muted">say what you want; TripShots finds the footage and makes it</span></div>
  <div class="card box">
    <textarea rows="3" placeholder="a reel about…" bind:value={request}
              onkeydown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && go()}></textarea>
    <div class="row">
      {#each examples as ex}<button class="chip" onclick={() => (request = ex)}>{ex}</button>{/each}
      <div style="flex:1"></div>
      <button class="btn primary" onclick={go} disabled={!request.trim() || job?.state === "running"}><Icon name="spark" size={15} /> Make it</button>
    </div>
    {#if !app.status?.footage_folders?.length}
      <p class="muted small">Tip: set your footage folders in Settings so TripShots knows where to look.</p>
    {/if}
  </div>

  {#if job}
    <div class="card box">
      <div class="row"><b>{job.state === "running" ? "Working…" : job.state === "done" ? "Done" : "Stopped"}</b>
        {#if job.state === "running"}<span class="spin"></span>{/if}
        <div style="flex:1"></div>
        {#if plan}<button class="btn primary small" onclick={() => openReel(plan)}>Open the reel</button>{/if}
      </div>
      <pre class="log mono selectable">{(job.log || []).join("\n")}{job.error ? "\n" + job.error : ""}</pre>
    </div>
  {/if}
</div>

<style>
  .box { padding: 16px; margin-bottom: 16px; max-width: 820px; display: flex; flex-direction: column; gap: 10px; }
  .chip { border: 0; cursor: pointer; }
  .small { font-size: 12.5px; }
  .log { background: var(--sunken); padding: 10px; border-radius: 8px; max-height: 300px; overflow: auto; white-space: pre-wrap; margin: 0; }
</style>
