<script>
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";
  import { app } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let { onready } = $props();
  let busy = $state(false);
  let error = $state(app.engineState?.error || "");
  let progress = $state(null);
  let latest = $state(null);

  const stages = { checking: "Checking for the latest engine", downloading: "Downloading", verifying: "Verifying the signature", unpacking: "Unpacking", done: "Starting" };
  const mb = (b) => (b / 1e6).toFixed(0);

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
      else error = st.error || "the engine was installed but didn't start";
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="page setup">
  <div class="card box">
    <img src="/icon.png" alt="" width="64" height="64" />
    <h1>Welcome to TripShots</h1>
    <p class="muted">
      TripShots needs its engine: the part that analyses your footage and renders reels. It is downloaded once
      {#if latest}(version {latest.latest}){/if} and updates on its own afterwards. Your footage never leaves this computer.
    </p>

    {#if busy && progress}
      <div class="prog">
        <div class="bar"><div style="width: {progress.total ? (100 * progress.done) / progress.total : 15}%"></div></div>
        <div class="muted small">
          {stages[progress.stage] || progress.stage}
          {#if progress.stage === "downloading" && progress.total}: {mb(progress.done)} of {mb(progress.total)} MB{/if}
        </div>
      </div>
    {:else}
      <button class="btn primary big" onclick={install} disabled={busy}>
        {#if busy}<span class="spin"></span>{:else}<Icon name="download" />{/if} Download the engine
      </button>
    {/if}

    {#if error}<p class="err selectable">{error}</p>{/if}

    <details class="dev">
      <summary class="muted">Already have TripShots installed with pip?</summary>
      <p class="muted">
        The app uses a <span class="mono">tripshots</span> on your PATH when no engine is installed here, or the one
        named by <span class="mono">TRIPSHOTS_ENGINE</span>. It needs a version with <span class="mono">tripshots serve</span>.
      </p>
      <button class="btn small" onclick={onready}><Icon name="refresh" size={14} /> Try again</button>
    </details>
  </div>
</div>

<style>
  .setup { display: grid; place-items: center; }
  .box { max-width: 520px; padding: 36px 40px; text-align: center; }
  .box img { border-radius: 14px; margin-bottom: 10px; }
  .box p { margin: 12px 0 22px; }
  .big { padding: 11px 20px; font-size: 15px; }
  .prog { margin: 8px 0 4px; }
  .bar { height: 8px; background: var(--sunken); border-radius: 99px; overflow: hidden; }
  .bar div { height: 100%; background: var(--accent); transition: width 0.3s; }
  .small { font-size: 12.5px; margin-top: 8px; }
  .err { color: var(--err); font-size: 13px; }
  .dev { margin-top: 26px; text-align: left; font-size: 13px; }
  .dev summary { cursor: pointer; }
</style>
