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
| Test frontend | `cd frontend && npm test` |
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
  - Flags: `--config` (default `config.yaml`), `--folder` (sets `originals`/`processed`/`trash` and other `*_folder` subdirs), `--database`, `--port` (8000), `--failsafe` (skip `FolderService`/`ProcessingService` start, no scan/watch), `--openapi FILE`

- **Artifacts** (CWD, all gitignored): `config.yaml`, `gallery.db`, `originals/`, `processed/`, `thumbnails/`, `trash/`, `maps/`, `activities/`, `models/`, `tiles/`

- **Style**: ruff from root `pyproject.toml`

- **pip**: `torch` installed to `C:\pylibs` via `.pth` (Win long-path limit); use `pip install --target C:/pylibs <pkg>` for deep dirs

- **Releases**: build frontend first, then `python -m build`; attach wheel to GitHub release (no PyPI)

### Architecture

- **Services** (`trailframe/services/`): class-based `Service` singletons wired in `main.py` lifespan
  - `service.py` (base), `core/` (Configuration, Database, Statistics, ThreadPool), `photos/` (Folder, Processing, Thumbnail, Photo), `rules/` (Rule), `activities/` (Activity, GarminConnect, Gpx), `map/` (Map, Location, Tile), plus `pipelines/`, `scanners/`
  - `Service`: non-virtual `configure/start/stop` → virtual `_configure/_start/_stop`, `_log` (`[Name]` prefixed on stderr via `log.py`), state tracking; `_name` overrides
  - `_requires`: each service declares its direct dependencies as names (resolved against `ServiceRegistry` at start); `start()` verifies them — on violation logs an `ERROR` and raises (`Service._require_started`)

- **Pipeline** base: eager thread-safe queue (sync `add`/`start`/`stop`, `get_queue_size`, `accepts`); `stop()` drains worker and flushes run stats; `take_pending()` returns leftover items; `PipelineEmpty` sentinel accepted everywhere and dropped

- **Start order**: `ThreadPoolService` → `ExpressionEngineService` → `DatabaseService` (creates tables) → `HardwareService` → `PhotoService` → `TagService` → `RuleService` → `PipelineService` → `FolderService` → `ProcessingService` → `ThumbnailService` → `MapService` → `GarminConnectService` → `GpxService` → `ActivityService` → `LocationService` → `TileService` → `StatisticsService` → `DuplicatesService` (order must satisfy `_requires`: DB→TP, Hardware→DB, Photos→DB, Tag→DB, Rule→DB+Tag, Pipeline→DB, Folder→DB, Processing→TP+Folder+Pipeline, Thumbnail→Photos, Garmin→DB+TP, Gpx→DB, Activity→DB+TP+Garmin+Map, Location→DB+TP, Tile→TP, Statistics→DB, Duplicates→DB+TP)

- **Concurrency**: one shared pool (`ThreadPoolService`, size `general.thread_pool_size`, default 2); all heavy work (scanners, maps, Garmin, tiles, geo); each pipeline = 1 worker task (`Pipeline._worker_count = 1`) — bounds memory (one YOLO inference at a time); DB work stays on event loop

- **Hardware detection** (`core/hardware_service.py`): `HardwareService` runs before `PipelineService` at configure time so scanner flags are already settled. It reads the free (available) physical memory with stdlib only (`GlobalMemoryStatusEx`/`ullAvailPhys` on Windows, `MemAvailable` from `/proc/meminfo` on Linux, `vm_stat` on macOS) and, below `MIN_FREE_RAM_GB` (1 GB), sets `scanners.<Name>.enabled = false` for every heavy scanner. The outcome is recorded only in the generic `app_data` table (key `hardware_detection`): free memory, threshold, heavy scanner names and the ones auto-disabled. Detection only re-evaluates heavy scanners missing from that record, so scanners added by a later release are covered without overriding a user's earlier enable/disable choice. The result is internal and deliberately not exposed through the API; `Hardware & performance` (`trailframe/docs/hardware.md`, `GET /api/docs/hardware`) explains the behaviour in the Help menu.

