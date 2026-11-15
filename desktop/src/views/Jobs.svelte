<script>
  // Activity: everything being made, rendered or learned, from this app, the command line or an AI agent. The list
  // says each job's state in words; the selected one shows its steps, what it's doing now and its full log.
  import { app, api, openReel, pollJobs, clock, ago } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";
  import JobState from "../lib/JobState.svelte";
  import Steps from "../lib/Steps.svelte";
  import { steps, kindName } from "../lib/steps.js";

  let open = $state(app.jobs[0]?.id || null);
  let detail = $state(null);

  $effect(() => {
    if (!open) return;
    let alive = true;
    const tick = async () => {
      const d = await api(`/api/jobs/${open}?lines=300`).catch(() => null);
      if (!alive) return;
      if (d) detail = d;
      if (d?.state === "running") setTimeout(tick, 1200);
    };
    tick();
    return () => (alive = false);
  });

  async function cancel(id) {
    await api(`/api/jobs/${id}/cancel`, {});
    pollJobs();
  }
  const planOf = (d) => d?.result?.plan || d?.result?.variants?.[0]?.plan;
  let info = $derived(detail ? steps(detail.kind, detail.log, detail.result?.question ? "running" : detail.state) : null);
  let now = $derived((detail?.log || []).filter((l) => l.trim()).at(-1) || "");
  // arrow keys move through the list
  function listKeys(e) {
    const i = app.jobs.findIndex((j) => j.id === open);
    const j = e.key === "ArrowDown" ? i + 1 : e.key === "ArrowUp" ? i - 1 : null;
    if (j === null || !app.jobs[j]) return;
    e.preventDefault();
    open = app.jobs[j].id;
    e.currentTarget.querySelectorAll(".item")[j]?.focus();
  }
</script>

<div class="page">
  <div class="page-head"><h1>Activity</h1><span class="meta">{app.jobs.length}</span></div>
  <p class="page-sub">Reels being made, rendered and learned, from this app, the command line or an AI agent</p>

  {#if !app.jobs.length}
    <div class="empty">
      <h2>Nothing has run yet</h2>
      <p>Making a reel, rendering or learning a style shows up here with its progress</p>
      <button class="btn primary" onclick={() => (app.view = "make")}>Make a reel</button>
    </div>
  {:else}
    <div class="split">
      <!-- svelte-ignore a11y_interactive_supports_focus -->
      <div class="list surface" role="listbox" aria-label="Jobs" onkeydown={listKeys}>
        {#each app.jobs as j (j.id)}
          <button class="item" class:on={open === j.id} role="option" aria-selected={open === j.id} tabindex={open === j.id ? 0 : -1}
                  onclick={() => (open = j.id)}>
            <span class="top">
              <span class="kind">{kindName[j.kind] || j.kind}</span>
              <span class="meta">{j.state === "running" ? clock(j.elapsed_s) : j.started ? ago(j.started) : clock(j.elapsed_s)}</span>
            </span>
            <span class="bottom">
              <span class="label ellipsis">{j.label || ""}</span>
              <JobState state={j.state} />
            </span>
          </button>
        {/each}
      </div>

      <div class="detail surface">
        {#if detail}
          <div class="row head">
            <h2 class="ellipsis">{kindName[detail.kind] || detail.kind}<span class="muted">&nbsp;·&nbsp;{detail.label}</span></h2>
            <div class="spacer"></div>
            <JobState state={detail.state} question={!!detail.result?.question} />
            <span class="meta">{clock(detail.elapsed_s)}</span>
            {#if detail.state === "running"}<button class="btn sm" onclick={() => cancel(detail.id)}><Icon name="x" size={14} /> Stop</button>{/if}
            {#if planOf(detail)}<button class="btn primary sm" onclick={() => openReel(planOf(detail))}><Icon name="play" size={14} /> Open the reel</button>{/if}
          </div>

          {#if info}<div class="steps"><Steps {info} /></div>{/if}
          {#if detail.result?.question}<p class="notice">{detail.result.question} <button class="btn sm" onclick={() => (app.view = "make")}>Answer in Make</button></p>{/if}
          {#if detail.state === "failed"}<p class="err-text selectable">{detail.error || now}</p>
          {:else if detail.state === "running" && now}<p class="muted ellipsis" title={now}>{now}</p>{/if}

          <details open={!info}>
            <summary class="small">Log · <span class="tc">{detail.command}</span></summary>
            <pre class="log">{(detail.log || []).join("\n")}{detail.error ? "\n\n" + detail.error : ""}</pre>
          </details>
        {:else}
          <div class="empty">Select a job to see its progress</div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .split { display: grid; grid-template-columns: 320px 1fr; gap: 16px; align-items: start; }
  .list { padding: 4px; max-height: calc(100vh - 220px); overflow: auto; display: flex; flex-direction: column; gap: 2px; }
  .item {
    display: flex; flex-direction: column; gap: 2px; width: 100%; padding: 8px 12px;
    border: 0; border-radius: var(--r-ctl); background: none; text-align: left; color: inherit;
    transition: background-color var(--fast) var(--ease);
  }
  .item:hover { background: var(--raised); }
  .item.on { background: var(--raised); box-shadow: inset 0 0 0 1px var(--line), var(--highlight); }
  .top, .bottom { display: flex; align-items: center; gap: 12px; justify-content: space-between; min-width: 0; }
  .kind { font-weight: 500; }
  .label { color: var(--text-2); font-size: 13px; min-width: 0; }
  .detail { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; min-height: 360px; max-height: calc(100vh - 220px); overflow: auto; }
  .head { gap: 12px; }
  .head h2 { min-width: 0; }
  .steps { padding: 4px 0; }
  details summary { color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  details .log { margin-top: 8px; max-height: 420px; }
</style>
