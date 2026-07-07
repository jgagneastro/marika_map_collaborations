from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import folium
import pandas as pd
from geopy.exc import GeocoderServiceError
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim


MONTREAL_CENTER = (45.5017, -73.5673)
QUEBEC_PROVINCE_CENTER = (52.9399, -71.2080)
WORLD_CENTER = (20.0, 0.0)
LABELED_TILE_LAYER = "CartoDB Positron"
NO_LABEL_TILE_LAYER = "CartoDB PositronNoLabels"

GLOBE_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Collaborations Globe</title>
  <style>
    html,
    body {
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: #050814;
      font-family: Arial, Helvetica, sans-serif;
    }

    #globe {
      position: fixed;
      inset: 0;
    }

    .scene-tooltip {
      pointer-events: none;
    }

    .hoverbox {
      max-width: 280px;
      padding: 8px 10px;
      border: 1px solid rgba(127, 29, 29, 0.25);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.96);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
      color: #111827;
      font-size: 13px;
      font-weight: 700;
      line-height: 1.25;
      white-space: normal;
    }
  </style>
</head>
<body>
  <div id="globe"></div>

  <script src="https://unpkg.com/three@0.160.0/build/three.min.js"></script>
  <script src="https://unpkg.com/globe.gl@2/dist/globe.gl.min.js"></script>
  <script src="https://unpkg.com/topojson-client@3"></script>
  <script src="https://unpkg.com/d3-geo@3"></script>
  <script>
    const COLLABORATION_POINTS = __POINTS_JSON__;
    const COUNTRY_ATLAS_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

    const container = document.getElementById("globe");
    const globe = Globe()(container);
    const pointGeometry = new THREE.SphereGeometry(0.9, 24, 24);
    const pointMaterial = new THREE.MeshStandardMaterial({
      color: 0xdc2626,
      emissive: 0x5f0909,
      emissiveIntensity: 0.26,
      roughness: 0.42,
      metalness: 0.05
    });

    function escapeHtml(value) {
      const element = document.createElement("div");
      element.textContent = value || "";
      return element.innerHTML;
    }

    function resizeGlobe() {
      globe.width(window.innerWidth);
      globe.height(window.innerHeight);
    }

    globe
      .backgroundColor("#050814")
      .globeImageUrl("https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg")
      .bumpImageUrl("https://unpkg.com/three-globe/example/img/earth-topology.png")
      .showAtmosphere(true)
      .atmosphereColor("#8fd3ff")
      .atmosphereAltitude(0.18)
      .pointLat("lat")
      .pointLng("lng")
      .pointAltitude("altitude")
      .pointLabel((point) => `<div class="hoverbox">${escapeHtml(point.name)}</div>`)
      .customThreeObject((point) => {
        const mesh = new THREE.Mesh(pointGeometry, pointMaterial.clone());
        mesh.userData = point;
        return mesh;
      })
      .customThreeObjectUpdate((object, point) => {
        const position = globe.getCoords(point.lat, point.lng, point.altitude);
        object.position.set(position.x, position.y, position.z);
      })
      .labelsData([])
      .labelLat("lat")
      .labelLng("lng")
      .labelText("name")
      .labelSize("size")
      .labelAltitude(0.012)
      .labelColor(() => "rgba(255, 255, 255, 0.84)")
      .labelResolution(2);

    globe.controls().enableDamping = true;
    globe.controls().dampingFactor = 0.08;
    globe.controls().autoRotate = true;
    globe.controls().autoRotateSpeed = 0.28;
    globe.pointOfView({ lat: 24, lng: -35, altitude: 2.15 }, 0);
    globe.pointsData(COLLABORATION_POINTS);

    const ambientLight = new THREE.AmbientLight(0xffffff, 1.15);
    globe.scene().add(ambientLight);

    window.addEventListener("resize", resizeGlobe);
    resizeGlobe();

    fetch(COUNTRY_ATLAS_URL)
      .then((response) => response.json())
      .then((atlas) => {
        const countries = topojson.feature(atlas, atlas.objects.countries).features;
        const labels = countries
          .map((country) => {
            const centroid = d3.geoCentroid(country);
            const area = d3.geoArea(country);
            const name = country.properties && country.properties.name;
            return {
              lat: centroid[1],
              lng: centroid[0],
              name,
              size: Math.max(0.23, Math.min(0.62, Math.sqrt(area) * 3.2))
            };
          })
          .filter((country) => (
            country.name
            && country.name !== "Antarctica"
            && Number.isFinite(country.lat)
            && Number.isFinite(country.lng)
          ));

        globe.labelsData(labels);
      })
      .catch((error) => {
        console.error("Country labels could not be loaded.", error);
      });
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Montreal, Quebec, and world maps from a CSV of addresses."
    )
    parser.add_argument("csv_path", type=Path, help="Path to the CSV file containing addresses.")
    parser.add_argument(
        "--address-column",
        default="address",
        help="Name of the column containing the addresses.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Directory where output files will be written.",
    )
    parser.add_argument(
        "--cache-file",
        type=Path,
        default=None,
        help="Optional explicit path for the geocoding cache JSON file.",
    )
    parser.add_argument(
        "--label-column",
        default="institute",
        help="Name of the column containing institute labels shown next to pins.",
    )
    parser.add_argument(
        "--hide-labels",
        action="store_true",
        help="Disable institute labels next to pins.",
    )
    return parser.parse_args()