- **Call hierarchy**: content/enrichment = `Pipeline → Scanner → Service`; API content = `API → Service`, never a Scanner (map/wireframe via `LocationService`/`MapService`)

### Photos & Pipelines

- **Photo files** (`models/photo.py`, `models/photo_file.py`): the chain is `originals/` → preprocessing → `processed/` → pipelines. One `Photo` row describes both: `path`/`filename`/`file_size` are the **original** archive file (relative to `originals/`, `path` unique); `alternatives` is a JSON list of processed files (`{target_size, path, filename, file_size, width, height, main}`, path relative to `processed/`); `processing` is a separate JSON list of provenance (`{step, source, target_size, format, quality, tool, tool_version, at}`). Accessors return a `PhotoFile` value object: `photo.original`, `photo.main()` (the entry flagged `main`, else the original) and `photo.alternative(target)`. Alternatives carry pixels only; EXIF stays on the original and orientation is baked in. No backfill: legacy rows have no alternatives and `main()` falls back to the original.

- **PhotoService** (`photos/photo_service.py`): resolves and deletes photo files. `resolve(photo, file=None)` uses the provider for originals (default `ProcessingService`, `SOURCE = "File"`, plus `RemoteProvider` `SOURCE = "Remote"` for in-memory photos) and `FolderService` for alternatives; it defaults to `photo.main()`. `delete(photo)` removes every alternative and moves the original to the trash. Extensible to network/NAS backends.

- **ProcessingService** (`photos/processing_service.py`): owns originals and preprocessing. `POST /api/photos/upload` writes the original into `general.originals_folder` (unique `name_1.ext`, `.part` temp file) and keeps it as the archive; it encodes each `processing.alternatives` target size (longest edge, default `[1080]`) into `general.processed_folder` (WebP, `processing.main`/`format`/`quality`), records provenance, then hands the `Photo` to the pipeline. On startup and every 10 s a watcher imports leftover originals, skipping those already in the DB. `_requires = ("ThreadPoolService", "FolderService", "PipelineService")`; honors `general.failsafe`.

- **FolderService** (`photos/folder_service.py`): the processed store only — resolves relative alternative paths and deletes processed files/alternatives. It never scans or watches; everything it contains is derived and regenerable.

- **Pipelines** (`pipelines/pipeline_service.py`): explicitly registers `CreationPipeline`/`BasicPipeline` (not auto-discovered); `next(item, pipeline=None)` routes to first accepting pipeline — without a `pipeline` arg to the whole list, else after it; when the handing-off pipeline vanished from the list during reconfigure it continues from `pipeline._index` (stored position), so remote photos never re-enter the standard pipeline at index 0
  - External items: `Photo` → `Item` (`photo` + `updated` flag + lazily-cached `image` = main pixels and `original` = original pixels); EXIF reads `item.original`, content scanners read `item.image`
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

- **Scanner tracking**: `self.add_scanner(photo)` appends name to `photo.scanners` (JSON column, NULL-safe; read via `photo.scanners or []`); `ObjectScanner` runs YOLO on `item.image` (in-memory PIL, no path needed; model `yolo26n.pt`/`yolo26m.pt` in `general.models_folder`), stores `photo.objects` as `{reference: {width, height}, detections: [{label, confidence, box, surface}]}` — `box` is absolute pixels in the detector's decoded image and `reference` is that image's size, so `surface` (0–1, 1/1000) stays valid when a differently sized file is served; gates on `"Object" not in photo.scanners`; image-bearing scanners (`EXIF`/`PerceptualHash`/`Object`) all consume `item.image`, which can be preloaded via `Item(photo, image=...)` for in-memory sources
- **Heavy flag**: `Scanner._heavy` (default `False`) marks memory-intensive scanners; exposed by `get_scanner_definitions()` and the pipeline scanner chooser. `Object` is the only heavy scanner today, so `HardwareService` can disable it on small machines.
- **No tag scanner**: tags are never inferred from the photo content (not from the YOLO objects, not from the EXIF data) — they are only assigned by the user through the tag API, or by a user-defined **rule** (see Rules)

