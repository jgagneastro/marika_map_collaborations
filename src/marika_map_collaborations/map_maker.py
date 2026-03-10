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
        min="6"
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
          var labelControl_{map_id} = L.control({{position: 'topright'}});
          labelControl_{map_id}.onAdd = function() {{
            var div = L.DomUtil.create('div');
            div.innerHTML = `{control_html}`;
            L.DomEvent.disableClickPropagation(div);
            L.DomEvent.disableScrollPropagation(div);
            return div;
          }};
          labelControl_{map_id}.addTo({map_id});
        </script>
        """
    )
    map_object.get_root().html.add_child(control)


def add_pins(
    map_object: folium.Map,
    data: pd.DataFrame,
    address_column: str,
    label_column: str | None,
    label_font_size_px: int = 16,
    pin_radius: float = 8,
) -> None:
    label_layer: folium.FeatureGroup | None = None
    if label_column:
        label_layer = folium.FeatureGroup(name="Institute labels", show=True)
        label_layer.add_to(map_object)

    for _, row in data.iterrows():
        tooltip = row.get(address_column, "Address")
        popup = row.get("display_name") or row.get(address_column, "Address")
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=pin_radius,
            color="#9b1c1c",
            weight=2,
            fill=True,
            fill_color="#dc2626",
            fill_opacity=0.9,
            tooltip=str(tooltip),
            popup=folium.Popup(str(popup), max_width=320),
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
    center: tuple[float, float],
    zoom_start: int,
    title: str,
    label_font_size_px: int = 16,
    pin_radius: float = 8,
) -> folium.Map:
    map_object = folium.Map(
        location=center,
        zoom_start=zoom_start,
        tiles="CartoDB Positron",
        control_scale=True,
    )
    add_pins(
        map_object,
        data,
        address_column,
        label_column,
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
    title: str,
    pin_radius: float = 8,
) -> folium.Map:
    map_object = folium.Map(
        location=WORLD_CENTER,
        zoom_start=2,
        tiles="CartoDB Positron",
        control_scale=True,
    )
    add_pins(
        map_object,
        data,
        address_column,
        label_column,
        label_font_size_px=8,
        pin_radius=pin_radius,
    )

    bounds = data[["latitude", "longitude"]].values.tolist()
    if bounds:
        map_object.fit_bounds(bounds, padding=(30, 30))

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
    folium.LayerControl(collapsed=False).add_to(map_object)
    return map_object


def write_maps(
    data: pd.DataFrame,
    address_column: str,
    label_column: str | None,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    montreal_map = make_city_map(
        data,
        address_column,
        label_column,
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
        title="World",
        pin_radius=4,
    )
    world_map.save(str(output_dir / "world_map.html"))


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

    label_column = None
    if not args.hide_labels and args.label_column in geocoded_points.columns:
        label_column = args.label_column

    write_maps(geocoded_points, args.address_column, label_column, output_dir)

    matched = int(geocoded_points.shape[0])
    total = int(geocoded.shape[0])
    print(f"Geocoded {matched} of {total} addresses.")
    print(f"Maps written to {output_dir.resolve()}")


if __name__ == "__main__":
    main()
