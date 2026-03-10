# marika_map_collaborations

Generate three presentation-ready maps from a CSV of addresses:

- a Montreal-focused map
- a Quebec-focused map
- a world map

Each map places a pin at every address that can be geocoded.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## CSV format

By default, the script expects a column named `address`.
If a column named `institute` is present, the institute names are shown next to the pins by default.

Example:

```csv
institute,address
"Montreal Planetarium","Montreal Planetarium, Montreal, QC, Canada"
"Quebec Observatory","1 Rue des Carrieres, Quebec City, QC, Canada"
"Google HQ","1600 Amphitheatre Parkway, Mountain View, CA, USA"
```

If your CSV uses a different column name, pass `--address-column`.
If your institute names are in a different column, pass `--label-column`.

Addresses containing commas must be quoted as valid CSV fields.

## Usage

```bash
make-address-maps data/addresses.csv
```

Or:

```bash
python -m marika_map_collaborations.cli data/addresses.csv
```

Optional flags:

```bash
make-address-maps data/addresses.csv \
  --address-column full_address \
  --label-column institute_name \
  --output-dir outputs
```

Use `--hide-labels` to suppress text labels beside the pins.

Outputs:

- `outputs/montreal_map.html`
- `outputs/quebec_map.html`
- `outputs/world_map.html`
- `outputs/geocoded_addresses.csv`
- `outputs/geocode_cache.json`

## Notes

- Geocoding uses OpenStreetMap's Nominatim service through `geopy`.
- Results are cached locally to avoid repeated API requests.
- The maps use the `CartoDB Positron` tile set for a clean presentation style.
- The Quebec map is centered on the province of Quebec by default, not Quebec City.
