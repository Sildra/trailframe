# AGENTS.md

Trailframe — photo gallery app: Python/FastAPI backend + React/TS/Vite frontend, pip-installable as `trailframe` (wheels on GitHub releases; single server serving the built frontend).

## Quick Reference

| Task | Command |
|------|---------|
| Run backend | `python -m trailframe.main` |
| Build frontend | `cd frontend && npm run build` |
| Lint backend | `ruff check .` |
| Format backend | `ruff format .` |
| Lint frontend | `cd frontend && npm run lint` |
| Run tests | `python -m pytest` |
| Build package | `npm run build && python -m build` |
| Kill backend | `netstat -ano \| findstr :8000` then `taskkill -PID <pid> -F` |

## Layout

- `trailframe/` — FastAPI app
- `frontend/` — Vite + React app
- `pyproject.toml` — metadata, deps, ruff config, hatchling build, console script `trailframe = trailframe.main:main`
- `supervisor.py` — restarts `python -m trailframe.main`

## Backend (FastAPI, Python 3.12)

### Core

- **Run**: `python -m trailframe.main` from repo root
  - `main.py` serves `frontend/dist` from CWD if present, else packaged copy
  - Flags: `--config` (default `config.yaml`), `--folder` (sets `*_folder` subdirs), `--database`, `--port` (8000), `--failsafe` (skip `FolderService.start()`, no scan/watch), `--openapi FILE`

- **Artifacts** (CWD, all gitignored): `config.yaml`, `gallery.db`, `photos/`, `thumbnails/`, `trash/`, `maps/`, `activities/`, `models/`, `tiles/`

- **Style**: ruff from root `pyproject.toml`

- **pip**: `torch` installed to `C:\pylibs` via `.pth` (Win long-path limit); use `pip install --target C:/pylibs <pkg>` for deep dirs

- **Releases**: build frontend first, then `python -m build`; attach wheel to GitHub release (no PyPI)

### Architecture

- **Services** (`trailframe/services/`): class-based `Service` singletons wired in `main.py` lifespan
  - `service.py` (base), `core/` (Configuration, Database, Statistics, ThreadPool), `photos/` (Folder, Thumbnail, Photo), `activities/` (Activity, GarminConnect, Gpx), `map/` (Map, Location, Tile), plus `pipelines/`, `scanners/`
  - `Service`: non-virtual `configure/start/stop` → virtual `_configure/_start/_stop`, `_log` (`[Name]` prefixed on stderr via `log.py`), state tracking; `_name` overrides
  - `_requires`: each service declares its direct dependencies as names (resolved against `ServiceRegistry` at start); `start()` verifies them — on violation logs an `ERROR` and raises (`Service._require_started`)

- **Pipeline** base: eager thread-safe queue (sync `add`/`start`/`stop`, `get_queue_size`, `accepts`); `stop()` drains worker and flushes run stats; `take_pending()` returns leftover items; `PipelineEmpty` sentinel accepted everywhere and dropped

- **Start order**: `ThreadPoolService` → `DatabaseService` (creates tables) → `PhotoService` → `PipelineService` → `FolderService` → `ThumbnailService` → `MapService` → `GarminConnectService` → `GpxService` → `ActivityService` → `LocationService` → `TileService` → `StatisticsService` → `DuplicatesService` (order must satisfy `_requires`: DB→TP, Photos→DB, Pipeline→DB, Folder→DB+Pipeline, Thumbnail→Photos, Garmin→DB+TP, Gpx→DB, Activity→DB+TP+Garmin+Map, Location→DB+TP, Tile→TP, Statistics→DB, Duplicates→DB+TP)

- **Concurrency**: one shared pool (`ThreadPoolService`, size `general.thread_pool_size`, default 2); all heavy work (scanners, maps, Garmin, tiles, geo); each pipeline = 1 worker task (`Pipeline._worker_count = 1`) — bounds memory (one YOLO inference at a time); DB work stays on event loop

- **Call hierarchy**: content/enrichment = `Pipeline → Scanner → Service`; API content = `API → Service`, never a Scanner (map/wireframe via `LocationService`/`MapService`)

### Photos & Pipelines

- **PhotoService** (`photos/photo_service.py`): routes photo-source ops (resolve → local path, delete) to `PhotoProvider` keyed by `photo.source` (default `FolderService`, `SOURCE = "File"`, plus `RemoteProvider` `SOURCE = "Remote"` for in-memory photos with no disk file); extensible to network/NAS backends; upload/scan/folder-watching stay in `FolderService`

