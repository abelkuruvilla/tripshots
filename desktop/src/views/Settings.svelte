<script>
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-dialog";
  import { check } from "@tauri-apps/plugin-updater";
  import { relaunch } from "@tauri-apps/plugin-process";
  import { app, api, startEngine, startJob, toast } from "../lib/store.svelte.js";
  import { theme, applyTheme } from "../lib/theme.svelte.js";
  import Icon from "../lib/Icon.svelte";
  import AiSetup from "./AiSetup.svelte";
  import { onMount } from "svelte";

  const st = app.status || {};
  const s = st.settings || {};
  let footage = $state([...(st.footage_folders || [])]);
  let reelsFolder = $state(st.reels_folder || "");
  let music = $state([...(st.music_folders || [])]);
  let browser = $state(s.TRIPSHOTS_COOKIES_BROWSER || "");
  // opened from the "set up an AI" notice: go straight to that section
  onMount(() => {
    if (app.focus === "ai") document.getElementById("ai")?.scrollIntoView({ block: "start" });
    app.focus = null;
  });
  let saving = $state(false);
  let saved = $state(false);
  // changes save on their own, a moment after the last one
  let first = true;
  $effect(() => {
    const snapshot = JSON.stringify([footage, reelsFolder, music, browser]);
    if (first) {
      first = false;
      return;
    }
    saved = false;
    const id = setTimeout(() => save(snapshot), 600);
    return () => clearTimeout(id);
  });
  // the footage catalogue (tripshots analyze): new files only; "again" re-asks the AI about every shot
  let again = $state(false);
  let analysing = $derived(app.jobs.find((j) => j.kind === "analyze" && j.state === "running"));
  let lastAnalysis = $derived(app.jobs.find((j) => j.kind === "analyze" && j.state !== "running"));
  const analyse = run(async () => {
    if (!footage.length) return toast("Add a footage folder first", "error");
    await startJob("analyze", { sources: footage, rescore: again }, again ? "Analyse all footage again" : "Analyse new footage");
  });
  const sections = [["ai", "AI"], ["folders", "Folders"], ["analysis", "Footage analysis"], ["appearance", "Appearance"], ["instagram", "Instagram"],
                    ["outside", "Outside the app"], ["about", "About"]];
  const go = (id) => document.getElementById(id)?.scrollIntoView({ block: "start", behavior: "smooth" });
  let engineUpdate = $state(null);
  let cli = $state(null);
  let claude = $state(null);
  const themes = [
    { id: "system", icon: "monitor", label: "System" },
    { id: "light", icon: "sun", label: "Light" },
    { id: "dark", icon: "moon", label: "Dark" },
  ];

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
      app.status = await api("/api/settings", { footage_folders: footage, reels_folder: reelsFolder || null, music_folders: music, env });
      saved = true;
    } catch (e) {
      toast(String(e.message || e), "error");
    } finally {
      saving = false;
    }
  }
  const run = (f) => async () => {
    try {
      await f();
    } catch (e) {
      toast(String(e.message || e), "error");
    }
  };
  const checkEngine = run(async () => (engineUpdate = await invoke("engine_check_update")));
  const updateEngine = run(async () => {
    toast("Updating the engine", "info");
    await invoke("engine_install");
    await startEngine(true);
    engineUpdate = null;
    toast("Engine updated", "ok");
  });
  const updateApp = run(async () => {
    const u = await check();
    if (!u) return toast("TripShots is up to date", "ok");
    toast(`Downloading TripShots ${u.version}`, "info");
    await u.downloadAndInstall();
    await relaunch();
  });
  const installCli = run(async () => (cli = await invoke("install_cli")));
  const connectClaude = run(async () => (claude = await invoke("connect_claude")));
</script>

