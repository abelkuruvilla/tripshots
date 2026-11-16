<script>
  // Colour: the reel's look (with strength, grain, vignette) and one shot's own corrections on top of it.
  // The shot is the selected one, else the one under the playhead. Hold Compare to see it as filmed.
  import { onMount } from "svelte";
  import { open } from "@tauri-apps/plugin-dialog";
  import Icon from "../../lib/Icon.svelte";
  import Sheet from "../../lib/Sheet.svelte";
  import LayersPanel from "./LayersPanel.svelte";
  import Section from "../../lib/Section.svelte";
  import { app, api, tc, startJob, toast } from "../../lib/store.svelte.js";
  import { ed, edit } from "./editor.svelte.js";

  const sliders = [
    ["exposure", "Exposure", -2, 2, 0.05, 0, (v) => `${v > 0 ? "+" : ""}${(+v).toFixed(2)} stops`],
    ["contrast", "Contrast", 0.4, 1.6, 0.01, 1, (v) => `${Math.round((v - 1) * 100)}`],
    ["saturation", "Saturation", 0, 2, 0.01, 1, (v) => `${Math.round((v - 1) * 100)}`],
    ["warmth", "Warmth", -1, 1, 0.01, 0, (v) => (v > 0 ? `warmer ${Math.round(v * 100)}` : v < 0 ? `cooler ${Math.round(-v * 100)}` : "0")],
    ["tint", "Tint", -1, 1, 0.01, 0, (v) => (v > 0 ? `magenta ${Math.round(v * 100)}` : v < 0 ? `green ${Math.round(-v * 100)}` : "0")],
    ["shadows", "Shadows", -1, 1, 0.01, 0, (v) => `${Math.round(v * 100)}`],
    ["highlights", "Highlights", -1, 1, 0.01, 0, (v) => `${Math.round(v * 100)}`],
  ];
  const lightName = { golden: "golden light", blue_hour: "blue hour", night: "night", mixed: "" };
  const logName = { "": "Normal video", apple_log: "Apple Log", dlog: "DJI D-Log", slog3: "Sony S-Log3", vlog: "Panasonic V-Log",
                    flog: "Fujifilm F-Log", flog2: "Fujifilm F-Log2", clog3: "Canon C-Log3" };

  let looks = $state([]);
  let packs = $state([]);
  const loadLooks = async () => {
    looks = await api("/api/looks").catch(() => looks);
    packs = await api("/api/lookpacks").catch(() => packs);
  };
  onMount(loadLooks);

  // which looks the strip shows: all, the built-in ones, yours (measured from reels or added by you), or one pack
  let filter = $state("all");
  let q = $state("");
  let more = $state(false);
  let filters = $derived([["all", "All"], ["builtin", "Built in"], ["yours", "Yours"],
    ...packs.filter((p) => p.installed).map((p) => [p.id, p.title])]);
  const fits = (l) => (filter === "all" || (filter === "builtin" && l.builtin) || (filter === "yours" && !l.builtin && (!l.pack || l.pack === "yours"))
    || l.pack === filter) && (!q || `${l.name} ${l.title || ""} ${l.description}`.toLowerCase().includes(q.toLowerCase()));

  // a looks job (fetching a pack, adding files) finished: show what it added
  let lookJobs = new Set();
  $effect(() => {
    for (const j of app.jobs) {
      if (j.kind === "looks" && j.state !== "running" && lookJobs.has(j.id)) {
        lookJobs.delete(j.id);
        loadLooks();
      }
    }
  });
  async function fetchPack(p) {
    const st = await startJob("looks", { action: "fetch", pack: p.id }, `Looks: ${p.title}`).catch((e) => toast(String(e.message || e), "error"));
    if (st) lookJobs.add(st.id);
  }
  async function removePack(p) {
    const st = await startJob("looks", { action: "remove", pack: p.id }, `Remove ${p.title}`).catch((e) => toast(String(e.message || e), "error"));
    if (st) lookJobs.add(st.id);
    if (filter === p.id) filter = "all";
  }
  async function importFiles() {
    const got = await open({ multiple: true, title: "LUT files", filters: [{ name: "LUTs", extensions: ["cube", "png", "tif", "tiff", "zip"] }] });
    const files = [got].flat().filter(Boolean);
    if (!files.length) return;
    const st = await startJob("looks", { action: "add", files }, "Add looks").catch((e) => toast(String(e.message || e), "error"));
    if (st) lookJobs.add(st.id);
  }
  let running = $derived(app.jobs.some((j) => j.kind === "looks" && j.state === "running"));

  let reel = $derived(ed.reel);
  let g = $derived(reel?.grading || {});
  let off = $derived(!g.look || g.look === "none");
  // the reel's look first, then the built-in ones, then yours and the packs; log LUTs only when asked for by name
  let ordered = $derived([...looks].filter((l) => fits(l) && (!l.for_log || q))
    .sort((a, b) => (b.name === g.look) - (a.name === g.look) || (b.builtin - a.builtin)));
  let s = $derived.by(() => {
    if (!reel) return null;
    if (ed.sel?.kind === "clip") return reel.segments[ed.sel.slot - 1];
    return reel.segments.find((x) => ed.now >= x.start && ed.now < x.start + x.dur) || reel.segments[0];
  });

  // drafts that follow the plan until the slider is let go
  let strength = $state(0.75);
  let grain = $state(0);
  let vals = $state({});
  let gk = "";
  $effect(() => {
    const k = JSON.stringify(g);
    if (k !== gk) {
      gk = k;
      strength = g.strength ?? 0.75;
      grain = g.grain || 0;
    }
  });
  let sk = "";
  $effect(() => {
    const k = s ? `${s.slot}|${JSON.stringify(s.adjust)}` : "";
    if (k !== sk) {
      sk = k;
      vals = Object.fromEntries(sliders.map(([key, , , , , n]) => [key, s?.adjust?.[key] ?? n]));
    }
  });

  let working = $state(false);
  async function look(name) {
    working = true;
    ed.preview = true;
    await edit({ op: "grade", look: name, ...(name !== "none" ? { strength: +strength } : {}) });
    working = false;
  }
  const grade = (o) => {
    ed.preview = true;
    return edit({ op: "grade", look: g.look, ...o }, true);
  };
  const adjust = (o) => {
    ed.preview = true;
    return edit({ op: "adjust", segment: s.slot, ...o }, true);
  };
  const changed = $derived(s && (Object.keys(s.adjust || {}).length || s.no_grade));
  const nice = (n) => n.replace(/[-_]+/g, " ").replace(/^./, (c) => c.toUpperCase());
  const label = (l) => l.title || nice(l.name);
  let current = $derived(looks.find((l) => l.name === g.look));
  // the shot shown in each look: the selected one, else the one at the playhead
  const thumb = (name) => `${app.engine.url}/api/lookthumb?t=${app.engine.token}&plan=${encodeURIComponent(reel.plan)}&slot=${s.slot}&look=${encodeURIComponent(name)}&v=${g.strength}`;
