from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import folium
import pandas as pd
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
    geolocator = Nominatim(user_agent="marika_map_collaborations")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.0)

    results: list[dict[str, Any] | None] = []
    updated_cache = dict(cache)

    for address in addresses:
        if address in updated_cache:
            results.append(updated_cache[address])
            continue

        location = geocode(address)
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


def add_pins(map_object: folium.Map, data: pd.DataFrame, address_column: str) -> None:
    for _, row in data.iterrows():
        tooltip = row.get(address_column, "Address")
        popup = row.get("display_name") or row.get(address_column, "Address")
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=8,
            color="#9b1c1c",
            weight=2,
            fill=True,
            fill_color="#dc2626",
            fill_opacity=0.9,
            tooltip=str(tooltip),
            popup=folium.Popup(str(popup), max_width=320),
        ).add_to(map_object)


def make_city_map(
    data: pd.DataFrame,
    address_column: str,
    center: tuple[float, float],
    zoom_start: int,
    title: str,
) -> folium.Map:
    map_object = folium.Map(
        location=center,
        zoom_start=zoom_start,
        tiles="CartoDB Positron",
        control_scale=True,
    )
    add_pins(map_object, data, address_column)
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
    return map_object


def make_world_map(data: pd.DataFrame, address_column: str, title: str) -> folium.Map:
    map_object = folium.Map(
        location=WORLD_CENTER,
        zoom_start=2,
        tiles="CartoDB Positron",
        control_scale=True,
    )
    add_pins(map_object, data, address_column)
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
    return map_object


def write_maps(data: pd.DataFrame, address_column: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    montreal_map = make_city_map(
        data,
        address_column,
        center=MONTREAL_CENTER,
        zoom_start=10,
        title="Montreal",
    )
    montreal_map.save(str(output_dir / "montreal_map.html"))

    quebec_map = make_city_map(
        data,
        address_column,
        center=QUEBEC_PROVINCE_CENTER,
        zoom_start=5,
        title="Quebec",
    )
    quebec_map.save(str(output_dir / "quebec_map.html"))

    world_map = make_world_map(data, address_column, title="World")
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

    write_maps(geocoded_points, args.address_column, output_dir)

    matched = int(geocoded_points.shape[0])
    total = int(geocoded.shape[0])
    print(f"Geocoded {matched} of {total} addresses.")
    print(f"Maps written to {output_dir.resolve()}")


if __name__ == "__main__":
    main()
