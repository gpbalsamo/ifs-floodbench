#!/usr/bin/env python3
"""
dashboard_shell.py

Shared HTML/CSS/JS generator for this project's flood-event dashboards
(kurosiwo_dashboard.py, modis2016_dashboard.py). Both dashboards use the
identical Leaflet + PapaParse UI -- event list (sorted by peak date),
map with click-to-zoom, per-source CSI/FAR/HR score tables, threshold
selector, and toggleable layers -- differing only in title/subtitle,
which catalogue CSV to load, and (optionally) a small cross-link to a
sibling dashboard. Keeping the shell in one place means a UI change
(like the event list or score tables) only needs to be made once.

Not a CLI; import write_dashboard_shell() from a per-dashboard script
that sets OUTDIR/DATA_DIR/etc. and prints its own pipeline instructions.
"""
from pathlib import Path


def write_dashboard_shell(outdir, title, subtitle, events_csv,
                           reference_figures=True, nav_links=None):
    """
    outdir:            dashboard output directory (Path or str)
    title:              <title> / <h1> text
    subtitle:           header <p> text
    events_csv:          catalogue CSV filename, relative to dashboard_data/
    reference_figures:   whether to include the "Reference figure" <details>
                         section (KuroSiwo has one per event; the MODIS-only
                         post-2016 dashboard does not)
    nav_links:           optional list of (label, href) rendered as a small
                         nav in the header, e.g. a link to a sibling dashboard
    """
    outdir = Path(outdir)
    data_dir = outdir / "dashboard_data"
    (data_dir / "floods_png").mkdir(parents=True, exist_ok=True)
    (data_dir / "layers").mkdir(parents=True, exist_ok=True)

    nav_html = ""
    if nav_links:
        links = " &middot; ".join(f'<a href="{href}">{label}</a>' for label, href in nav_links)
        nav_html = f'\n    <nav id="dashboard-nav">{links}</nav>'

    reference_html = """
      <details id="reference-figure">
        <summary>Reference figure (discharge + flood fraction)</summary>
        <img id="event-image" src="" alt="Flood event reference figure" />
      </details>""" if reference_figures else ""

    index_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <link rel="stylesheet" href="style.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p>{subtitle}</p>{nav_html}
  </header>

  <main>
    <div id="map"></div>

    <aside id="panel">
      <div id="event-list-control">
        <h3>Events <span id="event-count" class="muted"></span></h3>
        <p class="muted">Sorted by peak flood date, newest first. Click an event to zoom the map to it.</p>
        <div id="event-list"></div>
      </div>

      <h2 id="event-title">Select a flood event</h2>
      <div id="event-info"></div>

      <div id="score-control">
        <h3>Benchmark scores</h3>
        <p class="muted">CSI / FAR / HR vs. each observation source, at every flood-fraction threshold.</p>
        <div id="score-tables"></div>
      </div>

      <div id="threshold-control">
        <h3>Flood threshold</h3>
        <p class="muted">Minimum flooded fraction of a ~1 arcmin cell to count as "flooded", applied the same way to the model and all observations.</p>
        <div id="threshold-rows"></div>
      </div>

      <div id="layer-control">
        <h3>Layers</h3>
        <div id="layer-rows"></div>
        <p id="layer-empty" class="muted">No model/observation layers available for this event.</p>
        <p class="muted"><span style="display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px;vertical-align:-1px;background:rgba(120,120,120,0.6);"></span>Gray = no observation, VIIRS/MODIS (optical sensors blocked by cloud cover &mdash; irregular, can clear up on a later date). Genuinely unknown, not "confirmed not flooded" &mdash; excluded from that layer's CSI/FAR/HR scores.</p>
        <p class="muted"><span style="display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px;vertical-align:-1px;background:rgba(90,110,150,0.6);"></span>Slate blue = no observation, GFM (radar sees through cloud, but the satellite swath doesn't cover this area &mdash; a fixed strip, not weather-related). Also excluded from scoring.</p>
        <p class="muted"><span style="display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:6px;vertical-align:-1px;background-color:rgba(0,172,193,0.35);background-image:repeating-linear-gradient(45deg, rgba(0,172,193,0.9) 0, rgba(0,172,193,0.9) 2px, transparent 2px, transparent 6px);"></span>Hatched teal = known lake/river/reservoir (Reference water layer). This is a fixed geographic fact, not uncertainty &mdash; CaMa-Flood's flood fraction includes this extent, so it's excluded from scoring so it isn't counted as a false alarm.</p>
      </div>{reference_html}
    </aside>
  </main>

  <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/papaparse@5.4.1/papaparse.min.js"></script>
  <script src="app.js"></script>
</body>
</html>
"""

    style_css = """body {
  margin: 0;
  font-family: Arial, sans-serif;
  background: #f7f7f7;
}

header {
  padding: 12px 20px;
  background: #1f2937;
  color: white;
}

header h1 {
  margin: 0;
  font-size: 22px;
}

header p {
  margin: 4px 0 0;
  font-size: 14px;
}

#dashboard-nav {
  margin-top: 6px;
  font-size: 13px;
}

