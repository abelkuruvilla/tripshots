<script>
  import { onMount } from "svelte";
  import { app, startEngine, refreshReels, watchJobs } from "./lib/store.svelte.js";
  import Icon from "./lib/Icon.svelte";
  import Setup from "./views/Setup.svelte";
  import Reels from "./views/Reels.svelte";
  import Reel from "./views/Reel.svelte";
  import Make from "./views/Make.svelte";
  import Ask from "./views/Ask.svelte";
  import Styles from "./views/Styles.svelte";
  import Jobs from "./views/Jobs.svelte";
  import Settings from "./views/Settings.svelte";

  let booting = $state(true);
  const nav = [
    { id: "reels", label: "Reels", icon: "film" },
    { id: "make", label: "New reel", icon: "plus" },
    { id: "ask", label: "Ask", icon: "spark" },
    { id: "styles", label: "Styles", icon: "palette" },
    { id: "jobs", label: "Activity", icon: "pulse" },
    { id: "settings", label: "Settings", icon: "gear" },
  ];
  let running = $derived(app.jobs.filter((j) => j.state === "running").length);

  async function boot() {
    booting = true;
    try {
      const st = await startEngine();
      if (st.status === "ready") {
        await refreshReels();
        watchJobs();
      }
    } finally {
      booting = false;
    }
  }
  onMount(boot);
</script>

<div class="shell">
  <aside class="side" data-tauri-drag-region>
    <div class="brand" data-tauri-drag-region>
      <img src="/icon.png" alt="" width="26" height="26" />
      <span>TripShots</span>
    </div>
    {#if app.engine}
      {#each nav as n}
        <button class="nav" class:on={app.view === n.id || (n.id === "reels" && app.view === "reel")}
                onclick={() => (app.view = n.id)}>
          <Icon name={n.icon} />
          <span>{n.label}</span>
          {#if n.id === "jobs" && running}<span class="count">{running}</span>{/if}
        </button>
      {/each}
    {/if}
    <div class="side-foot muted">
      {#if app.engine}engine {app.engine.version}{:else if booting}starting…{/if}
    </div>
  </aside>

  <main class="main">
    <div class="drag" data-tauri-drag-region></div>
    {#if booting}
      <div class="empty"><span class="spin"></span>&nbsp; Starting TripShots…</div>
    {:else if !app.engine}
      <Setup onready={boot} />
    {:else if app.view === "reels"}
      <Reels />
    {:else if app.view === "reel"}
      <Reel />
    {:else if app.view === "make"}
      <Make />
    {:else if app.view === "ask"}
      <Ask />
    {:else if app.view === "styles"}
      <Styles />
    {:else if app.view === "jobs"}
      <Jobs />
    {:else if app.view === "settings"}
      <Settings />
    {/if}
  </main>

  <div class="toasts">
    {#each app.toasts as t (t.id)}
      <div class="toast card {t.kind}">
        <span>{t.text}</span>
        {#if t.action}<button class="btn small" onclick={t.action.run}>{t.action.label}</button>{/if}
      </div>
    {/each}
  </div>
</div>

<style>
  .shell { display: grid; grid-template-columns: 208px 1fr; height: 100%; }
  .side {
    background: var(--sunken); border-right: 1px solid var(--line);
    padding: 38px 10px 12px; display: flex; flex-direction: column; gap: 2px;
  }
  .brand { display: flex; align-items: center; gap: 9px; font-weight: 700; font-size: 15px; padding: 4px 10px 16px; }
  .brand img { border-radius: 7px; }
  .nav {
    display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
    border: 0; background: transparent; padding: 8px 10px; border-radius: 8px; cursor: pointer; color: var(--text);
  }
  .nav:hover { background: color-mix(in srgb, var(--text) 6%, transparent); }
  .nav.on { background: var(--panel); box-shadow: var(--shadow); font-weight: 600; }
  .count { margin-left: auto; background: var(--accent); color: var(--accent-ink); font-size: 11px; border-radius: 999px; padding: 0 7px; }
  .side-foot { margin-top: auto; font-size: 11.5px; padding: 0 10px; }
  .main { position: relative; overflow: hidden; }
  .drag { position: absolute; top: 0; left: 0; right: 0; height: 22px; z-index: 5; }
  .toasts { position: fixed; right: 18px; bottom: 18px; display: flex; flex-direction: column; gap: 8px; z-index: 50; }
  .toast { padding: 10px 14px; display: flex; align-items: center; gap: 12px; max-width: 420px; animation: up 0.18s ease-out; }
  .toast.ok { border-left: 3px solid var(--ok); }
  .toast.error { border-left: 3px solid var(--err); }
  .toast.info { border-left: 3px solid var(--accent); }
  @keyframes up { from { transform: translateY(8px); opacity: 0; } }
</style>
