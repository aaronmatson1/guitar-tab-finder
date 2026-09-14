/* tabfinder web UI. Vanilla JS, no build step, no CDN - the whole point is
   that this runs locally with nothing else installed. */

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const statusBox = $("status");
const errorBox = $("error");
const results = $("results");

function setStatus(message) {
  if (!message) { statusBox.hidden = true; return; }
  statusBox.replaceChildren(el("div", "spinner"), el("span", null, message));
  statusBox.hidden = false;
}

function setError(message) {
  if (!message) { errorBox.hidden = true; return; }
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function busy(isBusy) {
  $("go").disabled = isBusy;
}

function options() {
  return {
    tuning: $("tuning").value,
    capo: $("capo").value || 0,
    solo: $("solo").checked,
    melody: $("melody").checked,
    allow_download: $("allow_download").checked,
  };
}

/* ---------- chord diagrams, drawn as SVG ---------- */

const DIAGRAM = { rows: 5, cellW: 15, cellH: 17, padX: 11, padY: 20 };

function chordDiagram(shape, strings) {
  const frets = shape.frets;
  const played = frets.filter((f) => f !== null && f > 0);
  const lowest = played.length ? Math.min(...played) : 1;
  const highest = played.length ? Math.max(...played) : 1;
  // Shapes near the nut are drawn against it; higher ones get a fret number.
  const atNut = !played.length || highest <= DIAGRAM.rows;
  const firstFret = atNut ? 1 : lowest;

  const n = frets.length;
  const width = DIAGRAM.padX * 2 + (n - 1) * DIAGRAM.cellW;
  const height = DIAGRAM.padY + DIAGRAM.rows * DIAGRAM.cellH + 16;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${shape.chord}, ${shape.text}`);

  const draw = (tag, attrs, text) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    svg.appendChild(node);
    return node;
  };

  const x = (i) => DIAGRAM.padX + i * DIAGRAM.cellW;
  const y = (row) => DIAGRAM.padY + row * DIAGRAM.cellH;
  const line = "var(--line)";
  const ink = "var(--text)";
  const dim = "var(--dim)";

  // Nut, or a plain fret wire when the shape sits up the neck.
  draw("line", {
    x1: x(0), y1: y(0), x2: x(n - 1), y2: y(0),
    stroke: atNut ? ink : line, "stroke-width": atNut ? 3.5 : 1.2,
  });
  for (let row = 1; row <= DIAGRAM.rows; row++) {
    draw("line", { x1: x(0), y1: y(row), x2: x(n - 1), y2: y(row), stroke: line, "stroke-width": 1 });
  }
  for (let i = 0; i < n; i++) {
    draw("line", { x1: x(i), y1: y(0), x2: x(i), y2: y(DIAGRAM.rows), stroke: line, "stroke-width": 1 });
  }

  if (!atNut) {
    draw("text", {
      x: x(n - 1) + 5, y: y(0) + DIAGRAM.cellH * 0.75, fill: dim,
      "font-size": 9, "font-family": "var(--mono)",
    }, `${firstFret}fr`);
  }

  // A barre is one bar across the strings it covers.
  if (shape.barre !== null && shape.barre !== undefined) {
    const covered = frets
      .map((f, i) => (f === shape.barre ? i : -1))
      .filter((i) => i >= 0);
    if (covered.length > 1) {
      const row = shape.barre - firstFret;
      draw("rect", {
        x: x(Math.min(...covered)) - 5, y: y(row) + DIAGRAM.cellH / 2 - 5,
        width: x(Math.max(...covered)) - x(Math.min(...covered)) + 10, height: 10,
        rx: 5, fill: ink, opacity: 0.85,
      });
    }
  }

  frets.forEach((fret, i) => {
    if (fret === null) {
      draw("text", { x: x(i), y: DIAGRAM.padY - 6, fill: dim, "font-size": 10,
                     "text-anchor": "middle" }, "×");
      return;
    }
    if (fret === 0 || fret < firstFret) {
      draw("circle", { cx: x(i), cy: DIAGRAM.padY - 10, r: 3.4, fill: "none",
                       stroke: dim, "stroke-width": 1.3 });
      return;
    }
    const row = fret - firstFret;
    if (row < 0 || row >= DIAGRAM.rows) return;
    draw("circle", { cx: x(i), cy: y(row) + DIAGRAM.cellH / 2, r: 5.2, fill: ink });
  });

  strings.forEach((name, i) => {
    draw("text", {
      x: x(i), y: height - 3, fill: dim, "font-size": 9,
      "text-anchor": "middle", "font-family": "var(--mono)",
    }, name);
  });

  return svg;
}

function diagramCard(shape, strings) {
  const wrap = el("div", "diagram");
  wrap.appendChild(el("div", "name", shape.chord));
  wrap.appendChild(chordDiagram(shape, strings));
  wrap.appendChild(el("div", "meta", shape.text));
  return wrap;
}

/* ---------- rendering results ---------- */

function card(title) {
  const node = el("section", "card");
  if (title) node.appendChild(el("h2", null, title));
  return node;
}

function renderSearch(data) {
  results.replaceChildren();
  results.hidden = false;

  if (data.track) {
    const found = card("Link");
    found.appendChild(el("p", "headline", data.track.display));
    found.appendChild(el("p", "subtle", `identified from the ${data.track.provider} link`));
    const actions = el("div", "actions");
    const analyse = el("button", "primary", "Work out the chords from the audio");
    analyse.onclick = () => analyzeLink($("query").value.trim());
    actions.appendChild(analyse);
    found.appendChild(actions);
    results.appendChild(found);
  }

  const hits = card(data.results.length ? "Published tabs" : "No published tabs found");
  if (data.results.length) {
    const list = el("ol", "hits");
    for (const hit of data.results) {
      const item = el("li");
      const link = el("a", null, `${hit.artist} — ${hit.title}`);
      link.href = hit.url;
      link.target = "_blank";
      link.rel = "noopener";
      item.appendChild(link);
      const bits = [hit.source, hit.kind];
      if (hit.rating) bits.push(`${hit.rating.toFixed(1)}★${hit.votes ? ` (${hit.votes})` : ""}`);
      item.appendChild(el("div", "meta", bits.join(" · ")));
      list.appendChild(item);
    }
    hits.appendChild(list);
  } else {
    hits.appendChild(el("p", "subtle",
      "Nobody has published a tab for this — which is exactly what the analyser is for. " +
      "Paste a link to the song, or drop an audio file above."));
  }

  if (data.links && data.links.length) {
    hits.appendChild(el("h3", null, "Search these yourself"));
    const row = el("div", "link-row");
    for (const link of data.links) {
      const anchor = el("a", null, link.source);
      anchor.href = link.url;
      anchor.target = "_blank";
      anchor.rel = "noopener";
      row.appendChild(anchor);
    }
    hits.appendChild(row);
  }

  if (data.errors && Object.keys(data.errors).length) {
    const note = el("div", "note-banner");
    note.textContent = "Some sources did not answer: " + Object.keys(data.errors).join(", ");
    hits.appendChild(note);
  }
  results.appendChild(hits);
}

function renderAnalysis(data) {
  results.replaceChildren();
  results.hidden = false;

  // --- the summary ---
  const summary = card(null);
  summary.appendChild(el("p", "headline", data.title || "Analysis"));
  const facts = el("div", "facts");
  const fact = (label, value) => {
    const box = el("div", "fact");
    box.appendChild(el("div", "label", label));
    box.appendChild(el("div", "value", value));
    return box;
  };
  facts.appendChild(fact("Key", data.key.name));
  facts.appendChild(fact("Confidence", `${Math.round(data.key.confidence * 100)}%`));
  facts.appendChild(fact("Tempo", `${Math.round(data.tempo)} BPM`));
  if (data.capo) {
    facts.appendChild(fact("Capo", data.capo.fret === 0
      ? "not needed" : `fret ${data.capo.fret} → ${data.capo.shape_key} shapes`));
  }
  summary.appendChild(facts);

  summary.appendChild(el("p", "subtle",
    `Scale: ${data.key.scale.join(" ")}   ·   Pentatonic for soloing: ${data.key.pentatonic.join(" ")}`));

  if (data.key.alternatives && data.key.alternatives.length && data.key.confidence < 0.6) {
    const note = el("div", "note-banner");
    note.textContent = "This key is genuinely ambiguous. Also possible: " +
      data.key.alternatives.map((a) => a.name).join(", ") + ".";
    summary.appendChild(note);
  }
  if (data.partial) {
    const note = el("div", "note-banner");
    note.textContent = "Only a short preview clip was analysed" +
      (data.source_label ? ` (${data.source_label})` : "") +
      ", so the key and main progression should hold but later sections are not covered.";
    summary.appendChild(note);
  }
  results.appendChild(summary);

  // --- progression ---
  if (data.progression && data.progression.loop.length) {
    const prog = card("Progression");
    const row = el("div", "progression");
    data.progression.loop.forEach((symbol, i) => {
      const step = el("div", "chord-step");
      step.appendChild(el("div", "sym", symbol));
      step.appendChild(el("div", "num", data.progression.numerals[i] || ""));
      row.appendChild(step);
    });
    prog.appendChild(row);
    if (data.progression.name) {
      prog.appendChild(el("p", "subtle", `That is ${data.progression.name}.`));
    }
    results.appendChild(prog);
  }

  // --- shapes ---
  if (data.shapes && data.shapes.length) {
    const shapes = card("Chord shapes");
    const row = el("div", "diagrams");
    for (const shape of data.shapes) row.appendChild(diagramCard(shape, data.strings));
    shapes.appendChild(row);
    results.appendChild(shapes);
  }

  // --- rhythm tab ---
  if (data.rhythm_tab) {
    const tab = card("Rhythm tab");
    tab.appendChild(el("p", "subtle", "One bar of downstrokes per chord."));
    tab.appendChild(el("pre", "tab", data.rhythm_tab));
    results.appendChild(tab);
  }

  // --- solo ---
  if (data.solo_tab) {
    const solo = card("Guitar solo");
    const head = el("p", "subtle",
      `${data.solo_tab.section} · ${data.solo_tab.notes} notes · ${data.solo_tab.position}` +
      (data.solo_tab.separated ? " · lead separated with demucs" : ""));
    solo.appendChild(head);
    solo.appendChild(el("pre", "tab", data.solo_tab.tab));
    if (data.solo_tab.legend.length) {
      const legend = el("ul", "legend");
      for (const line of data.solo_tab.legend) {
        const item = el("li");
        const [symbol, ...rest] = line.split(/\s+/);
        item.appendChild(el("code", null, symbol));
        item.appendChild(document.createTextNode(rest.join(" ")));
        legend.appendChild(item);
      }
      solo.appendChild(legend);
    }
    const note = el("div", "note-banner");
    note.textContent = "Solo transcription follows the loudest melodic line, which during an " +
      "instrumental break is the solo but elsewhere may be the vocal. Bends, slides and vibrato " +
      "read well; hammer-ons and pull-offs are deliberately under-reported.";
    solo.appendChild(note);
    results.appendChild(solo);
  } else if (data.solo_candidates && data.solo_candidates.length) {
    const solo = card("Guitar solo");
    solo.appendChild(el("p", "subtle",
      "No solo was transcribed, but these sections looked like a lead line: " +
      data.solo_candidates.map((c) => `${fmtTime(c.start)}–${fmtTime(c.end)}`).join(", ")));
    results.appendChild(solo);
  }

  // --- timeline ---
  if (data.chords && data.chords.length) {
    const timeline = card("Chord timeline");
    const table = el("table", "timeline");
    let flagged = false;
    for (const segment of data.chords) {
      const row = el("tr");
      row.appendChild(el("td", "time", fmtTime(segment.start)));
      row.appendChild(el("td", "sym", segment.chord));
      const bars = `${segment.bars.toFixed(0)} bar${segment.bars >= 2 ? "s" : ""}`;
      if (segment.monophonic) {
        // One note at a time was sounding, so this label describes the line
        // being played rather than any chord behind it.
        flagged = true;
        row.classList.add("mono");
        row.appendChild(el("td", "bars", `${bars} \u00b7 single notes`));
      } else {
        row.appendChild(el("td", "bars", bars));
      }
      table.appendChild(row);
    }
    timeline.appendChild(table);
    if (flagged) {
      timeline.appendChild(el("p", "subtle",
        "Rows marked \u201csingle notes\u201d had only one note sounding \u2014 a solo or an " +
        "unaccompanied line \u2014 so the chord named there describes the notes played, " +
        "not the harmony. Those rows are left out of the progression above."));
    }
    results.appendChild(timeline);
  }
}

function fmtTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/* ---------- talking to the server ---------- */

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({ error: "The server sent something unreadable." }));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

async function pollJob(job) {
  // Analysis takes tens of seconds; poll steadily rather than holding a request.
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 900));
    const response = await fetch(`/api/jobs/${job.id}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Lost track of that job.");
    if (data.progress) setStatus(`${data.progress} (${data.elapsed}s)`);
    if (data.status === "done") return data.result;
    if (data.status === "error") throw new Error(data.error);
  }
}