#dashboard-nav a {
  color: #93c5fd;
}

main {
  display: grid;
  grid-template-columns: 1fr 1fr;
  height: calc(100vh - 75px);
}

#map {
  height: 100%;
}

#panel {
  padding: 16px;
  overflow-y: auto;
  background: white;
  border-left: 1px solid #ccc;
}

#event-title {
  margin-top: 0;
}

#event-info {
  font-size: 14px;
  line-height: 1.5;
  margin-bottom: 12px;
}

#threshold-control,
#layer-control,
#event-list-control,
#score-control {
  margin: 16px 0;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  background: #fafafa;
}

#threshold-control h3,
#layer-control h3,
#event-list-control h3,
#score-control h3 {
  margin: 0 0 8px;
  font-size: 14px;
}

#threshold-control p.muted,
#event-list-control p.muted,
#score-control p.muted {
  margin: 0 0 8px;
}

#event-count {
  font-weight: normal;
  font-size: 12px;
}

#event-list {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #e5e5e5;
  border-radius: 4px;
  background: white;
}

.event-list-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  font-size: 12px;
  cursor: pointer;
  border-bottom: 1px solid #eee;
}

.event-list-item:last-child {
  border-bottom: none;
}

.event-list-item:hover {
  background: #f0f4ff;
}

.event-list-item.active {
  background: #1f2937;
  color: white;
}

.event-list-item .event-list-name {
  font-weight: bold;
  white-space: nowrap;
}

.event-list-item .event-list-place {
  color: #888;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  text-align: right;
}

.event-list-item.active .event-list-place {
  color: #cbd5e1;
}

.event-list-item .event-list-date {
  color: #666;
  white-space: nowrap;
}

.event-list-item.active .event-list-date {
  color: #cbd5e1;
}

.score-block {
  margin-bottom: 12px;
}

.score-block:last-child {
  margin-bottom: 0;
}

.score-block-title {
  display: flex;
  align-items: center;
  font-size: 13px;
  font-weight: bold;
  margin-bottom: 4px;
}

.score-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.score-table th,
.score-table td {
  border: 1px solid #e5e5e5;
  padding: 3px 6px;
  text-align: center;
}

.score-table thead th {
  background: #eef1f5;
  font-weight: normal;
  color: #555;
}

.score-table tbody th {
  text-align: left;
  color: #555;
  font-weight: normal;
  background: #fafafa;
}

#threshold-rows {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.threshold-btn {
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid #bbb;
  border-radius: 999px;
  background: white;
  cursor: pointer;
}

.threshold-btn.active {
  background: #1f2937;
  color: white;
  border-color: #1f2937;
}

.layer-row {
  padding: 4px 0;
  border-bottom: 1px solid #eee;
}

.layer-row:last-child {
  border-bottom: none;
}