def load_cache(cache_path: Path) -> dict[str, dict[str, Any] | None]:
    if not cache_path.exists():
        return {}
    with cache_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_cache(cache_path: Path, cache: dict[str, dict[str, Any] | None]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2)


def geocode_addresses(
    addresses: list[str], cache: dict[str, dict[str, Any] | None]
) -> tuple[list[dict[str, Any] | None], dict[str, dict[str, Any] | None]]:
    geolocator = Nominatim(user_agent="marika_map_collaborations", timeout=10)
    geocode = RateLimiter(
        geolocator.geocode,
        min_delay_seconds=1.0,
        max_retries=1,
        swallow_exceptions=False,
    )

    results: list[dict[str, Any] | None] = []
    updated_cache = dict(cache)

    for address in addresses:
        if address in updated_cache:
            results.append(updated_cache[address])
            continue

        try:
            location = geocode(address)
        except GeocoderServiceError:
            updated_cache[address] = None
            results.append(None)
            continue
        if location is None:
            updated_cache[address] = None
            results.append(None)
            continue

        geocoded = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "display_name": location.address,
        }
        updated_cache[address] = geocoded
        results.append(geocoded)

    return results, updated_cache


def build_geocoded_frame(
    csv_path: Path,
    address_column: str,
    cache_path: Path,
) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    if address_column not in frame.columns:
        available = ", ".join(frame.columns.astype(str))
        raise ValueError(
            f"Column '{address_column}' was not found in {csv_path}. "
            f"Available columns: {available}"
        )

    frame = frame.copy()
    frame = frame[frame[address_column].notna()].copy()
    frame[address_column] = frame[address_column].astype(str).str.strip()
    frame = frame[frame[address_column].ne("")].reset_index(drop=True)

    cache = load_cache(cache_path)
    geocoded_results, updated_cache = geocode_addresses(
        frame[address_column].tolist(),
        cache,
    )
    save_cache(cache_path, updated_cache)

    geocoded_frame = pd.DataFrame.from_records(
        [result or {} for result in geocoded_results],
        columns=["latitude", "longitude", "display_name"],
    )
    frame = pd.concat([frame, geocoded_frame], axis=1)
    frame["geocoded"] = frame["latitude"].notna() & frame["longitude"].notna()
    return frame


def add_label(
    layer: folium.FeatureGroup,
    latitude: float,
    longitude: float,
    text: str,
    font_size_px: int = 16,
) -> None:
    label_html = f"""
    <div class="institute-label" style="
        color: #b91c1c;
        font-family: Georgia, 'Times New Roman', serif;
        font-size: {font_size_px}px;
        font-weight: 700;
        letter-spacing: 0.2px;
        text-shadow: 0 1px 2px rgba(255, 255, 255, 0.9);
        white-space: nowrap;
        transform: translate(12px, -6px);
    ">
        {html.escape(text)}
    </div>
    """
    folium.Marker(
        location=[latitude, longitude],
        icon=folium.DivIcon(
            icon_size=(220, 24),
            icon_anchor=(-4, 10),
            html=label_html,
        ),
    ).add_to(layer)