### Tags

- **Model** (`models/tag.py`): `Tag` table (`tags`) — `id`, `name`, `path` (unique, slash-separated full path), `parent_id`, `depth`, `rules` (JSON list of embedded rule documents); `TagNode` is the API DTO (`count` = photos with exactly this path, `total` = incl. descendants, `rules_count` = rules assigning this exact path, `children`)
- **TagService** (`services/photos/tag_service.py`): owns the registry *shape*; `Photo.tags` (JSON list of full paths) owns the *assignments* — one source of truth per concern, no tag scanner
  - Paths: `normalize()` (trim segments, single `/`), `name_of()`, `parent_path()`, `ancestors()`, `depth_of()`; `MAX_DEPTH = 10` levels
  - `ensure_paths()` registers a path **and its ancestors** (missing parents are created)
  - `seed_defaults()` installs `DEFAULT_TAGS` (155 nodes / 12 roots: Activity, Architecture, Landscape, Animals, People, Food, Nature, Transport, Object, Event, Document, Quality); seeded automatically on first start when the `tags` table is empty, so user deletions survive restarts (no config flag)
  - `match()` / `match_exact()`: SQL conditions over `json_each(COALESCE(photo.tags,'[]'))` — `value = :path OR value LIKE :path || '/%'` (exact + descendants), `mode` = `any`/`all`
  - `sync(payload)`: bulk vocabulary write (one request carries the whole tree). Diff = rename (by `id`) → keep → cascade delete → create → describe; a renamed tag moves its descendants **and** the photos carrying them **and** its embedded rules (renamed in place); a deleted parent kills its whole subtree even if the payload still lists a descendant, and its rules go with the rows
  - `delete(tag_id)`: cascade delete of a tag + descendants, stripping them from the photos
  - `set_photo_tags(photo_id, paths)` replaces the whole list of a photo's tags (one call, not incremental)
- **Photo filters**: `GET /api/photos?tags=&tags_mode=any|all&include_descendants=true` and `GET /api/photos/ids` (ids only, used by the gallery/slideshow); `GET /api/photos/custom?tags=` keeps the AND semantics

### Rules

