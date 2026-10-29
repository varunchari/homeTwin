// Day 1: render HA states, live-update ONLY from WebSocket state_changed
// events relayed by the backend. No optimistic UI.
const statusEl = document.getElementById("status");
const listEl = document.getElementById("entities");
const states = new Map();

function render() {
  listEl.innerHTML = "";
  for (const [id, st] of states) {
    if (id.startsWith("input_boolean.")) continue; // helpers back templates; not devices
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = prettyEntity(id);
    name.title = id;
    const dot = document.createElement("span");
    dot.className = "dot" + (st === "on" ? " on" : "");
    dot.title = st;
    li.appendChild(name);
    li.appendChild(dot);
    listEl.appendChild(li);
  }
  // Ambient strip: sun + lights-on at a glance. Pins follow live state too.
  const sun = states.get("sun.sun");
  const sunState = document.getElementById("sun-state");
  const sunDot = document.getElementById("sun-dot");
  if (sunState) {
    const day = sun === "above_horizon";
    sunState.textContent = sun ? (day ? "Daytime" : "Night") : "—";
    if (sunDot) sunDot.className = "dot" + (sun ? (day ? " day" : " night") : "");
  }
  const onCount = [...states].filter(([id, st]) => id.startsWith("light.") && st === "on").length;
  const lightsOn = document.getElementById("lights-on");
  if (lightsOn) lightsOn.textContent = `${onCount} light${onCount === 1 ? "" : "s"} on`;
  if (typeof updatePins === "function") updatePins();
}

async function load() {
  const res = await fetch("/api/entities");
  const entities = await res.json();
  noteNames(entities);
  for (const e of entities) states.set(e.entity_id, e.state);
  render();
  await refreshEntities();
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { statusEl.textContent = "Live"; statusEl.classList.add("on"); };
  ws.onclose = () => { statusEl.textContent = "Reconnecting…"; statusEl.classList.remove("on"); setTimeout(connect, 2000); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    const st = msg?.data?.new_state;
    if (st) {
      states.set(st.entity_id, st.state);
      render();
    }
  };
}

// Day 2: room photo, SAM regions, manual fallback. Overlays are drawn
// deterministically from the scene graph; reload shows the same graph.
const photoInput = document.getElementById("photo-input");
const photoEl = document.getElementById("photo");
const regionsEl = document.getElementById("regions");
const phraseInput = document.getElementById("phrase-input");
const phraseChips = document.getElementById("phrase-chips");
const segmentBtn = document.getElementById("segment-btn");
const drawBtn = document.getElementById("draw-btn");
const photoMsg = document.getElementById("photo-msg");
const regionList = document.getElementById("region-list");
let photoId = null;
let drawing = false;
let drawStart = null;

const SUGGESTED = ["lamp", "string lights", "patio door", "tv", "smart display", "reading light"];
for (const p of SUGGESTED) {
  const chip = document.createElement("button");
  chip.className = "chip";
  chip.textContent = p;
  chip.addEventListener("click", () => {
    phraseInput.value = p;
    segmentBtn.click();
  });
  phraseChips.appendChild(chip);
}

function say(msg) { photoMsg.textContent = msg; }

let bindings = {};
let selectedId = null;

let lastRegions = [];