def add_label_slider(map_object: folium.Map, default_font_size_px: int) -> None:
    map_id = map_object.get_name()
    slider_html = f"""
    <style>
      .label-size-control {{
        background: rgba(255, 255, 255, 0.94);
        padding: 10px 12px;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
        font-family: Arial, sans-serif;
      }}
      .label-size-control label {{
        display: block;
        margin-bottom: 6px;
        font-size: 12px;
        font-weight: 700;
        color: #7f1d1d;
      }}
      .label-size-control input[type="range"] {{
        width: 140px;
      }}
      .label-size-control .label-size-value {{
        margin-left: 8px;
        font-size: 12px;
        color: #374151;
      }}
    </style>
    <script>
      function updateLabelSize_{map_id}(value) {{
        var labels = document.querySelectorAll("#{map_id} .institute-label");
        labels.forEach(function(label) {{
          label.style.fontSize = value + "px";
        }});
        var output = document.getElementById("label-size-value-{map_id}");
        if (output) {{
          output.textContent = value + "px";
        }}
      }}
    </script>
    """
    control_html = f"""
    <div class="label-size-control">
      <label for="label-size-slider-{map_id}">Label size</label>
      <input
        id="label-size-slider-{map_id}"
        type="range"
        min="3"
        max="24"
        step="1"
        value="{default_font_size_px}"
        oninput="updateLabelSize_{map_id}(this.value)"
      />
      <span id="label-size-value-{map_id}" class="label-size-value">{default_font_size_px}px</span>
    </div>
    """
    map_object.get_root().header.add_child(folium.Element(slider_html))
    control = folium.Element(
        f"""
        <script>
          window.addEventListener("load", function() {{
            var labelControl_{map_id} = L.control({{position: 'topright'}});
            labelControl_{map_id}.onAdd = function() {{
              var div = L.DomUtil.create('div');
              div.innerHTML = `{control_html}`;
              L.DomEvent.disableClickPropagation(div);
              L.DomEvent.disableScrollPropagation(div);
              return div;
            }};
            labelControl_{map_id}.addTo({map_id});
          }});
        </script>
        """
    )
    map_object.get_root().html.add_child(control)


def add_pins(
    map_object: folium.Map,
    data: pd.DataFrame,
    address_column: str,
    label_column: str | None,
    marker_text_column: str | None,
    label_font_size_px: int = 16,
    pin_radius: float = 8,
) -> None:
    label_layer: folium.FeatureGroup | None = None
    if label_column:
        label_layer = folium.FeatureGroup(name="Institute labels", show=True)
        label_layer.add_to(map_object)

    for _, row in data.iterrows():
        marker_text = None
        if marker_text_column:
            marker_value = row.get(marker_text_column)
            if pd.notna(marker_value):
                marker_text = str(marker_value).strip() or None

        marker_kwargs: dict[str, Any] = {}
        if marker_text:
            marker_kwargs["tooltip"] = marker_text
            marker_kwargs["popup"] = folium.Popup(marker_text, max_width=320)

        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=pin_radius,
            color="#9b1c1c",
            weight=2,
            fill=True,
            fill_color="#dc2626",
            fill_opacity=0.9,
            **marker_kwargs,
        ).add_to(map_object)

        if label_column:
            label_value = row.get(label_column)
            if pd.notna(label_value):
                label_text = str(label_value).strip()
                if label_text and label_layer is not None:
                    add_label(
                        label_layer,
                        row["latitude"],
                        row["longitude"],
                        label_text,
                        font_size_px=label_font_size_px,
                    )


def make_city_map(
    data: pd.DataFrame,
    address_column: str,
    label_column: str | None,
    marker_text_column: str | None,
    center: tuple[float, float],
    zoom_start: int,
    title: str,
    label_font_size_px: int = 16,
    pin_radius: float = 8,
) -> folium.Map:
    map_object = folium.Map(
        location=center,
        zoom_start=zoom_start,
        tiles=LABELED_TILE_LAYER,
        control_scale=True,
    )
    add_pins(
        map_object,
        data,
        address_column,
        label_column,
        marker_text_column,
        label_font_size_px=label_font_size_px,
        pin_radius=pin_radius,
    )
    title_html = f"""
    <div style="
        position: fixed;
        top: 18px;
        left: 50px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.92);
        padding: 10px 14px;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
        font-family: Arial, sans-serif;
        font-size: 20px;
        font-weight: 700;
    ">
        {title}
    </div>
    """
    map_object.get_root().html.add_child(folium.Element(title_html))
    if label_column:
        add_label_slider(map_object, label_font_size_px)
    folium.LayerControl(collapsed=False).add_to(map_object)
    return map_object


