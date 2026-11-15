<script>
  import { app, api, openReel, pollJobs, clock } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let open = $state(app.jobs[0]?.id || null);
  let detail = $state(null);

  $effect(() => {
    if (!open) return;
    let alive = true;
    const tick = async () => {
      detail = await api(`/api/jobs/${open}?lines=200`).catch(() => detail);
      if (alive && detail?.state === "running") setTimeout(tick, 1200);
    };
    tick();
    return () => (alive = false);
  });

  async function cancel(id) {
    await api(`/api/jobs/${id}/cancel`, {});
    pollJobs();
  }
  const planOf = (d) => d?.result?.plan || d?.result?.variants?.[0]?.plan;
  const tone = (s) => (s === "running" ? "run" : s === "done" ? "ok" : "err");
</script>

<div class="page">
  <div class="page-head"><h1>Activity</h1><span class="meta">{app.jobs.length}</span></div>
  <p class="page-sub">Reels being made, rendered and learned, from this app, the command line or an AI agent</p>

  {#if !app.jobs.length}
    <div class="empty">Nothing has run yet</div>
  {:else}
    <div class="split">
      <div class="list surface">
        {#each app.jobs as j (j.id)}
          <button class="item" class:on={open === j.id} onclick={() => (open = j.id)}>
            <span class="dot {tone(j.state)}"></span>
            <span class="what ellipsis"><span class="kind">{j.kind}</span> <span class="muted">{j.label || ""}</span></span>
            <span class="meta">{clock(j.elapsed_s)}</span>
          </button>
        {/each}
      </div>
      <div class="detail surface">
        {#if detail}
          <div class="row">
            <span class="dot {tone(detail.state)}"></span>
            <h2>{detail.kind}</h2>
            <span class="muted ellipsis">{detail.label}</span>
            <div class="spacer"></div>
            {#if detail.state === "running"}<button class="btn sm" onclick={() => cancel(detail.id)}><Icon name="x" size={14} /> Stop</button>{/if}
            {#if planOf(detail)}<button class="btn primary sm" onclick={() => openReel(planOf(detail))}>Open the reel</button>{/if}
          </div>
          <div class="meta cmd selectable">{detail.command}</div>
          <pre class="log selectable">{(detail.log || []).join("\n")}{detail.error ? "\n\n" + detail.error : ""}</pre>
        {:else}
          <div class="empty">Select a job to see its log</div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .spacer { flex: 1; }
  .split { display: grid; grid-template-columns: 320px 1fr; gap: 16px; align-items: start; }
  .list { padding: 4px; max-height: calc(100vh - 200px); overflow: auto; }
  .item {
    display: flex; align-items: center; gap: 10px; width: 100%; height: 36px; padding: 0 12px;
    border: 0; border-radius: var(--r-ctl); background: none; text-align: left; color: inherit; cursor: pointer;
    transition: background-color 150ms var(--ease);
  }
  .item:hover { background: var(--raised); }
  .item.on { background: var(--raised); box-shadow: inset 0 0 0 1px var(--line); }
  .what { flex: 1; }
  .kind { font-weight: 500; }
  .detail { padding: 16px 20px; display: flex; flex-direction: column; gap: 8px; min-height: 360px; max-height: calc(100vh - 200px); }
  .cmd { word-break: break-all; }
  .log { flex: 1; margin: 4px 0 0; padding: 12px; overflow: auto; white-space: pre-wrap; border-radius: var(--r-ctl); background: var(--raised); font: 12px/18px var(--mono); color: var(--text-2); }
</style>