function renderRegions(regions) {
  lastRegions = regions;
  regionsEl.innerHTML = "";
  regionList.innerHTML = "";
  for (const r of regions) {
    const box = document.createElement("div");
    box.className = "region box" + (r.source === "manual" ? " manual" : "");
    box.dataset.oid = r.object_id;
    box.style.left = `${r.x * 100}%`;
    box.style.top = `${r.y * 100}%`;
    box.style.width = `${r.w * 100}%`;
    box.style.height = `${r.h * 100}%`;
    box.title = `${r.object_id} (${r.source})`;
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = r.object_id;
    box.appendChild(tag);
    if (bindings[r.object_id]) box.classList.add("bound");
    regionsEl.appendChild(box);
    // Screens (TV, smart display) light up when their switch is on.
    if (/tv|display|screen/i.test(`${r.object_id} ${r.phrase}`)) {
      const screen = document.createElement("div");
      screen.className = "screen";
      screen.dataset.oid = r.object_id;
      screen.style.left = `${r.x * 100}%`;
      screen.style.top = `${r.y * 100}%`;
      screen.style.width = `${r.w * 100}%`;
      screen.style.height = `${r.h * 100}%`;
      regionsEl.appendChild(screen);
    }
    // Device pin: the everyday face. Boxes appear only when selected/drawing.
    const pin = document.createElement("button");
    pin.className = "pin" + (r.source === "manual" ? " manual" : "");
    pin.dataset.oid = r.object_id;
    pin.style.left = `${(r.x + r.w / 2) * 100}%`;
    pin.style.top = `${(r.y + r.h / 2) * 100}%`;
    pin.title = `${r.object_id} (${r.source})`;
    pin.textContent = r.object_id.charAt(0).toUpperCase();
    if (bindings[r.object_id]) pin.classList.add("bound");
    const activate = async (ev) => {
      if (drawing) return;
      ev.stopPropagation();
      selectRegion(r.object_id);
      if (bindings[r.object_id]) await tapSelected();
    };
    pin.addEventListener("click", activate);
    box.addEventListener("click", activate);
    regionsEl.appendChild(pin);
    const li = document.createElement("li");
    li.className = r.source;
    li.textContent = `${r.object_id} · ${r.phrase}`;
    li.title = `source: ${r.source}`;
    regionList.appendChild(li);
  }
  if (selectedId) showSelected(selectedId);
  updatePins();
}

function updatePins() {
  for (const pin of regionsEl.querySelectorAll(".pin")) {
    const entity = bindings[pin.dataset.oid];
    pin.classList.toggle("on", !!entity && states.get(entity) === "on");
    pin.classList.toggle("selected", pin.dataset.oid === selectedId);
  }
  for (const box of regionsEl.querySelectorAll(".box")) {
    box.classList.toggle("selected", box.dataset.oid === selectedId);
  }
  for (const screen of regionsEl.querySelectorAll(".screen")) {
    const entity = bindings[screen.dataset.oid];
    screen.classList.toggle("on", !!entity && states.get(entity) === "on");
  }
}

async function refreshGraph() {
  if (!photoId) return;
  const res = await fetch(`/api/photos/${photoId}/graph`);
  const graph = await res.json();
  bindings = graph.bindings || {};
  renderRegions(graph.regions);
  refreshAutoSelects(Object.keys(bindings));
  if (selectedId) showSelected(selectedId);
}

function selectRegion(objectId) {
  selectedId = objectId;
  document.getElementById("sheet").hidden = false;
  showSelected(objectId);
  updatePins();
}

function deselect() {
  selectedId = null;
  document.getElementById("sheet").hidden = true;
  updatePins();
}
document.getElementById("sheet-close").addEventListener("click", deselect);
photoEl.addEventListener("click", () => { if (!drawing) deselect(); });

function showSelected(objectId) {
  const info = document.getElementById("selected-info");
  const bound = bindings[objectId];
  info.textContent = bound
    ? `${prettyOid(objectId)} → ${prettyEntity(bound)}`
    : `${prettyOid(objectId)} (unbound)`;
}