- **Storage**: rules live **on the tag they assign** (`Tag.rules`, a JSON list) — there is no rule table, no FK and no orphan. The owning tag *is* the target: renaming/moving the tag carries its rules, deleting the tag deletes them. Legacy `tag_rule` tables are ignored (never read, never dropped).
- **Rule document**: `{id, name, description, enabled, priority, expression, definition}`. `expression` is kept for display/re-edit; `definition` is authoritative and the backend **never parses** expression text.
- **Definition AST** (`services/rules/ast.py`): `{version, match: all|any, conditions}`; a condition is `scalar` (`path`, `op`, `value`), `detection` (`label`, `present|absent`, `metrics`) or recursive `group`. A detection binds its label and metric constraints to the **same** detection. Detection metric values are written in **percent** (`confidence >= 80`); `metric_scale()` maps them to the stored 0–1 values (`confidence`/`surface` stay 0–1 in `photo.objects`). Units (`%`, `mm`, `s`, `px`, `B`, prefix `f/`) are expression syntax only, never part of the AST.
- **Schema** (`services/rules/schema.py`): one descriptor drives validation, evaluation, the generated form and the editor hints — groups/fields/kind/operators/docs/value source, plus the detection metrics. Fields: objects, EXIF make/model/lens/aperture/ISO/focal length/exposure, image width/height/orientation from `photo.main()` (EXIF fallback), country/location/date/lat/long, filename/file size/favorite/tags/scanners, `scores.brisque`. `MAX_CONDITIONS = 20`, `MAX_GROUP_DEPTH = 4`; `validate_definition()` rejects unknown paths/operators, malformed values and metric values outside 0–100.
- **RuleService** (`services/rules/rule_service.py`): `_requires = (DatabaseService, TagService)`; embeds CRUD in `Tag.rules`, keeps every rule in `_records` and the enabled ones in `_rules` (refreshed at `_start`, after writes, and from `api/tags.py` after sync/delete) so `RulesScanner` evaluates with no DB round-trip. `schema()` and `values()` serve the editor (bounded dynamic dictionaries, cached for 60 s). `preview()` is read-only and capped at `TEST_SCAN_LIMIT = 5000`; `apply_all()` re-applies enabled rules to the library, add-only.
- **ExpressionEngineService** (`services/rules/expression_engine_service.py`): loads the standalone frontend bundle (`frontend/dist-expression/expression.js`, built by `npm run build:expression`) in `mini-racer` (V8) and exposes `parse()` / `print()`; the same parser/printer as the editor, with the served schema injected once. The bundle is force-included in the wheel like `frontend/dist`.
- **Evaluator** (`services/rules/evaluator.py`): AST-only (`matches`, `tags_for_photo`); a detection's metrics must all hold for one detection; `surface` is the stored 0–1 value from `photo.objects.detections` (captured against the object `reference`, not recomputed from `photo.main()`); missing values match only `neq`/`not_contains`.
- **RulesScanner** (`services/scanners/rules_scanner.py`): a standard scanner registered in `SCANNER_DEFINITIONS` and in `BasicPipeline` **after** `Object` (so detections exist) and **before** `Database` (so tags persist). Gates on `"Rules" not in photo.scanners`, add-only.
- **API** (`api/rules.py`): `GET /api/rules/schema`, `GET /api/rules/values`, `POST /api/rules/expression/parse` (text → AST), `POST /api/rules/expression/print` (AST → canonical text), `GET/POST /api/rules`, `GET/PUT/DELETE /api/rules/{id}`, `POST /api/rules/preview`, `POST /api/rules/apply`.

### Database & Storage

- **DB models**: SQLModel classes in `trailframe/models/` (converter classmethods, e.g. `GarminActivity.to_activity`); tables auto-created at startup, no migrations

- **Generic data** (`core/app_data.py`, model `models/app_data.py`): `app_data` is a key/value table (`key` PK, `value`, `updated_at`) for misc state; `AppData.get_value/set_value` use the running DB session, `read_value(path, key)` reads it synchronously before `DatabaseService` starts (used by `HardwareService._configure`)

- **Thumbnails** (`photos/thumbnail_service.py`): multi-size via `general.thumbnail_sizes` (default `[160, 400]`); files at `{sha1(original path)[:2]}/{sha1}_{main_target}_{size}.webp` (`original` when the main file is the original), so they survive reprocessing at the same target but invalidate when it changes; `generate_all` writes all; `exists` = all present; `delete(photo)` removes every size; `select_size` picks lowest ≥ preferred when ≤ 2×preferred else highest below; `GET /api/photos/{id}/thumbnail?size=<p>`

- **Location boundaries cache** (`map/location_service.py`): `maps/_cache/*.jsonl` — JSON Lines, geometry as base64 WKB; `_read_entries`/`_write_entries` stream line-by-line (never a whole-file parse — the old array format peaked at file+parsed structure, measured 311 MB for `adm0`); unparseable/empty file = cache miss → re-download; superseded `.json` array caches are ignored and deleted on rewrite (no retrocompat); ADM0 download is strictly sequential (convert-to-shapely-and-drop per country, never parallel); `_adm0` resident, `_adm1`/`_adm2` LRU-bounded (`_ADM_CACHE_SIZE`, 16); `_find`/wireframe prefilter use `STRtree`; `_timed_load` logs duration/traced-peak/geometry-size at DEBUG (`LocationService` logger)

- **Favorites**: `Photo.is_favorite` (`_add_missing_columns`); `PUT /api/photos/{id}/favorite`, `GET /api/photos?favorites=true`, `GET /api/photos/favorites`