async function search() {
  const query = $("query").value.trim();
  if (!query) { setError("Type a song name, or paste a link."); return; }
  setError(null);
  busy(true);
  setStatus("Searching for a published tab...");
  try {
    const data = await postJSON("/api/search", { query });
    setStatus(null);
    renderSearch(data);
  } catch (err) {
    setStatus(null);
    setError(err.message);
  } finally {
    busy(false);
  }
}

async function analyzeLink(source) {
  setError(null);
  busy(true);
  setStatus("Starting...");
  try {
    const job = await postJSON("/api/analyze", { source, ...options() });
    const data = await pollJob(job);
    setStatus(null);
    renderAnalysis(data);
  } catch (err) {
    setStatus(null);
    setError(err.message);
  } finally {
    busy(false);
  }
}

async function analyzeFile(file) {
  setError(null);
  busy(true);
  setStatus(`Uploading ${file.name}...`);
  const form = new FormData();
  form.append("audio", file);
  for (const [key, value] of Object.entries(options())) form.append(key, value);
  try {
    const response = await fetch("/api/upload", { method: "POST", body: form });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "Upload failed.");
    const data = await pollJob(job);
    setStatus(null);
    renderAnalysis(data);
  } catch (err) {
    setStatus(null);
    setError(err.message);
  } finally {
    busy(false);
  }
}

/* ---------- wiring ---------- */

$("go").addEventListener("click", search);
$("query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") search();
});
$("file").addEventListener("change", (event) => {
  if (event.target.files.length) analyzeFile(event.target.files[0]);
});

const drop = $("drop");
["dragenter", "dragover"].forEach((name) =>
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("over");
  }));
["dragleave", "drop"].forEach((name) =>
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("over");
  }));
drop.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (file) analyzeFile(file);
});