.layer-row-main {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.layer-row .swatch {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  display: inline-block;
  margin-right: 6px;
}

.layer-row .layer-label {
  display: flex;
  align-items: center;
}

.layer-row .layer-date {
  font-size: 11px;
  color: #666;
}

.layer-row input[type="range"] {
  width: 70px;
}

.muted {
  color: #888;
  font-size: 13px;
}

#reference-figure {
  margin-top: 8px;
}

#reference-figure summary {
  cursor: pointer;
  font-size: 13px;
  color: #1f2937;
}

#event-image {
  width: 100%;
  height: auto;
  max-height: 70vh;
  object-fit: contain;
  border: 1px solid #ccc;
  margin-top: 8px;
}

.event-popup {
  font-size: 13px;
}
"""

    app_js = f"""const map = L.map("map").setView([20, 0], 2);

L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
  maxZoom: 15,
  attribution: "© OpenStreetMap contributors"
}}).addTo(map);

function continentColor(continent) {{
  const colors = {{
    Europe: "#1f77b4",
    Asia: "#ff7f0e",
    Africa: "#2ca02c",
    "North America": "#d62728",
    "South America": "#9467bd",
    Oceania: "#8c564b"
  }};
  return colors[continent] || "#555";
}}

// Populated once layers.json has loaded.
let LAYERS_META = {{}};
let EVENT_LAYERS = {{}};
let THRESHOLDS = [];
let currentThreshold = null;

// One Leaflet imageOverlay per layer key, reused across event selections.
const activeOverlays = {{}};
// Per-layer UI state, keyed by layer id (e.g. "viirs").
const layerState = {{}};

let currentEvent = null;
// flood_case -> DOM node in the event list, for active-row highlighting.
const eventListRows = {{}};

function clearOverlays() {{
  Object.values(activeOverlays).forEach(layer => map.removeLayer(layer));
  for (const key in activeOverlays) delete activeOverlays[key];
}}

function renderThresholdControls() {{
  const container = document.getElementById("threshold-rows");
  container.innerHTML = "";

  THRESHOLDS.forEach(t => {{
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "threshold-btn" + (t.key === currentThreshold ? " active" : "");
    btn.textContent = t.label;
    btn.addEventListener("click", () => {{
      currentThreshold = t.key;
      renderThresholdControls();
      updateOverlaysForCurrentEvent();
    }});
    container.appendChild(btn);
  }});
}}

function renderLayerControls() {{
  const container = document.getElementById("layer-rows");
  container.innerHTML = "";

  const keys = Object.keys(LAYERS_META);
  keys.forEach(key => {{
    if (!(key in layerState)) {{
      // Reference water is a diagnostic overlay (lakes/rivers, not a
      // flood/model layer), so keep it off by default to avoid clutter.
      layerState[key] = {{ visible: key !== "reference_water", opacity: 0.85 }};
    }}

    const meta = LAYERS_META[key];
    const row = document.createElement("div");
    row.className = "layer-row";

    const main = document.createElement("div");
    main.className = "layer-row-main";

    const label = document.createElement("label");
    label.className = "layer-label";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = layerState[key].visible;
    checkbox.addEventListener("change", () => {{
      layerState[key].visible = checkbox.checked;
      updateOverlaysForCurrentEvent();
    }});

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    if (key === "reference_water") {{
      // Matches the hatched fill used for this layer on the map, so the
      // swatch doesn't look like just another flat-colour flood layer.
      swatch.style.backgroundColor = "rgba(0,172,193,0.35)";
      swatch.style.backgroundImage =
        "repeating-linear-gradient(45deg, rgba(0,172,193,0.9) 0, rgba(0,172,193,0.9) 2px, transparent 2px, transparent 6px)";
    }} else {{
      swatch.style.background = meta.color;
    }}

    label.appendChild(checkbox);
    label.appendChild(swatch);
    label.appendChild(document.createTextNode(meta.label));

    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0.1";
    slider.max = "1";
    slider.step = "0.05";
    slider.value = layerState[key].opacity;
    slider.addEventListener("input", () => {{
      layerState[key].opacity = parseFloat(slider.value);
      updateOverlaysForCurrentEvent();
    }});

    const dateSpan = document.createElement("span");
    dateSpan.className = "layer-date";
    dateSpan.id = `layer-date-${{key}}`;

    main.appendChild(label);
    main.appendChild(slider);
    main.appendChild(dateSpan);

    row.appendChild(main);
    container.appendChild(row);
  }});
}}

