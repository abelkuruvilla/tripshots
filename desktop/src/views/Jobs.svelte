<script>
  import { app, api, openReel, pollJobs, seconds } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let open = $state(null);
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
</script>

<div class="page">
  <div class="page-head"><h1>Activity</h1><span class="muted">reels being made, rendered and learned (also those started from the command line or an AI agent)</span></div>
  <div class="split">
    <div class="list card">
      {#each app.jobs as j (j.id)}
        <button class="item" class:on={open === j.id} onclick={() => (open = j.id)}>
          <span class="badge {j.state === 'running' ? 'run' : j.state === 'done' ? 'ok' : 'err'}">{j.state}</span>
          <span class="ellipsis"><b>{j.kind}</b> {j.label || ""}</span>
          <span class="muted small">{seconds(j.elapsed_s)}</span>
        </button>
      {:else}
        <div class="empty">Nothing yet.</div>
      {/each}
    </div>
    <div class="card detail">
      {#if detail}
        <div class="row">
          <b>{detail.kind}</b><span class="muted ellipsis">{detail.label}</span><div style="flex:1"></div>
          {#if detail.state === "running"}<button class="btn small" onclick={() => cancel(detail.id)}><Icon name="x" size={13} /> Stop</button>{/if}
          {#if planOf(detail)}<button class="btn primary small" onclick={() => openReel(planOf(detail))}>Open the reel</button>{/if}
        </div>
        <div class="mono muted cmd selectable">{detail.command}</div>
        <pre class="log mono selectable">{(detail.log || []).join("\n")}{detail.error ? "\n\n" + detail.error : ""}</pre>
      {:else}
        <div class="empty">Pick a job to see its log.</div>
      {/if}
    </div>
  </div>
</div>

<style>
  .split { display: grid; grid-template-columns: 340px 1fr; gap: 16px; height: calc(100% - 60px); }
  .list { overflow: auto; padding: 6px; }
  .item { display: flex; align-items: center; gap: 8px; width: 100%; border: 0; background: none; padding: 8px; border-radius: 7px; cursor: pointer; text-align: left; color: inherit; }
  .item:hover { background: var(--sunken); }
  .item.on { background: var(--accent-soft); }
  .item .ellipsis { flex: 1; }
  .small { font-size: 12px; }
  .detail { padding: 14px; display: flex; flex-direction: column; gap: 8px; overflow: hidden; }
  .cmd { word-break: break-all; }
  .log { flex: 1; background: var(--sunken); border-radius: 8px; padding: 10px; overflow: auto; white-space: pre-wrap; margin: 0; }
</style>
