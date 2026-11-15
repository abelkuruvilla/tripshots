<script>
  import { onMount } from "svelte";
  import { app, startEngine, refreshReels, refreshAi, watchJobs } from "./lib/store.svelte.js";
  import { theme, applyTheme } from "./lib/theme.svelte.js";
  import Icon from "./lib/Icon.svelte";
  import Mark from "./lib/Mark.svelte";
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
    { id: "ask", label: "Ask", icon: "message" },
    { id: "styles", label: "Styles", icon: "layers" },
    { id: "jobs", label: "Activity", icon: "activity" },
  ];
  const themes = [
    { id: "system", icon: "monitor", label: "Match the system" },
    { id: "light", icon: "sun", label: "Light" },
    { id: "dark", icon: "moon", label: "Dark" },
  ];
  let running = $derived(app.jobs.filter((j) => j.state === "running").length);
  const on = (id) => app.view === id || (id === "reels" && app.view === "reel");

  async function boot() {
    booting = true;
    try {
      const st = await startEngine();
      if (st.status === "ready") {
        await refreshReels();
        watchJobs();
        refreshAi();
      }
    } finally {
      booting = false;
    }
  }
  onMount(() => {
    applyTheme();
    boot();
  });
</script>

<!-- the title bar: the window is moved by dragging the top of it, and zoomed by double-clicking it (macOS draws
     its own buttons over the top left). A drag region works on its own element only, so it's one empty strip -->
<div class="titlebar" data-tauri-drag-region></div>

<div class="shell">
  <aside class="side">
    <div class="brand">
      <Mark size={24} />
      <span>TripShots</span>
    </div>

    {#if app.engine}
      <nav>
        {#each nav as n}
          <button class="nav" class:on={on(n.id)} onclick={() => (app.view = n.id)}>
            <Icon name={n.icon} />
            <span>{n.label}</span>
            {#if n.id === "jobs" && running}<span class="count tc">{running}</span>{/if}
          </button>
        {/each}
      </nav>
      <nav class="lower">
        <button class="nav" class:on={on("settings")} onclick={() => (app.view = "settings")}>
          <Icon name="settings" /><span>Settings</span>
        </button>
      </nav>
    {/if}

    <div class="foot">
      <div class="seg" role="radiogroup" aria-label="Appearance">
        {#each themes as t}
          <button role="radio" aria-checked={theme.choice === t.id} class:on={theme.choice === t.id}
                  title={t.label} aria-label={t.label} onclick={() => applyTheme(t.id)}>
            <Icon name={t.icon} size={14} />
          </button>
        {/each}
      </div>
      <span class="meta">{#if app.engine}engine {app.engine.version}{:else if booting}starting{/if}</span>
    </div>
  </aside>

  <main class="main">
    {#if booting}
      <div class="empty"><span class="spin"></span></div>
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

  <div class="toasts" aria-live="polite">
    {#each app.toasts as t (t.id)}
      <div class="toast">
        <span class="dot {t.kind === 'error' ? 'err' : t.kind === 'ok' ? 'ok' : 'run'}"></span>
        <span>{t.text}</span>
        {#if t.action}<button class="btn sm" onclick={t.action.run}>{t.action.label}</button>{/if}
      </div>
    {/each}
  </div>
</div>

<style>
  .shell { display: grid; grid-template-columns: 248px 1fr; height: 100%; }
  .side {
    background: var(--deep); border-right: 1px solid var(--line);
    padding: 40px 12px 16px; display: flex; flex-direction: column;
  }
  .brand { display: flex; align-items: center; gap: 8px; height: 32px; padding: 0 8px; margin-bottom: 24px; font-size: 16px; font-weight: 600; }
  nav { display: flex; flex-direction: column; gap: 2px; }
  nav.lower { margin-top: 24px; }
  .nav {
    display: flex; align-items: center; gap: 10px; height: 36px; padding: 0 8px; width: 100%;
    border: 0; border-radius: var(--r-ctl); background: transparent; color: var(--text-2);
    text-align: left; cursor: pointer; font-size: 14px;
    transition: background-color 150ms var(--ease), color 150ms var(--ease);
  }
  .nav:hover { background: var(--raised); color: var(--text); }
  .nav.on { background: var(--card); color: var(--text); font-weight: 500; box-shadow: inset 0 0 0 1px var(--line), var(--highlight); }
  .count { margin-left: auto; font-size: 12px; color: var(--accent); }
  .foot { margin-top: auto; display: flex; align-items: center; justify-content: space-between; padding: 0 8px; }
  .seg { display: inline-flex; padding: 2px; gap: 2px; background: var(--raised); border-radius: var(--r-ctl); }
  .seg button {
    width: 28px; height: 24px; border: 0; border-radius: var(--r-sm); background: transparent;
    color: var(--text-3); cursor: pointer; display: grid; place-items: center;
    transition: background-color 150ms var(--ease), color 150ms var(--ease);
  }
  .seg button:hover { color: var(--text); }
  .seg button.on { background: var(--card); color: var(--text); box-shadow: inset 0 0 0 1px var(--line); }
  .main { position: relative; overflow: hidden; }
  .titlebar { position: fixed; top: 0; left: 0; right: 0; height: 36px; z-index: 60; }
  .toasts { position: fixed; right: 24px; bottom: 24px; display: flex; flex-direction: column; gap: 8px; z-index: 50; }
  .toast {
    display: flex; align-items: center; gap: 12px; max-width: 420px; padding: 12px 16px;
    background: var(--card); border: 1px solid var(--line); border-radius: var(--r-card); box-shadow: var(--float);
    animation: rise 300ms var(--ease);
  }
  @keyframes rise { from { transform: translateY(8px); opacity: 0; } }
</style>