- **Deletion** (`api/photos.py`): `PhotoService.delete()` discards the alternatives via `FolderService.delete_alternatives()`, moves the original to `general.trash_folder` via its provider; `ThumbnailService.delete(photo)` removes the thumbnails; then the DB row is deleted

### API Endpoints

- **Tags** (`api/tags.py`): `GET /api/tags` → the registry tree (`TagNode[]`); `PUT /api/tags` → replace the whole vocabulary in one request (`{"tags": [{id, path}]}`) and return the new tree; `DELETE /api/tags/{id}` → cascade delete of a tag and its descendants
- **Photo files** (`api/photos.py`): `GET /api/photos/{id}/image?size=<target>` serves the matching alternative, or `photo.main()` when omitted/unknown; `POST /api/photos/upload` returns the photo's original `{filename, path, alternatives}`
- **Photo tags** (`api/photos.py`): `PUT /api/photos/{id}/tags` → replace the tags of a photo with the given list (`{"tags": [...]}` → `{id, tags}`); `GET /api/photos/ids` → the ids of the photos matching the filters (tags/favorites)

- **Maps/tiles**: `TileService` + `/api/tiles/{z}/{x}/{y}.png` proxy/cache (`general.tiles_folder`, TTL/size under `maps:`)

- **Forced scans** (Tools page): `POST /api/pipeline/scan {"scanners": [...]}`, `GET /api/pipeline/scanners`; `forced_scan(names)`: `ForceFlag(names)` → re-push every `Photo` as `Item`s → `ForceFlag([])`; forced beats `accept_` but honors `enabled`

- **Events** (`api/events.py`): SSE `GET /api/events` streams pipeline status dicts (0.2 s poll, sent on change); `Boundaries` pseudo-category reports `LocationService.get_download_progress()` as `(current/failed/total)` during boundary downloads, then one empty string (frontend drops the category) before the key is omitted; `Text` key → log line in EventBar

- **Remote scan**: `RemoteScanner` (host side) uploads the photo to `POST /api/pipeline/remote-scan` on the remote server, which runs the delegated scanners on an in-memory `Item(photo, image=...)` (no tmp file) with `photo.source = "Remote"` and returns the enriched fields; force flags propagate via a `forced` form field. `scanners.<Name>.enable_remote` gating lives on the *remote* instance only (`_get_scanner_by_name` on the endpoint), never on the delegating host — the host keeps all scanners configured in the pipeline that are code-capable of remote execution. Host side: `RemoteScanner.accept` intercepts `ForceFlag` (sets `_forced_names` = flag ∩ `_scanner_names`, then forces locally) and folds them into the request. Remote side: `_scanner_cache` reuses cached instances (`_get_scanner_by_name` re-runs `configure`); `_execute_remote_scanners` runs on the shared `ThreadPoolService` and feeds each cached scanner `ForceFlag(forced_names)` before executing then `ForceFlag([])` in `finally`

- **Statistics** (`core/statistics_service.py`): `Scanner._record` times scans; `Pipeline._flush_stats` calls `record_run`, which keeps **one aggregated `ScannerStat` row per scanner** (`count`/`total_ms` accumulate in place, the scanner name is unique, so the table never grows with runs); `GET /api/statistics/scanners` (items/s); `GET /api/statistics/storage` (DB + folder sizes); `FolderStat`/`StorageStats` are pydantic shapes in `api/statistics.py`, not DB tables; for tests: insert mock `ScannerStat` rows, don't run real scans

- **Docs/version** (`api/docs.py`, `api/about.py`): `GET /api/docs` lists bundled Markdown documents (`hardware`, `tutorial`, `whats-new`), `GET /api/docs/{name}` returns `{name, title, description, content}` from `trailframe/docs/*.md` (whitelisted names, `importlib.resources` so the wheel works); `GET /api/about/version` returns `trailframe.version.app_version()` (installed metadata → generated `_version.py` → `0.0.0`), also used as the FastAPI version