// One CSI/FAR/HR-by-threshold table per observation source (everything
// in LAYERS_META except the model layer itself), always showing all
// thresholds at once regardless of which one is selected for the map.
function renderScoreTables(layers) {{
  const container = document.getElementById("score-tables");
  container.innerHTML = "";

  const sourceKeys = Object.keys(LAYERS_META).filter(k => k !== "cama_flood");
  const fmt = v => (v === null || v === undefined ? "&ndash;" : v.toFixed(2));

  let anyScores = false;

  sourceKeys.forEach(key => {{
    const layer = layers[key];
    if (!layer || !layer.scores) return;
    anyScores = true;

    const meta = LAYERS_META[key];
    const block = document.createElement("div");
    block.className = "score-block";

    const title = document.createElement("div");
    title.className = "score-block-title";
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = meta.color;
    title.appendChild(swatch);
    title.appendChild(document.createTextNode(meta.label));
    block.appendChild(title);

    const rowsHtml = ["csi", "far", "hr"].map(metric => {{
      const cells = THRESHOLDS.map(t => {{
        const s = layer.scores[t.key];
        return `<td>${{s ? fmt(s[metric]) : "&ndash;"}}</td>`;
      }}).join("");
      return `<tr><th>${{metric.toUpperCase()}}</th>${{cells}}</tr>`;
    }}).join("");

    const headCells = THRESHOLDS.map(t => `<th>${{t.label}}</th>`).join("");

    block.insertAdjacentHTML("beforeend", `
      <table class="score-table">
        <thead><tr><th></th>${{headCells}}</tr></thead>
        <tbody>${{rowsHtml}}</tbody>
      </table>
    `);

    container.appendChild(block);
  }});

  if (!anyScores) {{
    container.innerHTML = '<p class="muted">No benchmark scores computed for this event yet.</p>';
  }}
}}

function updateOverlaysForCurrentEvent() {{
  clearOverlays();

  if (!currentEvent) return;

  const layers = EVENT_LAYERS[currentEvent] || {{}};
  const emptyMsg = document.getElementById("layer-empty");
  emptyMsg.style.display = Object.keys(layers).length ? "none" : "block";

  Object.keys(LAYERS_META).forEach(key => {{
    const dateSpan = document.getElementById(`layer-date-${{key}}`);
    const layer = layers[key];

    if (dateSpan) dateSpan.textContent = layer ? layer.date || "" : "";

    if (!layer || !layerState[key] || !layerState[key].visible) return;

    const pngPath = layer.png[currentThreshold] || Object.values(layer.png)[0];
    if (!pngPath) return;

    const bounds = layer.bounds; // [[south, west], [north, east]]
    const overlay = L.imageOverlay(`dashboard_data/${{pngPath}}`, bounds, {{
      opacity: layerState[key].opacity,
      interactive: false
    }});
    overlay.addTo(map);
    activeOverlays[key] = overlay;
  }});
}}

function selectEvent(event, bounds) {{
  currentEvent = event.flood_case;

  document.getElementById("event-title").textContent = event.flood_case;

  const riverLine = event.main_river_system
    ? `<b>Main river system:</b> ${{event.main_river_system}}<br>`
    : "";

  document.getElementById("event-info").innerHTML = `
    <b>Country:</b> ${{event.country || "Unknown"}}<br>
    <b>Continent:</b> ${{event.continent || "Unknown"}}<br>
    ${{riverLine}}
    <b>Date of max flood extent:</b> ${{event.date_of_max_flood_extent}}<br>
    <b>Latitude range:</b> ${{event.lat_min}} to ${{event.lat_max}}<br>
    <b>Longitude range:</b> ${{event.lon_min}} to ${{event.lon_max}}
  `;

  const img = document.getElementById("event-image");
  if (img) {{
    img.src = `dashboard_data/floods_png/${{event.flood_case}}.png`;
    img.onerror = () => {{ img.style.display = "none"; }};
    img.onload = () => {{ img.style.display = "block"; }};
  }}

  renderScoreTables(EVENT_LAYERS[currentEvent] || {{}});
  updateOverlaysForCurrentEvent();
  map.fitBounds(bounds);

  Object.values(eventListRows).forEach(row => row.classList.remove("active"));
  const activeRow = eventListRows[event.flood_case];
  if (activeRow) activeRow.classList.add("active");
}}