def make_world_map(
    data: pd.DataFrame,
    address_column: str,
    label_column: str | None,
    marker_text_column: str | None,
    title: str | None,
    pin_radius: float = 8,
    tile_layer: str = LABELED_TILE_LAYER,
    show_layer_control: bool = True,
) -> folium.Map:
    map_object = folium.Map(
        location=WORLD_CENTER,
        zoom_start=2,
        tiles=tile_layer,
        control_scale=True,
    )
    add_pins(
        map_object,
        data,
        address_column,
        label_column,
        marker_text_column,
        label_font_size_px=8,
        pin_radius=pin_radius,
    )

    bounds = data[["latitude", "longitude"]].values.tolist()
    if bounds:
        map_object.fit_bounds(bounds, padding=(30, 30))

    if title:
        title_html = f"""
        <div style="
            position: fixed;
            top: 18px;
            left: 50px;
            z-index: 1000;
            background: rgba(255, 255, 255, 0.92);
            padding: 10px 14px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
            font-family: Arial, sans-serif;
            font-size: 20px;
            font-weight: 700;
        ">
            {title}
        </div>
        """
        map_object.get_root().html.add_child(folium.Element(title_html))
    if label_column:
        add_label_slider(map_object, 8)
    if show_layer_control:
        folium.LayerControl(collapsed=False).add_to(map_object)
    return map_object


def globe_point_records(
    data: pd.DataFrame,
    marker_text_column: str | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for _, row in data.iterrows():
        name = None
        if marker_text_column:
            value = row.get(marker_text_column)
            if pd.notna(value):
                name = str(value).strip() or None

        records.append(
            {
                "lat": float(row["latitude"]),
                "lng": float(row["longitude"]),
                "altitude": 0.022,
                "name": name or "",
            }
        )
    return records


def write_globe_map(
    data: pd.DataFrame,
    marker_text_column: str | None,
    output_path: Path,
) -> None:
    points_json = json.dumps(
        globe_point_records(data, marker_text_column),
        ensure_ascii=False,
        indent=2,
    ).replace("</", "<\\/")
    output_path.write_text(
        GLOBE_HTML_TEMPLATE.replace("__POINTS_JSON__", points_json),
        encoding="utf-8",
    )


def write_maps(
    data: pd.DataFrame,
    address_column: str,
    label_column: str | None,
    marker_text_column: str | None,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    montreal_map = make_city_map(
        data,
        address_column,
        label_column,
        marker_text_column,
        center=MONTREAL_CENTER,
        zoom_start=10,
        title="Montreal",
        label_font_size_px=16,
        pin_radius=8,
    )
    montreal_map.save(str(output_dir / "montreal_map.html"))

    quebec_map = make_city_map(
        data,
        address_column,
        label_column,
        marker_text_column,
        center=QUEBEC_PROVINCE_CENTER,
        zoom_start=5,
        title="Quebec",
        label_font_size_px=8,
        pin_radius=6,
    )
    quebec_map.save(str(output_dir / "quebec_map.html"))

    world_map = make_world_map(
        data,
        address_column,
        label_column,
        marker_text_column,
        title="World",
        pin_radius=4,
    )
    world_map.save(str(output_dir / "world_map.html"))

    world_map_no_labels = make_world_map(
        data,
        address_column,
        label_column=None,
        marker_text_column=marker_text_column,
        title=None,
        pin_radius=4,
        tile_layer=NO_LABEL_TILE_LAYER,
        show_layer_control=False,
    )
    world_map_no_labels.save(str(output_dir / "world_map_no_labels.html"))

    write_globe_map(
        data,
        marker_text_column,
        output_dir / "world_globe.html",
    )


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    cache_path = args.cache_file or output_dir / "geocode_cache.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    geocoded = build_geocoded_frame(
        csv_path=args.csv_path,
        address_column=args.address_column,
        cache_path=cache_path,
    )
    geocoded.to_csv(output_dir / "geocoded_addresses.csv", index=False)

    geocoded_points = geocoded[geocoded["geocoded"]].copy()
    if geocoded_points.empty:
        raise RuntimeError("No addresses could be geocoded. No maps were generated.")

    marker_text_column = None
    if args.label_column in geocoded_points.columns:
        marker_text_column = args.label_column

    label_column = None
    if not args.hide_labels:
        label_column = marker_text_column

    write_maps(
        geocoded_points,
        args.address_column,
        label_column,
        marker_text_column,
        output_dir,
    )

    matched = int(geocoded_points.shape[0])
    total = int(geocoded.shape[0])
    print(f"Geocoded {matched} of {total} addresses.")
    print(f"Maps written to {output_dir.resolve()}")


if __name__ == "__main__":
    main()
