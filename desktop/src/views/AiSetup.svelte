<script>
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { app, api, toast, refreshStatus } from "../lib/store.svelte.js";
  import Icon from "../lib/Icon.svelte";

  let st = $state(null);
  let open = $state(null); // the provider whose steps are shown
  let keys = $state({}); // what's typed in each provider's key, model and address fields
  let testing = $state({});
  let results = $state({});
  let watching = $state(false);
  let error = $state("");

  const name = (id) => st?.providers?.[id]?.name || id;
  async function load() {
    try {
      st = await api("/api/ai");
      app.ai = st;
      error = "";
      if (open === null) open = st.using ? null : "claude-cli";
    } catch (e) {
      // an older engine has no AI page: say so instead of spinning
      error = /no such endpoint/.test(String(e.message || e))
        ? "This engine is older than the app. Update it in About below to set up AI here"
        : String(e.message || e);
    }
  }
  onMount(load);

  const P = (id) => st?.providers?.[id] || {};
  const label = (state) =>
    ({ ready: "Ready", logged_out: "Not logged in", missing: "Not installed", no_key: "No key", no_model: "Choose a model", no_sdk: "Needs the Gemini library" })[state] || state;
  // the AIs in the order automatic tries them; the ones in use are numbered
  let every = $derived(st?.every || []);
  let mode = $derived(!st ? "auto" : st.backend === "auto" || st.backend === "none" ? st.backend : "one");
  let ready = $derived(every.filter((id) => P(id).state === "ready"));

  async function setBackend(id) {
    await api("/api/settings", { backend: id });
    await load();
    await refreshStatus();
  }
  async function move(id, by) {
    const list = [...every];
    const i = list.indexOf(id);
    const j = i + by;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    st.every = list; // at once on screen; the engine confirms
    await api("/api/settings", { ai_order: list });
    await load();
  }
  async function toggle(id, on) {
    const off = every.filter((x) => (x === id ? !on : !P(x).on));
    await api("/api/settings", { ai_off: off });
    await load();
    toast(on ? `${name(id)} is used again` : `${name(id)} won't be used`, "ok");
  }
  async function saveEnv(envName, field, what = "Key") {
    const v = (keys[field] || "").trim();
    if (!v) return;
    await api("/api/settings", { env: { [envName]: v } });
    keys[field] = "";
    await load();
    toast(`${what} saved`, "ok");
  }
  async function removeEnv(envName, what = "Key") {
    await api("/api/settings", { env: { [envName]: "" } });
    await load();
    toast(`${what} removed`, "ok");
  }
  // (the Claude token's own field)
  const saveKey = (envName, field) => saveEnv(envName, field);
  const removeKey = (envName) => removeEnv(envName);
  async function test(id) {
    testing[id] = true;
    results[id] = null;
    try {
      results[id] = await api("/api/ai/test", { provider: id });
    } catch (e) {
      results[id] = { ok: false, message: String(e.message || e) };
    } finally {
      testing[id] = false;
    }
  }
  async function terminal(action) {
    try {
      const cmd = await invoke("open_terminal", { action });
      toast(`Terminal opened: ${cmd}`, "info");
      watchClaude();
    } catch (e) {
      toast(String(e), "error");
    }
  }
  // after the login or install runs in the terminal, notice when Claude becomes ready (up to 3 minutes)
  async function watchClaude() {
    if (watching) return;
    watching = true;
    const until = Date.now() + 180000;
    while (Date.now() < until) {
      await new Promise((r) => setTimeout(r, 3000));
      await load().catch(() => {});
      if (P("claude").state === "ready") {
        toast("Claude is connected", "ok");
        break;
      }
    }
    watching = false;
  }
  async function copy(text) {
    await navigator.clipboard.writeText(text);
    toast("Copied", "ok");
  }
  const tone = (state) => (state === "ready" ? "ok" : state === "logged_out" || state === "no_sdk" ? "run" : "");
</script>