function renderEventList(events) {{
  const container = document.getElementById("event-list");
  const countLabel = document.getElementById("event-count");
  container.innerHTML = "";
  for (const key in eventListRows) delete eventListRows[key];

  const sorted = [...events].sort((a, b) => {{
    const da = new Date(a.date_of_max_flood_extent);
    const db = new Date(b.date_of_max_flood_extent);
    return db - da; // newest first
  }});

  countLabel.textContent = `(${{sorted.length}})`;

  sorted.forEach(event => {{
    const bounds = [
      [event.lat_min, event.lon_min],
      [event.lat_max, event.lon_max]
    ];

    const row = document.createElement("div");
    row.className = "event-list-item";

    const name = document.createElement("span");
    name.className = "event-list-name";
    name.textContent = event.flood_case;

    const place = document.createElement("span");
    place.className = "event-list-place";
    place.textContent = [event.country, event.continent].filter(Boolean).join(", ") || "Unknown";

    const date = document.createElement("span");
    date.className = "event-list-date";
    date.textContent = event.date_of_max_flood_extent;

    row.appendChild(name);
    row.appendChild(place);
    row.appendChild(date);

    row.addEventListener("click", () => selectEvent(event, bounds));

    container.appendChild(row);
    eventListRows[event.flood_case] = row;
  }});
}}

fetch("dashboard_data/layers.json")
  .then(r => (r.ok ? r.json() : {{ layers_meta: {{}}, thresholds: [], events: {{}} }}))
  .catch(() => ({{ layers_meta: {{}}, thresholds: [], events: {{}} }}))
  .then(manifest => {{
    LAYERS_META = manifest.layers_meta || {{}};
    EVENT_LAYERS = manifest.events || {{}};
    THRESHOLDS = manifest.thresholds || [];
    currentThreshold = manifest.default_threshold || (THRESHOLDS[0] && THRESHOLDS[0].key) || null;
    renderThresholdControls();
    renderLayerControls();

    Papa.parse("dashboard_data/{events_csv}", {{
      download: true,
      header: true,
      dynamicTyping: true,

      complete: function(results) {{
        const data = results.data.filter(d => d.flood_case);

        renderEventList(data);

        data.forEach(event => {{
          const bounds = [
            [event.lat_min, event.lon_min],
            [event.lat_max, event.lon_max]
          ];

          const color = continentColor(event.continent);

          const rect = L.rectangle(bounds, {{
            color: color,
            weight: 2,
            fillColor: color,
            fillOpacity: 0.12
          }}).addTo(map);

          const hoverText = `
            <div class="event-popup">
              <b>${{event.flood_case}}</b><br>
              ${{event.country || "Unknown"}} (${{event.continent || "Unknown"}})<br>
              Date: ${{event.date_of_max_flood_extent}}<br>
              BBox: ${{event.lat_min}}, ${{event.lon_min}}, ${{event.lat_max}}, ${{event.lon_max}}
            </div>
          `;

          rect.bindTooltip(hoverText, {{
            sticky: true,
            direction: "top"
          }});

          rect.on("click", () => selectEvent(event, bounds));
        }});
      }}
    }});
  }});
"""

    (outdir / "index.html").write_text(index_html)
    (outdir / "style.css").write_text(style_css)
    (outdir / "app.js").write_text(app_js)