<div class="page">
  <div class="page-head"><h1>Settings</h1><div class="spacer"></div>
    <span class="state" aria-live="polite">{#if saving}<span class="spin" style="width: 10px; height: 10px; border-width: 1.5px"></span> Saving{:else if saved}<span class="dot ok"></span> Saved{/if}</span></div>

  <div class="layout">
  <nav class="index" aria-label="Settings sections">
    {#each sections as [id, label]}<button onclick={() => go(id)}>{label}</button>{/each}
  </nav>
  <div class="content">
  <div class="ai" id="ai-anchor"><AiSetup /></div>

  <div class="cols">
    <div class="col">
      <section class="surface block" id="folders">
        <h2>Folders</h2>
        <div class="field">
          <label for="ft">Footage <span class="hint">· where your photos and clips live</span></label>
          <div class="chips" id="ft">
            {#each footage as f, i}<span class="chip" title={f}><span class="ellipsis">{f}</span><button onclick={() => footage.splice(i, 1)} aria-label="Remove"><Icon name="x" size={14} /></button></span>{/each}
            <button class="btn sm" onclick={() => pickInto(footage)}><Icon name="folder" size={14} /> Add</button>
          </div>
        </div>
        <div class="field">
          <label for="rf">Reels are saved to</label>
          <div class="row"><input id="rf" type="text" bind:value={reelsFolder} /><button class="btn" onclick={pickReels}>Choose</button></div>
        </div>
        <div class="field last">
          <label for="mf">Music</label>
          <div class="chips" id="mf">
            {#each music as f, i}<span class="chip" title={f}><span class="ellipsis">{f}</span><button onclick={() => music.splice(i, 1)} aria-label="Remove"><Icon name="x" size={14} /></button></span>{/each}
            <button class="btn sm" onclick={() => pickInto(music)}><Icon name="folder" size={14} /> Add</button>
          </div>
        </div>
      </section>

      <section class="surface block" id="analysis">
        <h2>Footage analysis</h2>
        <p class="muted small">TripShots looks at every photo and clip once: sharpness, light, faces, where it was taken, and
          what the AI sees in it. That is what finding footage and picking shots use. Reels analyse their own footage as they
          go; this catalogues everything in your footage folders ahead of time, so searches and new reels start faster.</p>
        <p class="quiet small">Already-analysed files are skipped, so running it again only does the new ones.</p>
        <label class="check"><input type="checkbox" bind:checked={again} /> Ask the AI again about every shot
          <span class="hint">· slow; only after a big change to how shots are described</span></label>
        <div class="row">
          <button class="btn" onclick={analyse} disabled={!!analysing}>
            {#if analysing}<span class="spin" style="width: 10px; height: 10px; border-width: 1.5px"></span> Analysing{:else}<Icon name="sparkle" size={14} /> {again ? "Analyse everything again" : "Analyse new footage"}{/if}</button>
          {#if analysing}<button class="btn ghost sm" onclick={() => (app.view = "jobs")}>See the progress</button>{/if}
        </div>
        {#if lastAnalysis && !analysing}<p class="quiet small">Last run: {lastAnalysis.state === "done" ? "finished" : lastAnalysis.state}</p>{/if}
      </section>

      <section class="surface block" id="appearance">
        <h2>Appearance</h2>
        <div class="themes" role="radiogroup" aria-label="Appearance">
          {#each themes as t}
            <button role="radio" aria-checked={theme.choice === t.id} class:on={theme.choice === t.id} onclick={() => applyTheme(t.id)}>
              <Icon name={t.icon} /> {t.label}
            </button>
          {/each}
        </div>
        <p class="quiet small">System follows your computer's light and dark setting</p>
      </section>
    </div>

    <div class="col">
      <section class="surface block" id="instagram">
        <h2>Instagram</h2>
        <div class="field last">
          <label for="ig">Borrow the login from <span class="hint">· to download reels you learn from or take the sound of</span></label>
          <select id="ig" bind:value={browser}>
            <option value="">Not set</option>
            {#each ["auto", "chrome", "safari", "brave", "arc", "firefox", "edge"] as b}<option value={b}>{b === "auto" ? "Any browser that's signed in" : b[0].toUpperCase() + b.slice(1)}</option>{/each}
          </select>
        </div>
        {#if !app.status?.ffmpeg}<p class="warn">ffmpeg isn't installed. {app.engineState?.platform?.startsWith("darwin") ? "Install it with Homebrew: brew install ffmpeg" : "Install the engine again"}</p>{/if}
      </section>

      <section class="surface block" id="outside">
        <h2>Outside the app</h2>
        <div class="opt">
          <div><div class="t">Command line</div><div class="quiet small">The <span class="tc">tripshots</span> command, with the same engine and library</div></div>
          <button class="btn" onclick={installCli}><Icon name="terminal" /> Install</button>
        </div>
        {#if cli}<p class="small selectable">Installed at <span class="tc">{cli.path}</span>{cli.note ? `. ${cli.note}` : ""}</p>{/if}
        <div class="opt">
          <div><div class="t">Claude</div><div class="quiet small">Let Claude find footage and make reels for you, over MCP</div></div>
          <button class="btn" onclick={connectClaude}><Icon name="link" /> Connect</button>
        </div>
        {#if claude}
          <p class="small selectable">Added to Claude Desktop. Restart Claude to use it. For Claude Code run<br /><span class="tc">{claude.claude_code_command}</span></p>
        {/if}
      </section>

      <section class="surface block" id="about">
        <h2>About</h2>
        <dl>
          <dt>App</dt><dd class="tc">{app.engineState?.app_version}</dd>
          <dd class="act"><button class="btn sm" onclick={updateApp}>Check for updates</button></dd>
          <dt>Engine</dt><dd><span class="tc">{app.engine?.version}</span> <span class="quiet">{app.engine?.source === "installed" ? "" : `· ${app.engine?.source}`}</span></dd>
          <dd class="act">{#if engineUpdate?.available}<button class="btn sm primary" onclick={updateEngine}>Update to {engineUpdate.latest}</button>
            {:else}<button class="btn sm" onclick={checkEngine}>{engineUpdate ? "Up to date" : "Check"}</button>{/if}</dd>
          <dt>Library</dt><dd class="tc selectable ellipsis wide" title={app.status?.home}>{app.status?.home}</dd>
        </dl>
      </section>
    </div>
  </div>
</div>
  </div>
  </div>

<style>
  .layout { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 32px; align-items: start; }
  .index { position: sticky; top: 0; display: flex; flex-direction: column; gap: 2px; }
  .index button {
    height: 32px; padding: 0 8px; border: 0; border-radius: var(--r-ctl); background: none; text-align: left; color: var(--text-2);
    font-size: 13px; transition: background-color var(--fast) var(--ease), color var(--fast) var(--ease);
  }
  .index button:hover { background: var(--raised); color: var(--text); }
  .content { min-width: 0; max-width: 1040px; }
  .ai { margin-bottom: 16px; }
  .cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; align-items: start; }
  .col { display: flex; flex-direction: column; gap: 16px; }
  .block { padding: 20px 24px; display: flex; flex-direction: column; }
  .block h2 { margin-bottom: 16px; }
  .field.last { margin-bottom: 0; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .small { font-size: 13px; margin: 8px 0 0; }
  .warn { color: var(--err); font-size: 13px; margin: 16px 0 0; }
  .themes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; padding: 4px; background: var(--raised); border-radius: 12px; }
  .themes button {
    display: flex; align-items: center; justify-content: center; gap: 8px; height: 36px; border: 0; border-radius: var(--r-ctl);
    background: transparent; color: var(--text-2); cursor: pointer; font-weight: 500;
    transition: background-color 150ms var(--ease), color 150ms var(--ease);
  }
  .themes button:hover { color: var(--text); }
  .themes button.on { background: var(--card); color: var(--text); box-shadow: inset 0 0 0 1px var(--line), var(--highlight); }
  .opt { display: flex; align-items: center; gap: 16px; justify-content: space-between; padding: 12px 0; border-top: 1px solid var(--line); }
  .opt:first-of-type { border-top: 0; padding-top: 0; }
  .opt .t { font-weight: 500; }
  dl { display: grid; grid-template-columns: 72px 1fr auto; gap: 12px 12px; align-items: center; margin: 0; }
  dt { color: var(--text-3); font-size: 13px; }
  dd { margin: 0; min-width: 0; }
  dd.act { justify-self: end; }
  dd.wide { grid-column: span 2; font-size: 12px; }
</style>