const sourceSelect = document.getElementById("source-select");
const targetSelect = document.getElementById("target-select");
const autoText = document.getElementById("auto-text");
const planView = document.getElementById("plan-view");
function refreshAutoSelects(boundIds) {
  for (const sel of [sourceSelect, targetSelect]) {
    const keep = sel.value;
    sel.innerHTML = "";
    for (const id of boundIds) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `${prettyOid(id)} → ${prettyEntity(bindings[id])}`;
      sel.appendChild(opt);
    }
    if (boundIds.includes(keep)) sel.value = keep;
  }
}
document.getElementById("plan-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  if (!sourceSelect.value || !targetSelect.value) { say("Bind regions first."); return; }
  say("Asking Spark for an automation plan…");
  planView.innerHTML = "";
  const res = await fetch("/api/automations/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      photo_id: photoId,
      source_object_id: sourceSelect.value,
      target_object_id: targetSelect.value,
      text: autoText.value,
    }),
  });
  const body = await res.json();
  if (!res.ok) {
    const div = document.createElement("div");
    div.className = "plan rejected";
    div.textContent = `Rejected: ${body.detail || res.status}. No HA write happened.`;
    planView.appendChild(div);
    say("Plan rejected — see Automate panel.");
    return;
  }
  const div = document.createElement("div");
  div.className = "plan";
  const ir = body.ir;
  const cond = ir.condition ? ` when sun ${ir.condition.sun.replace("_", " ")}` : "";
  const delay = ir.delay_s ? `, off after ${ir.delay_s}s` : "";
  div.innerHTML = `<strong>${ir.description || "Automation plan"}</strong>` +
    `<br />${prettyEntity(ir.trigger.entity_id)} → ${prettyEntity(ir.action.entity_id)}${cond}${delay}` +
    `<br /><span class="muted">Compiled ${body.compiled.trigger.length} trigger(s), ` +
    `${body.compiled.action.length} action step(s) in ${body.latency_ms} ms. ` +
    `Approval required before deploy.</span>`;
  const btn = document.createElement("button");
  btn.className = "btn primary";
  btn.textContent = "Approve & deploy";
  btn.addEventListener("click", async () => {
    const r2 = await fetch(`/api/automations/${body.proposal_id}/approve`, { method: "POST" });
    const b2 = await r2.json();
    say(r2.ok ? `Deployed ${b2.automation_id}.` : `Deploy failed: ${b2.detail || r2.status}`);
  });
  div.appendChild(document.createElement("br"));
  div.appendChild(btn);
  planView.appendChild(div);
  say("Plan ready — review and approve to deploy.");
  await refreshProposals();
});

const whatifProposal = document.getElementById("whatif-proposal");
const whatifDoor = document.getElementById("whatif-door");
const whatifSun = document.getElementById("whatif-sun");
const whatifView = document.getElementById("whatif-view");
async function refreshProposals() {
  // Proposals belong to the current photo only. Before any photo is chosen
  // the list stays empty — global history would look prepopulated.
  const keep = whatifProposal.value;
  whatifProposal.innerHTML = "";
  if (!photoId) return;
  const res = await fetch(`/api/automations/proposals?photo_id=${photoId}`);
  const body = await res.json();
  for (const p of body.proposals) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = `#${p.id} ${prettyOid(p.source_id)} → ${prettyOid(p.target_id)} [${p.status}]`;
    whatifProposal.appendChild(opt);
  }
  if ([...whatifProposal.options].some((o) => o.value === keep)) whatifProposal.value = keep;
}
document.getElementById("whatif-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  if (!whatifProposal.value) { say("Generate a plan first."); return; }
  const res = await fetch("/api/whatif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      proposal_id: Number(whatifProposal.value),
      door: whatifDoor.value,
      sun: whatifSun.value,
    }),
  });
  const body = await res.json();
  whatifView.innerHTML = "";
  const div = document.createElement("div");
  div.className = "plan" + (body.fires ? "" : " rejected");
  div.textContent = res.ok
    ? (body.fires
      ? `SIMULATED: fires — ${body.condition_note}.`
      : `SIMULATED: no fire — ${body.condition_note}.`)
    : `What-If failed: ${body.detail || res.status}`;
  whatifView.appendChild(div);
});