## Frontend (Vite + React 19 + TS)

- **Entries**: `index.html` (`/?page=...&section=`), `slideshow.html` (`src/SlideshowApp.tsx`, `?section=&activity=`/`?photos=&name=&thumbs=`); params canonicalized in `src/lib/slideshowSections.ts`

- **Commands**: `npm run lint`, `npm test`, `npm run build`, `npm run dev` (node/npm/npx on PATH at `/c/Program Files/nodejs`)

- **Tables**: compact globally in `src/theme.tsx` — `MuiDataGrid` defaults to `density: "compact"` (13 px cells/headers), `MuiTable` defaults to `size="small"` with 4 px/8 px cell padding; don't re-specify size/density per table

- **Schema generation**: `src/api/generated/schema.ts` generated by `openapi-typescript` — never hand-edit; regenerate: from root `python -m trailframe.main --openapi ./openapi_local.json`, then from `frontend/` `npx openapi-typescript ../openapi_local.json -o src/api/generated/schema.ts`; delete temp file

- **API calls**: relative same-origin; dev proxy `/api` → `http://localhost:8000` (backend must run)

### Tags UI

- **`src/lib/tags.ts`**: path helpers (`tagName`, `tagParent`, `isTagUnder`, `normalizeTagPath`, `sanitizeTagName`) and draft operations on the flat `TagEntry[]` model (`{id, path}` — exactly the bulk payload): `flattenTags`, `buildTagTree` (tree derived from the paths), `renameTag`, `moveTag`, `addTag`, `removeTag`
- **`src/components/TagTree.tsx`**: hand-rolled recursive tree on MUI primitives (no `@mui/x-tree-view`); `checkable` shows the checkboxes, `filter` keeps the matching nodes and their ancestors
- **`src/components/TagPicker.tsx`**: dialog with a searchable tree + "new tag path" field (missing parents are created server-side); used by the photo metadata and the custom slideshow menu
- **`src/components/TagOverview.tsx`**: the **Overview** tab — a `DataGrid` of the vocabulary (Tag, Path, Rules, Photos, With descendants), scope select (all/root/used) and quick add; the Rules count comes straight from `TagNode.rules_count` (no extra request), the photo counts from the `TagNode` counts
- **`src/pages/TagsPage.tsx`** (`/?page=tags`): the **Overview** (`TagOverview`); clicking a row opens the tag's **inner page** (back arrow, the tag path as the read-only title, a table of the rules assigning that exact path, the photo gallery, delete); there is no vocabulary editor and no path/name editing. The inner page lists `GET /api/rules`, toggles a rule with `PUT /api/rules/{id}`, deletes it with `DELETE /api/rules/{id}`, and **Apply to all photos** calls `POST /api/rules/apply`
- **`src/pages/GalleryPage.tsx`**: "Tags" entry in the gallery menu — the tree filters the gallery (checked tags → `GET /api/photos/ids`) and the matching photos are listed under the tree
- **`src/components/PhotoMetadata.tsx`**: tags accordion with chips; "Edit tags" opens the picker and **Save sends the whole list** in one `PUT /api/photos/{id}/tags`
- **`src/components/CustomSlideshowMenu.tsx`**: the free-text tag input was replaced by the hierarchical picker; the selection is still serialised as the `tags[]` query param
- React Compiler lint (`react-hooks/set-state-in-effect`) rejects synchronous `setState` in effects: fetch in promise callbacks, or derive the value (the `key` comparison pattern used for the fetched photo ids)

### Rules UI