- **Pipelines** (`pipelines/pipeline_service.py`): explicitly registers `CreationPipeline`/`BasicPipeline` (not auto-discovered); `next(item, pipeline=None)` routes to first accepting pipeline — without a `pipeline` arg to the whole list, else after it; when the handing-off pipeline vanished from the list during reconfigure it continues from `pipeline._index` (stored position), so remote photos never re-enter the standard pipeline at index 0
  - External items: `Photo` (`FolderService.to_photo`) → `Item` (`photo` + `updated` flag + lazily-cached PIL `image`)
  - `_run_scanners`: runs every scanner's `execute(item)`; last scanner `DatabaseScanner` merges/commits on `item.updated`
  - `CreationPipeline`: `FileScanner`/`ExifScanner`/`ThumbnailScanner`/`DatabaseScanner`
  - `BasicPipeline`: `ActivityScanner`/`LocationScanner`/`ObjectScanner`/`PerceptualHashScanner`/`DatabaseScanner`; gates routing on `any(scanner.accept(item))`
  - **Defaults**: `DEFAULT_PIPELINES` in `PipelineService`; editor template (`PIPELINES_TEMPLATE`) assembled into API payloads by `add_pipelines_payload` (called from `api/configuration.py`); `ConfigurationService` is purely structural
  - **Cold `_configure`**: materializes defaults into `pipelines` config node when absent/empty; persists to `config.yaml` and round-trips to frontend
  - **Live reconfigure**: `POST /api/configuration` → `_reconfigure_live` (only when `STARTED`); matches pipelines to config by name; unchanged kept (params re-read), changed migrated (old worker stopped, items carried with `take_pending()`, new started), new added, missing removed; response includes `applied` summary via `get_last_reconfigure()`

### Scanners

- **Scanner contract** (`scanners/scanner.py`): non-virtual `configure/accept/execute` → overloadable `configure_/accept_/executePhoto`
  - `configure`: reads `enabled`; `accept`: handles `ForceFlag` (`_forced` toggle), `enabled`, `_forced`, else `accept_`; `execute`: calls `accept` first (declined → `ScannerResult.SUCCESS`), stashes `self._item`, runs `executePhoto` (sync on `ThreadPoolService`), returns `SUCCESS`/`ERROR`, sets `item.updated` if photo changed
  - `DatabaseScanner.accept` = `isinstance(item, Item) and item.updated`

- **Scanner tracking**: `self.add_scanner(photo)` appends name to `photo.scanners` (JSON column, NULL-safe; read via `photo.scanners or []`); `ObjectScanner` runs YOLO on `item.image` (in-memory PIL, no path needed; model `yolo26n.pt`/`yolo26m.pt` in `general.models_folder`), stores `photo.objects` (`[{label, confidence, box}]`), gates on `"Object" not in photo.scanners`; image-bearing scanners (`EXIF`/`PerceptualHash`/`Object`) all consume `item.image`, which can be preloaded via `Item(photo, image=...)` for in-memory sources

### Database & Storage

- **DB models**: SQLModel classes in `trailframe/models/` (converter classmethods, e.g. `GarminActivity.to_activity`); tables auto-created at startup, no migrations

- **Thumbnails** (`photos/thumbnail_service.py`): multi-size via `general.thumbnail_sizes` (default `[160, 400]`); files at `{safe_filename[:2]}/{safe_filename}_{file_size}_{size}.webp` (fallback `{safe_filename}_{size}.webp`); `generate_all` writes all; `exists` = all present; `select_size` picks lowest ≥ preferred when ≤ 2×preferred else highest below; `GET /api/photos/{id}/thumbnail?size=<p>`

- **Location boundaries cache** (`map/location_service.py`): `maps/_cache/*.jsonl` — JSON Lines, geometry as base64 WKB; `_read_entries`/`_write_entries` stream line-by-line (never a whole-file parse — the old array format peaked at file+parsed structure, measured 311 MB for `adm0`); unparseable/empty file = cache miss → re-download; superseded `.json` array caches are ignored and deleted on rewrite (no retrocompat); ADM0 download is strictly sequential (convert-to-shapely-and-drop per country, never parallel); `_adm0` resident, `_adm1`/`_adm2` LRU-bounded (`_ADM_CACHE_SIZE`, 16); `_find`/wireframe prefilter use `STRtree`; `_timed_load` logs duration/traced-peak/geometry-size at DEBUG (`LocationService` logger)

- **Favorites**: `Photo.is_favorite` (`_add_missing_columns`); `PUT /api/photos/{id}/favorite`, `GET /api/photos?favorites=true`, `GET /api/photos/favorites`