async function tapSelected() {
  if (!photoId || !selectedId) return;
  const res = await fetch(`/api/photos/${photoId}/tap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_id: selectedId }),
  });
  const body = await res.json();
  say(res.ok ? `Tapped ${selectedId} (${body.action}). Watch the Devices panel.` : `Tap failed: ${body.detail || res.status}`);
}

const entitySelect = document.getElementById("entity-select");
// Friendly display names everywhere: HA entity_ids never surface in the UI.
// Values stay entity_ids; only labels are humanized.
const names = new Map();
function prettyEntity(id) {
  if (names.has(id)) return names.get(id);
  return id.split(".").slice(1).join(" ").replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
function prettyOid(oid) {
  return oid.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function noteNames(entities) {
  for (const e of entities) {
    const friendly = (e.attributes || {}).friendly_name;
    if (friendly) names.set(e.entity_id, friendly);
  }
}
const BINDABLE_INPUTS = ["input_boolean.tv_on", "input_boolean.display_on"];
async function refreshEntities() {
  const res = await fetch("/api/entities");
  const entities = await res.json();
  noteNames(entities);
  entitySelect.innerHTML = "";
  for (const e of entities) {
    const domain = e.entity_id.split(".")[0];
    if (domain !== "light" && domain !== "binary_sensor" &&
        !BINDABLE_INPUTS.includes(e.entity_id)) continue;
    const opt = document.createElement("option");
    opt.value = e.entity_id;
    opt.textContent = `${prettyEntity(e.entity_id)} (${e.state})`;
    entitySelect.appendChild(opt);
  }
}

document.getElementById("bind-btn").addEventListener("click", async () => {
  if (!photoId || !selectedId) { say("Select a region first."); return; }
  const res = await fetch(`/api/photos/${photoId}/bindings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_id: selectedId, entity_id: entitySelect.value }),
  });
  const body = await res.json();
  say(res.ok ? `Bound ${prettyOid(selectedId)} → ${prettyEntity(entitySelect.value)}.` : `Bind failed: ${body.detail || res.status}`);
  await refreshGraph();
});

document.getElementById("unbind-btn").addEventListener("click", async () => {
  if (!photoId || !selectedId) return;
  await fetch(`/api/photos/${photoId}/bindings/${selectedId}`, { method: "DELETE" });
  say(`Unbound ${selectedId}.`);
  await refreshGraph();
});

document.getElementById("tap-btn").addEventListener("click", tapSelected);

