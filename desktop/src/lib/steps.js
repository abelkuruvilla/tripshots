// Where a long job is, from its log: the steps of making a reel, in order. A step counts as reached when a log
// line of it appears; the job shows "Step 3 of 5 · Planning". Jobs of other kinds have no steps.
const MAKE = [
  ["Reading the request", /^understood:|reading your request/i],
  ["Finding footage", /media files|found \d+|selection|clips shorter/i],
  ["Choosing shots", /using \d+ videos|scor|judg|batch \d+\/\d+|AI colourist|watch/i],
  ["Planning the edit", /^plan:|story|recipe|critic|grade: look/i],
  ["Rendering", /rendering \d+ shots|compositing|encoder:|^\s*\d+\/\d+$/i],
  ["Sound and checks", /sound design|sound:|qa:|loudness|render took|done:/i],
];
const RENDER = MAKE.slice(4);

export function steps(kind, log = [], state = "running") {
  const list = kind === "render" ? RENDER : kind === "make" || kind === "ask" ? (kind === "ask" ? MAKE : MAKE.slice(1)) : null;
  if (!list) return null;
  let at = 0;
  for (const line of log) list.forEach(([, re], i) => { if (re.test(line) && i > at) at = i; });
  if (state === "done") at = list.length;
  return { at, total: list.length, names: list.map(([n]) => n), label: list[Math.min(at, list.length - 1)][0] };
}

export const kindName = { make: "Make", render: "Render", ask: "Ask", learn: "Learn a style", find: "Find footage", trips: "Trips",
  music: "Sound", qa: "Check", analyze: "Analyse", discover: "People", caption: "Caption", looks: "Looks" };