- **Deletion** (`api/photos.py`): move source to `general.trash_folder` via `FolderService.delete()`, remove thumbnail, delete DB row

### API Endpoints

- **Maps/tiles**: `TileService` + `/api/tiles/{z}/{x}/{y}.png` proxy/cache (`general.tiles_folder`, TTL/size under `maps:`)

- **Forced scans** (Tools page): `POST /api/pipeline/scan {"scanners": [...]}`, `GET /api/pipeline/scanners`; `forced_scan(names)`: `ForceFlag(names)` → re-push every `Photo` as `Item`s → `ForceFlag([])`; forced beats `accept_` but honors `enabled`

- **Events** (`api/events.py`): SSE `GET /api/events` streams pipeline status dicts (0.2 s poll, sent on change); `Boundaries` pseudo-category reports `LocationService.get_download_progress()` as `(current/failed/total)` during boundary downloads, then one empty string (frontend drops the category) before the key is omitted; `Text` key → log line in EventBar

- **Remote scan**: `RemoteScanner` (host side) uploads the photo to `POST /api/pipeline/remote-scan` on the remote server, which runs the delegated scanners on an in-memory `Item(photo, image=...)` (no tmp file) with `photo.source = "Remote"` and returns the enriched fields; force flags propagate via a `forced` form field. `scanners.<Name>.enable_remote` gating lives on the *remote* instance only (`_get_scanner_by_name` on the endpoint), never on the delegating host — the host keeps all scanners configured in the pipeline that are code-capable of remote execution. Host side: `RemoteScanner.accept` intercepts `ForceFlag` (sets `_forced_names` = flag ∩ `_scanner_names`, then forces locally) and folds them into the request. Remote side: `_scanner_cache` reuses cached instances (`_get_scanner_by_name` re-runs `configure`); `_execute_remote_scanners` runs on the shared `ThreadPoolService` and feeds each cached scanner `ForceFlag(forced_names)` before executing then `ForceFlag([])` in `finally`

- **Statistics** (`core/statistics_service.py`): `Scanner._record` times scans; `Pipeline._flush_stats` persists `ScannerStat` row per scanner via `record_run`; `GET /api/statistics/scanners` (items/s); `GET /api/statistics/storage` (DB + folder sizes); `FolderStat`/`StorageStats` are pydantic shapes in `api/statistics.py`, not DB tables; for tests: insert mock `ScannerStat` rows, don't run real scans

## Frontend (Vite + React 19 + TS)

- **Entries**: `index.html` (`/?page=...&section=`), `slideshow.html` (`src/SlideshowApp.tsx`, `?section=&activity=`/`?photos=&name=&thumbs=`); params canonicalized in `src/lib/slideshowSections.ts`

- **Commands**: `npm run lint`, `npm run build`, `npm run dev` (node/npm/npx on PATH at `/c/Program Files/nodejs`)

- **Schema generation**: `src/api/generated/schema.ts` generated by `openapi-typescript` — never hand-edit; regenerate: from root `python -m trailframe.main --openapi ./openapi_local.json`, then from `frontend/` `npx openapi-typescript ../openapi_local.json -o src/api/generated/schema.ts`; delete temp file

- **API calls**: relative same-origin; dev proxy `/api` → `http://localhost:8000` (backend must run)

## Verification

- **Tests**: pytest + pytest-asyncio + httpx in `tests/`; `python -m pytest` from root
  - Fixtures: `app` (TestClient, full lifespan; `.db(coro)` for inserts on app's event-loop thread) and `db_session` (standalone configured `DatabaseService`)
  - Coverage: via `addopts`; gitignored `.coverage`/`coverage.xml`/`htmlcov/`

- **Allure 3**: `addopts = --alluredir=allure-results --clean-alluredir`; groups by class (`feature`)/method (`story`); `allure generate ./allure-results` + `allure open ./allure-report`; results/report gitignored

- **CI** (`.github/workflows/publish.yml`, on `v*` tags): Test → Release → Notify; local verification: test against `http://localhost:8000` (confirm frontend is up first); **never** test Garmin Connect against live service — always mock `garminconnect` client (see `tests/test_garmin_connect_service.py`)

### Change Types

| Change | Action |
|--------|--------|
| Backend | Kill port-8000 (`netstat -ano \| findstr :8000`, `taskkill -PID <pid> -F`), wait auto-restart |
| API | Regenerate schema (don't hit live server) |
| Frontend | Build from `frontend/`: `npm run build` |