- **`src/lib/rules.ts`**: the AST model matching the backend (`Definition`, `ScalarCondition`, `DetectionCondition`, `GroupCondition`, `MetricConstraint`) plus the draft (`RuleDraft`) and conversions (`emptyRule`, `toDraft`, `toPayload`, `countConditions`).
- **`src/lib/expression/`**: the **fully local** language — `tokens.ts` (tokenizer, UTF-16 spans, including `%` and the `f/` prefix unit), `parser.ts` (schema-aware: `and`/`or`, parentheses, `objects has [no] "label" [with metric op number[unit], ...]`, `path op value[unit]`, `path is [not] true|false`, `path in [..]`; a unit the schema declares is **required**, without a schema it stays optional), `printer.ts` (AST → canonical text, re-emitting units from the schema and `%` for metrics), `schema.ts` (validation against the served descriptor, including the 0–100 metric range), `units.ts` (known units, prefix detection), `hints.ts` (contextual hints: fields at a condition start, the field's operators, then its values/labels/metrics, filtered by the word being typed; text-like field hints fill in `path = ""` with the caret inside; a step keyword that is already typed — `objects has`, `objects has no`, `… with`, `field is`/`is not`/`contains`/`in`, a trailing `and`/`or` — advances to the next step even without a trailing space), `typing.ts` (typing aids: an operator picked from the hints arms unit filling for the number typed next, and only while the expression still has a parse error, so units never stack; space/comma steps over the unit, a closing quote is skipped, the first letter of a text value is quoted). It never calls the backend per keystroke. Vitest covers parse/print/validate/hints/typing (`npm test`).
- **`src/components/ExpressionEditor.tsx`**: transparent textarea over a syntax-coloured overlay (keywords, fields, strings, numbers, dates, units, operators); reports parse issues and pauses previews during IME composition. Under a focused editor it shows the contextual hint chips (`schema` + `values` props); clicking a chip or pressing Tab inserts the first hint at the caret, honouring the hint's caret offset. Printable typing goes through `typing.ts` (units, quotes).
- **`src/components/SchemaForm.tsx`**: the generated form — field/operator selects, value editors by kind, detection label + `confidence`/`surface` metrics, add/remove; labels, operators, metric bounds/step and suggestions all come from `GET /api/rules/schema` + `GET /api/rules/values` (fetched once when the editor opens). Number inputs show their unit (`%`, `f/`, `mm`…); new metrics start at the middle of the served range. Nested groups are round-tripped from the text; the form edits flat top-level conditions first.
- **`src/hooks/useRulePreview.ts`**: debounced (450 ms) preview with a **local-validity gate**, one request in flight, latest-wins coalescing, identical-definition suppression, and `POST /api/rules/preview`.
- **`src/components/RulePage.tsx`**: the editor — expression on top, generated schema form below, header (name/description/priority/enabled/revert/save) and the expected-matches panel; Save sends `POST /api/rules` or `PUT /api/rules/{id}`. The expression is always reprinted from the stored `definition` (percent, not the legacy fraction text) and again with units once the schema arrives; the expression text is then authoritative in the browser, and only a locally valid AST is ever sent.
- **`src/pages/TagsPage.tsx`**: opens `RulePage` from a tag's inner page; it no longer has a separate Rules tab.

### Help & documentation UI

- **`src/lib/markdownSlides.ts`**: `splitSlides(markdown)` splits a document on `---` lines outside fenced code blocks; Vitest covers CRLF, fences, empty slides.
- **`src/components/MarkdownSlidesDialog.tsx`**: one MUI dialog per document, `react-markdown` + `remark-gfm` mapped to theme typography/tables; bottom `‹` / `›` controls with a `current / total` counter, arrow-key navigation, scroll reset per slide; `initialSlide` selects `first` or `last`.
- **`src/App.tsx`**: Help button in the AppBar opens **Tutorial**, **Hardware & performance**, or **What's new**; version is fetched from `GET /api/about/version`, the last seen version lives in `localStorage["trailframe.seenVersion"]`, and What's new auto-opens at the last slide after a version change (then stores the version on close).
- **Content**: `trailframe/docs/tutorial.md`, `trailframe/docs/hardware.md` and `trailframe/docs/whats-new.md`; What's new keeps one slide per minor `0.X` release in ascending order (patch releases are folded into the minor slide).

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