const proposalList = document.getElementById("proposal-list");
async function applyProposal(p) {
  const res = await fetch(`/api/photos/${photoId}/bindings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ object_id: p.object_id, entity_id: p.entity_id }),
  });
  return res.ok;
}
document.getElementById("suggest-btn").addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  say("Asking Spark for binding suggestions…");
  const res = await fetch(`/api/photos/${photoId}/suggest-bindings`, { method: "POST" });
  const body = await res.json();
  if (!res.ok) { say(`Suggest failed: ${body.detail || res.status}`); return; }
  proposalList.innerHTML = "";
  if (!body.proposals.length) {
    say(body.note || "No suggestions — everything is bound or nothing matched.");
    return;
  }
  say(`${body.proposals.length} suggestion(s). Approve each, or all at once.`);
  for (const p of body.proposals) {
    const li = document.createElement("li");
    li.textContent = `${prettyOid(p.object_id)} → ${prettyEntity(p.entity_id)} (${Math.round(p.confidence * 100)}%): ${p.reason}${p.conflict ? " [CONFLICT]" : ""}`;
    const btn = document.createElement("button");
    btn.className = "btn";
    btn.textContent = "Approve";
    btn.addEventListener("click", async () => {
      say(await applyProposal(p) ? `Bound ${p.object_id}.` : `Bind failed for ${p.object_id}.`);
      await refreshGraph();
    });
    li.appendChild(btn);
    proposalList.appendChild(li);
  }
  const all = document.createElement("button");
  all.className = "btn primary";
  all.textContent = "Approve all";
  all.addEventListener("click", async () => {
    for (const p of body.proposals) {
      if (p.conflict) continue;
      await applyProposal(p);
    }
    say("Approved all non-conflicting suggestions.");
    await refreshGraph();
  });
  proposalList.appendChild(all);
});
document.getElementById("reset-btn").addEventListener("click", async () => {
  const res = await fetch("/api/reset", { method: "POST" });
  say(res.ok ? "Baseline restored: everything off." : "Reset failed.");
});

document.getElementById("demo-btn").addEventListener("click", async () => {
  say("Loading the demo room photo…");
  const res = await fetch("/api/photos/demo", { method: "POST" });
  if (!res.ok) { say(`Demo photo failed: ${res.status}`); return; }
  await usePhoto(await res.json());
});

photoInput.addEventListener("change", async () => {
  const file = photoInput.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  say("Uploading and auto-segmenting…");
  const res = await fetch("/api/photos", { method: "POST", body: form });
  if (!res.ok) { say(`Upload failed: ${res.status}`); return; }
  await usePhoto(await res.json());
});

async function usePhoto(body) {
  photoId = body.photo_id;
  photoEl.src = `/api/photos/${photoId}/image`;
  photoEl.hidden = false;
  document.getElementById("photo-empty").classList.add("gone");
  if (body.reused) {
    say(`Photo ${photoId} already known — loaded its regions directly.`);
  } else {
    const hits = (body.auto_segment || []).filter((a) => a.regions.length > 0);
    const missed = (body.auto_segment || []).filter((a) => a.regions.length === 0);
    say(`Photo ${photoId} segmented: ${hits.length} phrase(s) hit` +
      (missed.length ? `, missed: ${missed.map((a) => a.phrase).join(", ")} — draw those manually.` : "."));
  }
  await refreshGraph();
  await refreshProposals();
}

segmentBtn.addEventListener("click", async () => {
  if (!photoId) { say("Upload a photo first."); return; }
  const phrase = phraseInput.value.trim();
  if (!phrase) { say("Type a concept phrase first."); return; }
  say(`Segmenting "${phrase}"…`);
  const res = await fetch(`/api/photos/${photoId}/segment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phrase }),
  });
  const body = await res.json();
  if (!res.ok) {
    say(`SAM missed (${body.detail || res.status}). Draw the region manually instead.`);
    return;
  }
  if (body.regions.length === 0) {
    say(body.note || "No match. Draw the region manually instead.");
    return;
  }
  const matched = body.matched_phrase && body.matched_phrase !== phrase
    ? ` (matched as "${body.matched_phrase}")` : "";
  say(`"${phrase}"${matched}: ${body.regions.length} region(s) in ${body.latency_ms} ms.`);
  await refreshGraph();
});

function photoCoords(ev) {
  const rect = photoEl.getBoundingClientRect();
  return {
    x: Math.min(Math.max((ev.clientX - rect.left) / rect.width, 0), 1),
    y: Math.min(Math.max((ev.clientY - rect.top) / rect.height, 0), 1),
  };
}

drawBtn.addEventListener("click", () => {
  if (!photoId) { say("Upload a photo first."); return; }
  drawing = !drawing;
  drawBtn.textContent = drawing ? "Cancel draw" : "Draw region";
  drawBtn.classList.toggle("active", drawing);
  document.body.classList.toggle("drawing", drawing);
  say(drawing ? "Drag on the photo to draw the fallback region." : "Draw cancelled.");
});

const photoWrap = document.getElementById("photo-wrap");
photoWrap.addEventListener("pointerdown", (ev) => {
  if (!drawing) return;
  drawStart = photoCoords(ev);
});
photoWrap.addEventListener("pointerup", async (ev) => {
  if (!drawing || !drawStart) return;
  const end = photoCoords(ev);
  const x = Math.min(drawStart.x, end.x);
  const y = Math.min(drawStart.y, end.y);
  const w = Math.abs(end.x - drawStart.x);
  const h = Math.abs(end.y - drawStart.y);
  drawing = false;
  drawBtn.textContent = "Draw region";
  drawBtn.classList.remove("active");
  document.body.classList.remove("drawing");
  if (w < 0.01 || h < 0.01) { say("Box too small, ignored."); return; }
  const label = phraseInput.value.trim() || "region";
  const res = await fetch(`/api/photos/${photoId}/regions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, x, y, w, h }),
  });
  if (!res.ok) { say(`Manual region rejected: ${res.status}`); return; }
  const body = await res.json();
  say(`Manual region saved as ${body.object_id}.`);
  await refreshGraph();
});

load().then(connect);