</script>

<div class="topbar">
  <span class="meta" title={ed.sel?.kind === "clip" ? "The selected shot" : "The shot at the playhead"}>{s ? `Shot ${s.slot}` : ""}</span>
  {#if working}<span class="spin small-spin" aria-label="Applying the look"></span>{/if}
  <div class="spacer"></div>
  <button class="btn sm ghost" title="Hold to see the shot as filmed (or hold Space on it)" aria-label="Hold to compare with the shot as filmed"
          aria-pressed={ed.raw}
          onpointerdown={() => ((ed.preview = true), (ed.raw = true))} onpointerup={() => (ed.raw = false)}
          onpointerleave={() => (ed.raw = false)}
          onkeydown={(e) => (e.key === " " || e.key === "Enter") && (e.preventDefault(), (ed.preview = true), (ed.raw = true))}
          onkeyup={() => (ed.raw = false)} onblur={() => (ed.raw = false)}><Icon name="eye" size={14} /> Compare</button>
  <button class="btn sm ghost" class:pressed={ed.split} aria-pressed={ed.split} title="As filmed and your edit side by side, with a divider to drag"
          onclick={() => ((ed.split = !ed.split), (ed.preview = true))}><Icon name="split" size={14} /> Before | after</button>
</div>

<Section id="colour-look" title="Look" open={true}
         summary={off ? "None" : `${current ? label(current) : nice(g.look || "")} · ${Math.round((g.strength ?? 0.75) * 100)}%`}>
  {#snippet actions()}<button class="btn sm ghost" onclick={() => (more = true)} title="Add LUT files or get a free pack"><Icon name="plus" size={14} /> More</button>{/snippet}
  <div class="seg chips-seg" role="radiogroup" aria-label="Show looks">
    {#each filters as [id, name]}<button role="radio" aria-checked={filter === id} onclick={() => (filter = id)}>{name}</button>{/each}
  </div>
  {#if looks.length > 24}
    <input type="search" class="find" placeholder="Find a look" bind:value={q} aria-label="Find a look" />
  {/if}
  <div class="looks" role="radiogroup" aria-label="Look">
    {#each [{ name: "none", description: "As filmed, with a light touch", builtin: true }, ...ordered] as l (l.name)}
      {@const on = l.name === "none" ? off : g.look === l.name}
      <button role="radio" aria-checked={on} class="look" class:on onclick={() => look(l.name)} disabled={ed.busy} title={l.description}>
        <span class="pic">{#if s}<img src={thumb(l.name)} alt="" loading="lazy" />{/if}</span>
        <span class="name ellipsis">{l.name === "none" ? "None" : label(l)}</span>
      </button>
    {/each}
  </div>
  <p class="quiet small">{off ? "No look: each shot as filmed" : `${current ? label(current) + ": " : ""}${current?.description || ""}`}{!off && current?.pack ? ` · ${packs.find((p) => p.id === current.pack)?.title || "added by you"}` : ""}</p>
  {#if g.why}<p class="quiet small">{g.why}</p>{/if}
  {#if !off}
    <div class="grid3">
      <div class="field">
        <label for="gs">Strength <span class="hint">· {Math.round(strength * 100)}%</span></label>
        <input id="gs" class="range" type="range" min="0" max="1" step="0.05" bind:value={strength} onchange={() => grade({ strength: +strength })} />
      </div>
      <div class="field">
        <label for="gg">Grain <span class="hint">· {grain || "none"}</span></label>
        <input id="gg" class="range" type="range" min="0" max="12" step="1" bind:value={grain} onchange={() => grade({ grain: +grain })} />
      </div>
    </div>
    <label class="check"><input type="checkbox" checked={!!g.vignette} onchange={(e) => grade({ vignette: e.currentTarget.checked })} /> Vignette <span class="hint">· darker corners</span></label>
  {/if}
</Section>

{#if s}
  <Section id="colour-shot" title={`Shot ${s.slot} corrections`} open={true}
           summary={s.no_grade ? "as filmed" : Object.keys(s.adjust || {}).length ? `${Object.keys(s.adjust).length} changed` : "none"}>
    <div class="row">
      <span class="meta">{[tc(s.start), lightName[s.light] ?? s.light].filter(Boolean).join(" · ")}</span>
      <div class="spacer"></div>
      {#if !off}
        <label class="check"><input type="checkbox" checked={!s.no_grade} onchange={(e) => adjust({ graded: e.currentTarget.checked })} /> In the look</label>
      {/if}
    </div>
    <div class="sliders">
      {#each sliders as [key, name, lo, hi, step, neutral, fmt]}
        <div class="sl">
          <label for={"a-" + key}>{name}</label>
          <input id={"a-" + key} class="range" type="range" min={lo} max={hi} {step} bind:value={vals[key]}
                 ondblclick={() => ((vals[key] = neutral), adjust({ [key]: null }))}
                 onchange={() => adjust({ [key]: +vals[key] })} />
          <span class="meta val">{fmt(vals[key])}</span>
        </div>
      {/each}
    </div>
    <div class="row foot">
      <button class="btn sm ghost" disabled={!changed} onclick={() => adjust({ reset: true })}>Reset</button>
      <div class="spacer"></div>
      <button class="btn sm" disabled={!Object.keys(s.adjust || {}).length}
              onclick={() => edit({ op: "adjust", segment: "all", ...Object.fromEntries(sliders.map(([k, , , , , n]) => [k, s.adjust?.[k] ?? n])) })}
              title="Give every shot these corrections">Use on every shot</button>
    </div>
    <p class="quiet small">Double-click a slider to reset it</p>
  </Section>

  {#if s.kind === "video" && !s.panel}
    <Section id="colour-log" title="Filmed in" summary={logName[s.log || ""]}>
      <p class="quiet small">Flat log footage (drones, Apple Log, cinema cameras) is made normal before anything else</p>
      <div class="row">
        <select id="clog" aria-label="Filmed in" value={s.log || ""} onchange={(e) => edit({ op: "log", segment: s.slot, profile: e.currentTarget.value || null })}>
          {#each Object.entries(logName) as [id, name]}<option value={id}>{name}</option>{/each}
        </select>
        {#if s.log}<button class="btn sm ghost" onclick={() => edit({ op: "log", segment: "all", profile: s.log })} title="Every clip in this reel was filmed this way">All clips</button>{/if}
      </div>
    </Section>
  {/if}

  <Section id="colour-layers" title="Parts of the frame" summary={(s.layers || []).length ? `${s.layers.length} layer${s.layers.length > 1 ? "s" : ""}` : "none"}>
    <LayersPanel shot={s} />
  </Section>
{/if}

{#if more}
  <Sheet title="More looks" onclose={() => (more = false)}>
    <div class="more">
      <p class="muted">Any LUT can be a look: a <span class="tc">.cube</span> file or a HaldCLUT image, on its own, in a folder or a zip. TripShots balances each shot first, so they still match, then puts the LUT on top at the look's strength, keeping skin close to its own colour</p>
      <button class="btn" onclick={importFiles} disabled={running}><Icon name="folder" /> Add LUT files</button>

      <h3>Free packs</h3>
      {#each packs as p (p.id)}
        <div class="pack surface">
          <div class="row"><h3>{p.title}</h3><span class="meta">{p.by}</span><div class="spacer"></div>
            <span class="meta">{p.installed ? `${p.installed} looks` : `${p.size_mb} MB`}</span></div>
          <p class="muted small">{p.about}</p>
          <p class="quiet small">{p.licence}</p>
          <div class="row">
            {#if p.installed}
              <button class="btn sm" onclick={() => ((filter = p.id), (more = false))}>Show them</button>
              <button class="btn sm ghost danger" onclick={() => removePack(p)} disabled={running}>Remove</button>
            {:else}
              <button class="btn sm primary" onclick={() => fetchPack(p)} disabled={running}><Icon name="download" size={14} /> Get them</button>
            {/if}
          </div>
        </div>
      {/each}
      {#if running}<p class="state"><span class="spin" style="width: 10px; height: 10px; border-width: 1.5px"></span> Adding looks; Activity shows the progress</p>{/if}
      <p class="quiet small">Looks from <span class="tc">tripshots look</span> (measured from reels you like) show up under Yours too</p>
    </div>
  </Sheet>
{/if}

<style>
  .topbar { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 4px; padding: 8px 12px 8px 16px;
            background: var(--card); border-bottom: 1px solid var(--line); }
  p { margin: 0; }
  .spacer { flex: 1; }
  .small { font-size: 12px; line-height: 16px; }
  .small-spin { width: 12px; height: 12px; color: var(--accent); }
  h3 { font-size: 13px; font-weight: 500; margin: 0; }
  .filterbar { gap: 8px; }
  .chips-seg { flex-wrap: wrap; max-width: 100%; }
  .find { min-height: 32px; padding: 6px 10px; }
  .more { display: flex; flex-direction: column; gap: 16px; align-items: flex-start; }
  .pack { width: 100%; padding: 16px; display: flex; flex-direction: column; gap: 8px; }
  .looks { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px 8px; max-height: 236px; overflow: auto; padding: 2px; }
  .look { display: flex; flex-direction: column; gap: 6px; padding: 0; border: 0; background: none; text-align: left; min-width: 0; }
  .pic {
    display: block; aspect-ratio: 1; border-radius: var(--r-ctl); overflow: hidden; background: var(--raised);
    box-shadow: inset 0 0 0 1px var(--line); transition: box-shadow var(--fast) var(--ease);
  }
  .pic img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .look:hover .pic { box-shadow: 0 0 0 2px var(--line-strong); }
  .look.on .pic { box-shadow: 0 0 0 2px var(--accent); }
  .name { font-size: 12px; color: var(--text-2); }
  .look.on .name { color: var(--text); font-weight: 500; }
  .look:disabled { cursor: default; }
  .pressed { background: var(--accent-soft); border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
  .grid3 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px 12px; }
  .field { margin: 0; min-width: 0; }
  .lbl { display: block; font-weight: 500; font-size: 13px; margin: 0 0 8px; }
  .range { width: 100%; accent-color: var(--accent); margin: 0; }
  .check { display: flex; align-items: center; gap: 8px; margin: 0; font-weight: 400; font-size: 13px; }
  .check input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
  .sliders { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
  .sl { display: grid; grid-template-columns: 76px 1fr 88px; gap: 10px; align-items: center; }
  .sl label { margin: 0; font-weight: 400; color: var(--text-2); }
  .val { text-align: right; }
  .foot { padding-top: 4px; }
</style>
