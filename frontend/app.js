// Day 1: render HA states, live-update ONLY from WebSocket state_changed
// events relayed by the backend. No optimistic UI.
const statusEl = document.getElementById("status");
const listEl = document.getElementById("entities");
const states = new Map();

function render() {
  listEl.innerHTML = "";
  for (const [id, st] of states) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = id;
    const dot = document.createElement("span");
    dot.className = "dot" + (st === "on" ? " on" : "");
    dot.title = st;
    li.appendChild(name);
    li.appendChild(dot);
    listEl.appendChild(li);
  }
}

async function load() {
  const res = await fetch("/api/entities");
  const entities = await res.json();
  for (const e of entities) states.set(e.entity_id, e.state);
  render();
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
const uploadBtn = document.getElementById("upload-btn");
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

function renderRegions(regions) {
  regionsEl.innerHTML = "";
  regionList.innerHTML = "";
  for (const r of regions) {
    const box = document.createElement("div");
    box.className = "region" + (r.source === "manual" ? " manual" : "");
    box.style.left = `${r.x * 100}%`;
    box.style.top = `${r.y * 100}%`;
    box.style.width = `${r.w * 100}%`;
    box.style.height = `${r.h * 100}%`;
    box.title = `${r.object_id} (${r.source})`;
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = r.object_id;
    box.appendChild(tag);
    box.addEventListener("click", (ev) => {
      if (drawing) return;
      ev.stopPropagation();
      for (const el of regionsEl.children) el.classList.remove("selected");
      box.classList.add("selected");
      say(`Selected ${r.object_id} — binding arrives Day 3.`);
    });
    regionsEl.appendChild(box);
    const li = document.createElement("li");
    li.className = r.source;
    li.textContent = `${r.object_id} · ${r.phrase}`;
    li.title = `source: ${r.source}`;
    regionList.appendChild(li);
  }
}

async function refreshGraph() {
  if (!photoId) return;
  const res = await fetch(`/api/photos/${photoId}/graph`);
  const graph = await res.json();
  renderRegions(graph.regions);
}

uploadBtn.addEventListener("click", async () => {
  const file = photoInput.files[0];
  if (!file) { say("Choose a JPEG or PNG first."); return; }
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/photos", { method: "POST", body: form });
  if (!res.ok) { say(`Upload failed: ${res.status}`); return; }
  const body = await res.json();
  photoId = body.photo_id;
  photoEl.src = `/api/photos/${photoId}/image`;
  photoEl.hidden = false;
  document.getElementById("photo-empty").classList.add("gone");
  say(`Photo ${photoId} uploaded (${body.width}x${body.height}). Segment a phrase or draw a region.`);
  await refreshGraph();
});

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
