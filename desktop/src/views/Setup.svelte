<script>
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";
  import { app } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";
  import Mark from "../lib/Mark.svelte";

  let { onready } = $props();
  let busy = $state(false);
  let error = $state(app.engineState?.error || "");
  let progress = $state(null);
  let latest = $state(null);

  const stages = { checking: "Finding the latest engine", downloading: "Downloading", verifying: "Checking the signature", unpacking: "Unpacking", done: "Starting" };
  const mb = (b) => Math.round(b / 1e6);

  onMount(() => {
    invoke("engine_check_update").then((u) => (latest = u)).catch(() => {});
    const un = listen("engine-progress", (e) => (progress = e.payload));
    return () => un.then((f) => f());
  });

  async function install() {
    busy = true;
    error = "";
    try {
      const st = await invoke("engine_install");
      if (st.status === "ready") onready();
      else error = st.error || "The engine was installed but didn't start";
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="page center">
  <div class="box">
    <Mark size={40} />
    <h1>Install the TripShots engine</h1>
    <p class="muted">
      The engine is the part that reads your footage and renders reels. It downloads once{#if latest}, version <span class="tc">{latest.latest}</span>,{/if}
      about 200 MB, and keeps itself up to date. Your footage stays on this computer
    </p>

    {#if busy && progress}
      <div class="prog" role="progressbar" aria-valuenow={progress.done} aria-valuemax={progress.total || 1}>
        <div class="bar"><div style="transform: scaleX({progress.total ? progress.done / progress.total : 0.08})"></div></div>
        <div class="meta">
          {[stages[progress.stage] || progress.stage, progress.stage === "downloading" && progress.total ? `${mb(progress.done)} of ${mb(progress.total)} MB` : ""].filter(Boolean).join(" · ")}
        </div>
      </div>
    {:else}
      <button class="btn primary lg" onclick={install} disabled={busy}>
        {#if busy}<span class="spin"></span>{:else}<Icon name="download" />{/if} Download the engine
      </button>
    {/if}

    {#if error}<p class="err selectable">{error}</p>{/if}

    <details>
      <summary>Already installed TripShots with pip</summary>
      <p class="muted">
        The app uses a <span class="tc">tripshots</span> on your PATH when no engine is installed here, or the one named by
        <span class="tc">TRIPSHOTS_ENGINE</span>. It needs a version that has <span class="tc">tripshots serve</span>
      </p>
      <button class="btn sm" onclick={onready}><Icon name="refresh" size={14} /> Look again</button>
    </details>
  </div>
</div>

<style>
  .center { display: grid; place-items: center; }
  .box { max-width: 480px; display: flex; flex-direction: column; align-items: flex-start; gap: 16px; }
  .box p { margin: 0; }
  .prog { width: 100%; display: flex; flex-direction: column; gap: 8px; }
  .bar { height: 4px; background: var(--raised); border-radius: 2px; overflow: hidden; }
  .bar div { height: 100%; background: var(--accent); transform-origin: left; transition: transform 300ms var(--ease); }
  .err { color: var(--err); font-size: 13px; }
  details { margin-top: 24px; font-size: 13px; display: flex; flex-direction: column; gap: 8px; color: var(--text-2); }
  details[open] { gap: 12px; }
  summary { cursor: pointer; }
  details p { margin: 12px 0; }
</style>