{#snippet head(id)}
  {@const p = P(id)}
  {@const n = st.order.indexOf(id)}
  <div class="headrow" class:off={!p.on}>
    <span class="pos tc" title={n >= 0 ? `Tried ${n === 0 ? "first" : `${n + 1}th`}` : p.on ? "Not set up yet" : "Switched off"}>{n >= 0 ? n + 1 : "–"}</span>
    <button class="head" onclick={() => (open = open === id ? null : id)} aria-expanded={open === id}>
      <span class="dot {tone(p.state)}"></span>
      <span class="title">{p.name}</span>
      <span class="sub quiet ellipsis">{p.sub}{p.model ? ` · ${p.model}` : ""}</span>
      <span class="state meta">{p.on ? label(p.state) : "Off"}</span>
      <span class="chev" class:up={open === id}><Icon name="back" size={14} /></span>
    </button>
    <div class="order">
      <button class="btn ghost icon xs" onclick={() => move(id, -1)} disabled={every.indexOf(id) === 0} aria-label={`Try ${p.name} earlier`} title="Earlier"><span class="arr up"><Icon name="back" size={12} /></span></button>
      <button class="btn ghost icon xs" onclick={() => move(id, 1)} disabled={every.indexOf(id) === every.length - 1} aria-label={`Try ${p.name} later`} title="Later"><span class="arr down"><Icon name="back" size={12} /></span></button>
    </div>
    <label class="switch" title={p.on ? "Used by Automatic" : "Not used"}>
      <input type="checkbox" checked={p.on} onchange={(e) => toggle(id, e.currentTarget.checked)} aria-label={`Use ${p.name}`} />
      <span class="track"><span class="knob"></span></span>
    </label>
  </div>
{/snippet}

{#snippet keyed(id)}
  {@const p = P(id)}
  <div class="body">
    <ol class="steps">
      {#if p.local}
        <li>
          <div><b>Install Ollama and pull a model that can see pictures</b> <span class="quiet">· e.g. <span class="tc">ollama pull qwen2.5vl</span></span></div>
          <div class="row wrap">
            <button class="btn sm" onclick={() => openUrl(p.site)}><Icon name="link" size={14} /> Get Ollama</button>
            <button class="btn sm ghost" onclick={() => copy("ollama pull qwen2.5vl")}><Icon name="copy" size={14} /> Copy the command</button>
          </div>
        </li>
      {:else}
        <li>
          <div><b>Create an API key</b> <span class="quiet">· on {p.name}'s site</span></div>
          <div class="row wrap"><button class="btn sm" onclick={() => openUrl(p.site)}><Icon name="link" size={14} /> Open {p.name}</button></div>
        </li>
        <li class:done={p.state === "ready"}>
          <div><b>Paste it here</b></div>
          <div class="row">
            <input type="password" placeholder={p.state === "ready" ? "Key saved. Type to replace" : `${p.name} API key`} bind:value={keys[`${id}:key`]} aria-label={`${p.name} API key`} />
            <button class="btn sm primary" onclick={() => saveEnv(p.key_env, `${id}:key`)} disabled={!keys[`${id}:key`]?.trim()}>Save</button>
            {#if p.state === "ready"}<button class="btn sm ghost" onclick={() => removeEnv(p.key_env)}>Remove</button>{/if}
          </div>
        </li>
      {/if}
      <li class:done={!!p.model}>
        <div><b>Model</b> <span class="quiet">· {p.default_model ? `${p.default_model} unless you choose another` : "the model's name, as the service lists it"}{p.vision ? "" : ". This one can't look at pictures: it writes words and picks effects, and the next AI judges your footage"}</span></div>
        <div class="row">
          <input type="text" placeholder={p.model || "Model name"} bind:value={keys[`${id}:model`]} aria-label={`${p.name} model`} />
          <button class="btn sm" onclick={() => saveEnv(p.model_env, `${id}:model`, "Model")} disabled={!keys[`${id}:model`]?.trim()}>Save</button>
          {#if p.model && p.model !== p.default_model}<button class="btn sm ghost" onclick={() => removeEnv(p.model_env, "Model")}>Use the default</button>{/if}
        </div>
      </li>
      {#if p.local}
        <li>
          <div><b>Address</b> <span class="quiet">· where Ollama answers</span></div>
          <div class="row">
            <input type="text" placeholder={p.base} bind:value={keys[`${id}:base`]} aria-label="Ollama address" />
            <button class="btn sm" onclick={() => saveEnv(p.base_env, `${id}:base`, "Address")} disabled={!keys[`${id}:base`]?.trim()}>Save</button>
          </div>
        </li>
      {/if}
      <li>
        <div class="row wrap"><button class="btn sm" onclick={() => test(id)} disabled={testing[id] || p.state !== "ready"}>{#if testing[id]}<span class="spin"></span>{/if} Test</button>
          <span class="quiet small">sends one short message</span></div>
        {@render result(id)}
      </li>
    </ol>
    {#if id === "gemini"}
      <p class="quiet small">The same key also lets Gemini watch each clip once (best moment, shake, sound, spoken words){P("gemini").watch === "no_sdk" ? ": that part needs the Gemini library, which this engine doesn't have" : ""}.</p>
    {/if}
  </div>
{/snippet}

{#snippet result(id)}
  {#if results[id]}<p class="result" class:bad={!results[id].ok}>{results[id].message}</p>{/if}
{/snippet}

<section class="surface block" id="ai">
  <div class="row top">
    <h2>AI</h2>
    <div class="spacer"></div>
    <button class="btn sm ghost" onclick={load} aria-label="Check again"><Icon name="refresh" size={14} /> Check again</button>
  </div>
  <p class="muted intro">
    An AI judges your shots, picks the colour and writes the words on screen and the caption. Everything else runs on
    this computer. Set up at least one, or several: Automatic tries them in this order and moves to the next when one
    runs out or stops working.
  </p>

  {#if st}
    <div class="choose">
      <div class="seg" role="radiogroup" aria-label="Which AI makes the creative calls">
        {#each [["auto", "Automatic"], ["one", "One AI only"], ["none", "None"]] as [id, text]}
          <button role="radio" aria-checked={mode === id} class:on={mode === id}
                  onclick={() => setBackend(id === "one" ? (ready[0] || "claude-cli") : id)}>{text}</button>
        {/each}
      </div>
      {#if mode === "one"}
        <select value={st.backend} onchange={(e) => setBackend(e.currentTarget.value)} aria-label="The AI to use">
          {#each every as id}<option value={id} disabled={P(id).state !== "ready"}>{name(id)}{P(id).state !== "ready" ? ` (${label(P(id).state).toLowerCase()})` : ""}</option>{/each}
        </select>
      {/if}
      <p class="quiet small">
        {#if st.using}Making the creative calls now: <b>{name(st.using)}</b>.{:else if st.backend === "none"}No AI: shots are judged on sharpness and exposure only, and no captions are written.{:else}No AI is ready yet. Set one up below.{/if}
        {#if st.backend === "auto" && st.order.length > 1} If it runs out or stops working, {st.order.slice(1).map(name).join(", then ")} takes over.{/if}
        {#if st.backend === "auto"} Change the order with the arrows; switch one off to keep it out.{/if}
      </p>
    </div>

    <div class="providers">
      {#each every as id (id)}
        <div class="prov" class:open={open === id}>
          {@render head(id)}
          {#if open === id}
            {#if id === "claude-cli"}
          <div class="body">
            {#if P("claude-cli").state === "ready"}
              <p class="muted">{[P("claude-cli").account ? `Logged in as ${P("claude-cli").account}` : "Logged in", P("claude-cli").plan && `${P("claude-cli").plan} plan`, P("claude-cli").token && "with a saved token"].filter(Boolean).join(" · ")}</p>
            {/if}
            <ol class="steps">
              <li class:done={P("claude-cli").state !== "missing"}>
                <div><b>Install Claude Code</b> <span class="quiet">· the Claude command-line tool</span></div>
                {#if P("claude-cli").state === "missing"}
                  <div class="row wrap">
                    <button class="btn sm primary" onclick={() => terminal("claude-install")}><Icon name="terminal" size={14} /> Install in Terminal</button>
                    <button class="btn sm ghost" onclick={() => openUrl("https://docs.claude.com/en/docs/claude-code/setup")}>Install guide</button>
                  </div>
                {:else}<div class="meta">{P("claude-cli").path}</div>{/if}
              </li>
              <li class:done={P("claude-cli").state === "ready"}>
                <div><b>Log in with your Claude account</b> <span class="quiet">· a browser window opens to sign in, then come back here</span></div>
                {#if P("claude-cli").state !== "ready"}
                  <div class="row wrap">
                    <button class="btn sm primary" onclick={() => terminal("claude-login")} disabled={P("claude-cli").state === "missing"}><Icon name="terminal" size={14} /> Log in in Terminal</button>
                    <button class="btn sm ghost" onclick={() => copy("claude auth login")}><Icon name="copy" size={14} /> Copy the command</button>
                    {#if watching}<span class="quiet small"><span class="spin"></span> waiting for the login</span>{/if}
                  </div>
                {/if}
              </li>
              <li>
                <div><b>Test it</b> <span class="quiet">· sends one short message</span></div>
                <div class="row wrap">
                  <button class="btn sm" onclick={() => test("claude")} disabled={testing.claude || P("claude-cli").state === "missing"}>{#if testing.claude}<span class="spin"></span>{/if} Test</button>
                </div>
                {@render result("claude")}
              </li>
            </ol>
            <details>
              <summary class="quiet">Logged in, but TripShots still can't use it</summary>
              <p class="muted small">Make a long-lived token with <span class="tc">claude setup-token</span> and paste it here.</p>
              <div class="row">
                <button class="btn sm" onclick={() => terminal("claude-token")} disabled={P("claude-cli").state === "missing"}><Icon name="terminal" size={14} /> Make a token</button>
                <input type="password" placeholder={P("claude-cli").token ? "Token saved. Type to replace" : "Paste the token"} bind:value={keys.token} aria-label="Claude token" />
                <button class="btn sm" onclick={() => saveKey("CLAUDE_CODE_OAUTH_TOKEN", "token")} disabled={!keys.token.trim()}>Save</button>
                {#if P("claude-cli").token}<button class="btn sm ghost" onclick={() => removeKey("CLAUDE_CODE_OAUTH_TOKEN")}>Remove</button>{/if}
              </div>
            </details>
          </div>
        {:else}{@render keyed(id)}{/if}
          {/if}
        </div>
      {/each}
    </div>
    <p class="quiet small foot">Keys are saved in <span class="tc">~/.tripshots/.env</span> on this computer and only sent to the service they belong to.</p>
  {:else if error}
    <p class="muted small">{error}</p>
  {:else}
    <div class="empty"><span class="spin"></span></div>
  {/if}
</section>

<style>
  .block { padding: 20px 24px; }
  .top { margin-bottom: 8px; }
  .spacer { flex: 1; }
  .intro { margin: 0 0 16px; max-width: 720px; }
  .small { font-size: 13px; }
  .choose { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
  .choose p { margin: 0; }
  .seg { display: inline-flex; align-self: flex-start; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--raised); border-radius: 12px; }
  .seg button {
    height: 32px; padding: 0 12px; border: 0; border-radius: var(--r-ctl); background: transparent; color: var(--text-2);
    cursor: pointer; font-weight: 500; font-size: 13px; transition: background-color 150ms var(--ease), color 150ms var(--ease);
  }
  .seg button:hover { color: var(--text); }
  .seg button.on { background: var(--card); color: var(--text); box-shadow: inset 0 0 0 1px var(--line), var(--highlight); }
  .providers { border: 1px solid var(--line); border-radius: var(--r-card); overflow: hidden; }
  .prov + .prov { border-top: 1px solid var(--line); }
  .headrow { display: flex; align-items: center; gap: 4px; padding-right: 12px; }
  .headrow.off .title, .headrow.off .sub { opacity: 0.5; }
  .pos { width: 28px; flex: none; text-align: right; color: var(--text-3); font-size: 12px; }
  .order { display: flex; gap: 0; }
  .btn.xs { width: 24px; height: 24px; min-height: 24px; padding: 0; }
  .arr { display: grid; place-items: center; }
  .arr.up { transform: rotate(90deg); }
  .arr.down { transform: rotate(-90deg); }
  .switch { display: flex; align-items: center; margin-left: 8px; cursor: pointer; }
  .switch input { position: absolute; opacity: 0; width: 0; height: 0; }
  .track { width: 32px; height: 20px; border-radius: 10px; background: var(--line-strong); position: relative; transition: background-color 150ms var(--ease); }
  .knob { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: var(--card); box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2); transition: transform 200ms var(--ease); }
  .switch input:checked + .track { background: var(--accent); }
  .switch input:checked + .track .knob { transform: translateX(12px); }
  .switch input:focus-visible + .track { outline: 2px solid var(--accent); outline-offset: 2px; }
  .choose select { align-self: flex-start; min-width: 220px; }
  .head {
    flex: 1; min-width: 0;
    display: grid; grid-template-columns: 8px auto 1fr auto 16px; align-items: center; gap: 12px; width: 100%;
    height: 48px; padding: 0 12px; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer;
    transition: background-color 150ms var(--ease);
  }
  .head:hover { background: var(--raised); }
  .title { font-weight: 500; }
  .chev { color: var(--text-3); display: grid; place-items: center; transform: rotate(-90deg); transition: transform 150ms var(--ease); }
  .chev.up { transform: rotate(90deg); }
  .body { padding: 4px 16px 16px 64px; display: flex; flex-direction: column; gap: 12px; }
  .body > p { margin: 0; }
  .steps { margin: 0; padding: 0 0 0 20px; display: flex; flex-direction: column; gap: 12px; }
  .steps li { padding-left: 4px; }
  .steps li::marker { color: var(--text-3); font-family: var(--mono); font-size: 12px; }
  .steps li.done::marker { color: var(--ok); }
  .steps li > div + div { margin-top: 8px; }
  .row.wrap { flex-wrap: wrap; }
  .row input { max-width: 360px; height: 28px; min-height: 28px; padding: 0 8px; font-size: 13px; }
  .result { margin: 8px 0 0; font-size: 13px; color: var(--ok); user-select: text; }
  .result.bad { color: var(--err); }
  details { font-size: 13px; }
  details summary { cursor: pointer; }
  details p { margin: 8px 0; }
  .foot { margin: 12px 0 0; }
</style>
