<script>
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-dialog";
  import { check } from "@tauri-apps/plugin-updater";
  import { relaunch } from "@tauri-apps/plugin-process";
  import { app, api, startEngine, refreshStatus, toast } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  const st = app.status || {};
  let footage = $state([...(st.footage_folders || [])]);
  let reelsFolder = $state(st.reels_folder || "");
  let music = $state([...(st.music_folders || [])]);
  let browser = $state(st.settings?.TRIPSHOTS_COOKIES_BROWSER || "");
  let gemini = $state("");
  let anthropic = $state("");
  let saving = $state(false);
  let engineUpdate = $state(null);
  let cli = $state(null);
  let claude = $state(null);

  async function pickInto(list) {
    const got = await open({ directory: true, multiple: true });
    for (const f of [got].flat().filter(Boolean)) if (!list.includes(f)) list.push(f);
  }
  async function pickReels() {
    const got = await open({ directory: true });
    if (got) reelsFolder = got;
  }
  async function save() {
    saving = true;
    try {
      const env = { TRIPSHOTS_COOKIES_BROWSER: browser };
      if (gemini) env.GEMINI_API_KEY = gemini;
      if (anthropic) env.ANTHROPIC_API_KEY = anthropic;
      app.status = await api("/api/settings", { footage_folders: footage, reels_folder: reelsFolder || null, music_folders: music, env });
      gemini = anthropic = "";
      toast("Settings saved", "ok");
    } catch (e) {
      toast(String(e.message || e), "error");
    } finally {
      saving = false;
    }
  }
  async function checkEngine() {
    try {
      engineUpdate = await invoke("engine_check_update");
    } catch (e) {
      toast(String(e), "error");
    }
  }
  async function updateEngine() {
    try {
      toast("Updating the engine…", "info");
      await invoke("engine_install");
      await startEngine(true);
      engineUpdate = null;
      toast("Engine updated", "ok");
    } catch (e) {
      toast(String(e), "error");
    }
  }
  async function updateApp() {
    try {
      const u = await check();
      if (!u) return toast("TripShots is up to date", "ok");
      toast(`Downloading TripShots ${u.version}…`, "info");
      await u.downloadAndInstall();
      await relaunch();
    } catch (e) {
      toast(String(e), "error");
    }
  }
  async function installCli() {
    try {
      cli = await invoke("install_cli");
    } catch (e) {
      toast(String(e), "error");
    }
  }
  async function connectClaude() {
    try {
      claude = await invoke("connect_claude");
    } catch (e) {
      toast(String(e), "error");
    }
  }
  const s = st.settings || {};
</script>

<div class="page">
  <div class="page-head"><h1>Settings</h1><div class="spacer"></div>
    <button class="btn primary" onclick={save} disabled={saving}>{#if saving}<span class="spin"></span>{/if} Save</button></div>

  <div class="cols">
    <section class="card pad">
      <h2>Folders</h2>
      <div class="field">
        <label>Footage <span class="hint">· where your photos and clips live (searched inside)</span></label>
        <div class="chips">
          {#each footage as f, i}<span class="chip" title={f}><span class="ellipsis">{f}</span><button onclick={() => footage.splice(i, 1)}><Icon name="x" size={12} /></button></span>{/each}
          <button class="btn small" onclick={() => pickInto(footage)}><Icon name="folder" size={13} /> Add</button>
        </div>
      </div>
      <div class="field">
        <label>Reels are saved to</label>
        <div class="row"><input type="text" bind:value={reelsFolder} /><button class="btn" onclick={pickReels}>Choose</button></div>
      </div>
      <div class="field">
        <label>Music folders</label>
        <div class="chips">
          {#each music as f, i}<span class="chip" title={f}><span class="ellipsis">{f}</span><button onclick={() => music.splice(i, 1)}><Icon name="x" size={12} /></button></span>{/each}
          <button class="btn small" onclick={() => pickInto(music)}><Icon name="folder" size={13} /> Add</button>
        </div>
      </div>
    </section>

    <section class="card pad">
      <h2>AI and Instagram</h2>
      <div class="field">
        <label>Instagram login from <span class="hint">· to download reels you learn from or use the sound of</span></label>
        <select bind:value={browser}>
          <option value="">Not set</option>
          {#each ["auto", "chrome", "safari", "brave", "arc", "firefox", "edge"] as b}<option value={b}>{b}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Gemini API key <span class="hint">· {s.GEMINI_API_KEY ? "set" : "not set"}: lets TripShots watch clips and hear dialogue</span></label>
        <input type="password" placeholder={s.GEMINI_API_KEY ? "•••••••• (leave empty to keep)" : "optional"} bind:value={gemini} />
      </div>
      <div class="field">
        <label>Anthropic API key <span class="hint">· {s.ANTHROPIC_API_KEY ? "set" : "not set"}: for when the Claude app isn't signed in</span></label>
        <input type="password" placeholder={s.ANTHROPIC_API_KEY ? "•••••••• (leave empty to keep)" : "optional"} bind:value={anthropic} />
      </div>
      {#if !app.status?.ffmpeg}<p class="warn">ffmpeg wasn't found. {app.engineState?.platform?.startsWith("darwin") ? "Install it with Homebrew: brew install ffmpeg" : "Reinstall the engine."}</p>{/if}
    </section>

    <section class="card pad">
      <h2>Use TripShots elsewhere</h2>
      <div class="opt">
        <div><b>Command line</b><div class="muted small">the <span class="mono">tripshots</span> command in a terminal: the same engine and library as this app</div></div>
        <button class="btn" onclick={installCli}><Icon name="terminal" size={14} /> Install</button>
      </div>
      {#if cli}<p class="small selectable">Installed at <span class="mono">{cli.path}</span>{cli.note ? ` · ${cli.note}` : ""}</p>{/if}
      <div class="opt">
        <div><b>Claude (MCP)</b><div class="muted small">let Claude find footage and make reels for you</div></div>
        <button class="btn" onclick={connectClaude}><Icon name="link" size={14} /> Connect</button>
      </div>
      {#if claude}
        <p class="small selectable">Added to Claude Desktop (<span class="mono">{claude.desktop_config}</span>): restart Claude to use it.
          For Claude Code, run:<br /><span class="mono">{claude.claude_code_command}</span></p>
      {/if}
    </section>

    <section class="card pad">
      <h2>About</h2>
      <table class="small">
        <tbody>
          <tr><td class="muted">App</td><td>{app.engineState?.app_version}</td><td><button class="btn small" onclick={updateApp}>Check for updates</button></td></tr>
          <tr><td class="muted">Engine</td><td>{app.engine?.version} <span class="muted">({app.engine?.source})</span></td>
            <td>{#if engineUpdate?.available}<button class="btn small primary" onclick={updateEngine}>Update to {engineUpdate.latest}</button>
              {:else}<button class="btn small" onclick={checkEngine}>{engineUpdate ? "Up to date" : "Check"}</button>{/if}</td></tr>
          <tr><td class="muted">Engine file</td><td colspan="2" class="mono selectable ellipsis" title={app.engine?.path}>{app.engine?.path}</td></tr>
          <tr><td class="muted">Library</td><td colspan="2" class="mono selectable">{app.status?.home}</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</div>

<style>
  .cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; align-items: start; }
  .pad { padding: 18px 20px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .chip { max-width: 100%; }
  .small { font-size: 12.5px; }
  .warn { color: var(--warn); font-size: 13px; }
  .opt { display: flex; align-items: center; gap: 12px; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid var(--line); }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 6px 4px; vertical-align: middle; }
  td:last-child { text-align: right; }
</style>
