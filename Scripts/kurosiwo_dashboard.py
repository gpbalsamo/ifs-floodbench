#!/usr/bin/env python3
from pathlib import Path

OUTDIR = Path("kurosiwo-dashboard")
DATA_DIR = OUTDIR / "dashboard_data"
PNG_DIR = DATA_DIR / "floods_png"

OUTDIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
PNG_DIR.mkdir(exist_ok=True)

index_html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>KuroSiwo Flood Events Dashboard</title>
  <link rel="stylesheet" href="style.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
</head>
<body>
  <header>
    <h1>KuroSiwo Flood Events Dashboard</h1>
    <p>Clickable flood events from the KuroSiwo catalogue</p>
  </header>

  <main>
    <div id="map"></div>

    <aside id="panel">
      <h2 id="event-title">Select a flood event</h2>
      <div id="event-info"></div>
      <img id="event-image" src="" alt="Flood event image" />
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

#event-image {
  width: 100%;
  height: auto;
  max-height: 80vh;
  object-fit: contain;
  border: 1px solid #ccc;
  display: none;
}

.event-popup {
  font-size: 13px;
}
"""

app_js = """const map = L.map("map").setView([20, 0], 2);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 8,
  attribution: "© OpenStreetMap contributors"
}).addTo(map);

function continentColor(continent) {
  const colors = {
    Europe: "#1f77b4",
    Asia: "#ff7f0e",
    Africa: "#2ca02c",
    "North America": "#d62728",
    "South America": "#9467bd",
    Oceania: "#8c564b"
  };
  return colors[continent] || "#555";
}

Papa.parse("dashboard_data/KuroSiwo_events.csv", {
  download: true,
  header: true,
  dynamicTyping: true,

  complete: function(results) {
    const data = results.data.filter(d => d.flood_case);

    data.forEach(event => {
      const bounds = [
        [event.lat_min, event.lon_min],
        [event.lat_max, event.lon_max]
      ];

      const color = continentColor(event.continent);

      const rect = L.rectangle(bounds, {
        color: color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.18
      }).addTo(map);

      const hoverText = `
        <div class="event-popup">
          <b>${event.flood_case}</b><br>
          ${event.country || "Unknown"} (${event.continent || "Unknown"})<br>
          Date: ${event.date_of_max_flood_extent}<br>
          BBox: ${event.lat_min}, ${event.lon_min}, ${event.lat_max}, ${event.lon_max}
        </div>
      `;

      rect.bindTooltip(hoverText, {
        sticky: true,
        direction: "top"
      });

      rect.on("click", () => {
        document.getElementById("event-title").textContent = event.flood_case;

        document.getElementById("event-info").innerHTML = `
          <b>Country:</b> ${event.country || "Unknown"}<br>
          <b>Continent:</b> ${event.continent || "Unknown"}<br>
          <b>Date of max flood extent:</b> ${event.date_of_max_flood_extent}<br>
          <b>Latitude range:</b> ${event.lat_min} to ${event.lat_max}<br>
          <b>Longitude range:</b> ${event.lon_min} to ${event.lon_max}
        `;

        const img = document.getElementById("event-image");
        img.src = `dashboard_data/floods_png/${event.flood_case}.png`;
        img.style.display = "block";

        map.fitBounds(bounds);
      });
    });
  }
});
"""

(OUTDIR / "index.html").write_text(index_html)
(OUTDIR / "style.css").write_text(style_css)
(OUTDIR / "app.js").write_text(app_js)

print(f"Dashboard created in: {OUTDIR}")
print(f"Copy CSV and PNGs to the dashboard location")
print(f"cp KuroSiwo_events.csv {DATA_DIR / 'KuroSiwo_events.csv'}")
print(f"cp kurosiwo_png/*.png {PNG_DIR}/.")
print(f"rm -rf kurosiwo_png")
print()
print("Then run:")
print(f"  cd {OUTDIR}")
print("  python3 -m http.server 8000")
