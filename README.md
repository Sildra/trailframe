# Trailframe

[![GitHub Release](https://img.shields.io/github/release/sildra/trailframe.svg?style=for-the-badge)](https://github.com/sildra/trailframe/releases)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/sildra/trailframe.svg?style=for-the-badge)](https://github.com/sildra/trailframe/commits/main)
[![License](https://img.shields.io/github/license/sildra/trailframe.svg?style=for-the-badge)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/custom-components/hacs)


A self-hosted photo gallery for people who move: photos and GPS activities (Garmin Connect / GPX) live side by side, linked by time and place. One server hosts everything — a FastAPI backend that also serves its web UI.

![Gallery view](docs/img/gallery_fish_dog.jpg)

## Photo library

- Automatic ingestion of a photo folder, with EXIF capture (camera, date, GPS) on import.
- Multi-size thumbnails generated and cached per photo; sizes are configurable.
- **Favorites** — mark photos you love and find them instantly; favorite-only views everywhere.
- **Automatic groups** — related photos are clustered so bursts and series stay together.
- Filter and combine by date range, group, location, tags, and favorites.

## Activities

- Import activities from Garmin Connect or GPX files.
- Every activity gets a trace map; photos taken during the activity appear alongside it.
- Interactive map with selectable traces and popups showing distance, duration, and time.

![Garmin activities](docs/img/activities_garmin.png)

## Slideshows

- Slideshow sources: an activity (photos + trace), a group, or a fully custom selection.
- Custom slideshows support date ranges, groups, locations, tags, randomization, and favorites-only.
- **Thumbnail mode** renders slides from cached thumbnails instead of full images — smooth playback even for large libraries, with the size chosen automatically from the available screen space.
- Standalone kiosk entry (`/slideshow.html`) with deep-linkable URLs for dedicated screens.
- ZIP export of an activity's photos.

![Slideshow with activity trace](docs/img/slideshow_activity_1.png)
![Slideshow photo view](docs/img/slideshow_activity_2.jpg)

## Enrichment pipelines

Photos are processed by pluggable scanners:

| Scanner | What it does |
| --- | --- |
| File | Registers the file (name, size) |
| EXIF | Extracts camera metadata, dates, and GPS position |
| Thumbnail | Generates all configured thumbnail sizes |
| Activity | Links photos to imported activities |
| Brisque | Scores image quality |
| Location | Resolves GPS coordinates to places and countries |
| Object | Detects objects in photos (YOLO models, downloaded automatically) |
| PerceptualHash | Fingerprints images for duplicate/near-duplicate grouping |

Scanners can be force re-run individually from the Tools page — e.g. regenerate all thumbnails after changing their sizes.

## Maps

- Wireframe maps of your photo coverage and per-photo location maps.
- Built-in tile cache/proxy: tiles are fetched once from the configured provider and served locally afterwards.

![Tools map with activity traces](docs/img/tools_map.png)

## Statistics

- Per-scanner throughput (items processed and speed).
- Storage overview: database size plus disk usage of every data folder.

## Running

Build the web UI once (`npm install && npm run build` inside `custom_component/trailframe/frontend`), then start the server from the repository root:

```bash
python supervisor.py --config path/to/config.yaml
```

The server listens on port 8000 by default; open `http://localhost:8000`. On first start a default `config.yaml` is written next to the backend, where all data (database, thumbnails, caches, trash) also lives.
