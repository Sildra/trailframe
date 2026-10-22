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

- **Start order**: `ThreadPoolService` → `DatabaseService` (creates tables) → `PhotoService` → `TagService` → `TagRuleService` → `PipelineService` → `FolderService` → `ThumbnailService` → `MapService` → `GarminConnectService` → `GpxService` → `ActivityService` → `LocationService` → `TileService` → `StatisticsService` → `DuplicatesService` (order must satisfy `_requires`: DB→TP, Photos→DB, Tag→DB, TagRule→DB+Tag, Pipeline→DB, Folder→DB+Pipeline, Thumbnail→Photos, Garmin→DB+TP, Gpx→DB, Activity→DB+TP+Garmin+Map, Location→DB+TP, Tile→TP, Statistics→DB, Duplicates→DB+TP)

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
- **No tag scanner**: tags are never inferred from the photo content (not from the YOLO objects, not from the EXIF data) — they are only assigned by the user through the tag API, or by a user-defined **rule** (see Rules)

### Tags

- **Model** (`models/tag.py`): `Tag` table (`tags`) — `id`, `name`, `path` (unique, slash-separated full path), `parent_id`, `depth`, `description`; `TagNode` is the API DTO (`count` = photos with exactly this path, `total` = incl. descendants, `children`)
- **TagService** (`services/photos/tag_service.py`): owns the registry *shape*; `Photo.tags` (JSON list of full paths) owns the *assignments* — one source of truth per concern, no tag scanner
  - Paths: `normalize()` (trim segments, single `/`), `name_of()`, `parent_path()`, `ancestors()`, `depth_of()`; `MAX_DEPTH = 10` levels
  - `ensure_paths()` registers a path **and its ancestors** (missing parents are created)
  - `seed_defaults()` installs `DEFAULT_TAGS` (155 nodes / 12 roots: Activity, Architecture, Landscape, Animals, People, Food, Nature, Transport, Object, Event, Document, Quality); guarded by the `tags.seeded` config flag (set to `true` after the first install) so user deletions survive restarts
  - `match()` / `match_exact()`: SQL conditions over `json_each(COALESCE(photo.tags,'[]'))` — `value = :path OR value LIKE :path || '/%'` (exact + descendants), `mode` = `any`/`all`
  - `sync(payload)`: bulk vocabulary write (one request carries the whole tree). Diff = rename (by `id`) → keep → cascade delete → create → describe; a renamed tag moves its descendants **and** the photos carrying them; a deleted parent kills its whole subtree even if the payload still lists a descendant
  - `delete(tag_id)`: cascade delete of a tag + descendants, stripping them from the photos
  - `set_photo_tags(photo_id, paths)` replaces the whole list of a photo's tags (one call, not incremental)
- **Photo filters**: `GET /api/photos?tags=&tags_mode=any|all&include_descendants=true` and `GET /api/photos/ids` (ids only, used by the gallery/slideshow); `GET /api/photos/custom?tags=` keeps the AND semantics

### Rules

- **Model** (`models/tag_rule.py`): `TagRule` table (`tag_rule`) — `id`, `name`, `enabled`, `priority`, `description`, `conditions` (JSON), `tags` (JSON list of full paths)
- **Rule shape**: `{name, enabled, priority, description, conditions: {operator: "and"|"or", rules: [...]}, tags: [...]}`
  - A leaf condition is `{field, match_label?, operator, value?, constraints?}` — `field` names a metadata field, `operator` is one of the catalog's operators, `value` the compared value
  - Object conditions carry `match_label` (the detected label) and `constraints` — `{confidence: {gte: 0.8}, surface: {gte: 0.1}}`
  - `surface` = **share of the image area** (box w × h ÷ photo pixel area), so `0.10` = the object covers 10% of the frame; the pixel size comes from the EXIF `ExifImageWidth`/`ExifImageHeight` (orientation 5–8 swaps the axes) — there are no width/height columns on `Photo`
- **TagRuleService** (`services/photos/tag_rule_service.py`): owns the rule evaluation
  - **In-memory cache**: the enabled rules live in `TagRuleService._rules`, loaded at `_start` and refreshed after every CRUD write — so `RulesScanner` evaluates a `Photo` with **no database round-trip**, like every other scanner
  - **Field catalog** (`fields()`): objects (label/confidence/surface), EXIF (make, model, lens, ISO, aperture, focal length, exposure), image size/orientation, location/country, date, filename, file size, favorite, current tags, scanners, `scores.brisque`; each field declares its `kind` and the operators it offers (`OPERATORS`)
  - `validate()` rejects an unknown field, an unknown operator or a malformed condition; `MAX_RULES = 200`, `MAX_CONDITIONS = 20`
  - `tags_for_photo(photo)` / `matching_tags(photo, rule)` — the evaluation; `test_rule(rule, limit)` is a **read-only preview** against the library (capped at `TEST_SCAN_LIMIT = 5000` photos)
  - `apply_all()` — re-applies every enabled rule to the whole library (add-only), the counterpart of the scanner for the photos scanned before a rule existed
  - Assigned tag paths are registered in the vocabulary through `TagService.ensure_paths`
- **RulesScanner** (`services/scanners/rules_scanner.py`): a standard scanner, registered in `SCANNER_DEFINITIONS` and in `BasicPipeline` **after** `Object` (so the detections exist) and **before** `Database` (so the tags are persisted). Gates on `"Rules" not in photo.scanners`, like `ObjectScanner`. **Add-only**: it never removes a tag, so a tag set by hand is never taken away
- **API** (`api/tag_rules.py`): `GET /api/tag-rules` (list), `POST /api/tag-rules` (create), `GET/PUT/DELETE /api/tag-rules/{id}`, `GET /api/tag-rules/fields` (the builder catalog), `POST /api/tag-rules/test` (preview a draft), `POST /api/tag-rules/apply` (apply to the whole library)

### Database & Storage

- **DB models**: SQLModel classes in `trailframe/models/` (converter classmethods, e.g. `GarminActivity.to_activity`); tables auto-created at startup, no migrations

- **Thumbnails** (`photos/thumbnail_service.py`): multi-size via `general.thumbnail_sizes` (default `[160, 400]`); files at `{safe_filename[:2]}/{safe_filename}_{file_size}_{size}.webp` (fallback `{safe_filename}_{size}.webp`); `generate_all` writes all; `exists` = all present; `select_size` picks lowest ≥ preferred when ≤ 2×preferred else highest below; `GET /api/photos/{id}/thumbnail?size=<p>`

- **Location boundaries cache** (`map/location_service.py`): `maps/_cache/*.jsonl` — JSON Lines, geometry as base64 WKB; `_read_entries`/`_write_entries` stream line-by-line (never a whole-file parse — the old array format peaked at file+parsed structure, measured 311 MB for `adm0`); unparseable/empty file = cache miss → re-download; superseded `.json` array caches are ignored and deleted on rewrite (no retrocompat); ADM0 download is strictly sequential (convert-to-shapely-and-drop per country, never parallel); `_adm0` resident, `_adm1`/`_adm2` LRU-bounded (`_ADM_CACHE_SIZE`, 16); `_find`/wireframe prefilter use `STRtree`; `_timed_load` logs duration/traced-peak/geometry-size at DEBUG (`LocationService` logger)

- **Favorites**: `Photo.is_favorite` (`_add_missing_columns`); `PUT /api/photos/{id}/favorite`, `GET /api/photos?favorites=true`, `GET /api/photos/favorites`

- **Deletion** (`api/photos.py`): move source to `general.trash_folder` via `FolderService.delete()`, remove thumbnail, delete DB row

### API Endpoints

- **Tags** (`api/tags.py`): `GET /api/tags` → the registry tree (`TagNode[]`); `PUT /api/tags` → replace the whole vocabulary in one request (`{"tags": [{id, path, description}]}`) and return the new tree; `DELETE /api/tags/{id}` → cascade delete of a tag and its descendants
- **Photo tags** (`api/photos.py`): `PUT /api/photos/{id}/tags` → replace the tags of a photo with the given list (`{"tags": [...]}` → `{id, tags}`); `GET /api/photos/ids` → the ids of the photos matching the filters (tags/favorites)

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

### Tags UI

- **`src/lib/tags.ts`**: path helpers (`tagName`, `tagParent`, `isTagUnder`, `normalizeTagPath`, `sanitizeTagName`) and draft operations on the flat `TagEntry[]` model (`{id, path, description}` — exactly the bulk payload): `flattenTags`, `buildTagTree` (tree derived from the paths), `renameTag`, `moveTag`, `addTag`, `removeTag`
- **`src/components/TagTree.tsx`**: hand-rolled recursive tree on MUI primitives (no `@mui/x-tree-view`); `checkable` shows the checkboxes, `filter` keeps the matching nodes and their ancestors
- **`src/components/TagPicker.tsx`**: dialog with a searchable tree + "new tag path" field (missing parents are created server-side); used by the photo metadata and the custom slideshow menu
- **`src/pages/TagsPage.tsx`** (`/?page=tags`): vocabulary editor — the draft is the flat entry list, the tree is derived from it, and **Save sends the whole vocabulary in one `PUT /api/tags`**; renaming/moving a tag updates its descendants locally; the delete confirmation shows the descendant and photo counts (the cascade is applied on save)
- **`src/pages/GalleryPage.tsx`**: "Tags" entry in the gallery menu — the tree filters the gallery (checked tags → `GET /api/photos/ids`) and the matching photos are listed under the tree
- **`src/components/PhotoMetadata.tsx`**: tags accordion with chips; "Edit tags" opens the picker and **Save sends the whole list** in one `PUT /api/photos/{id}/tags`
- **`src/components/CustomSlideshowMenu.tsx`**: the free-text tag input was replaced by the hierarchical picker; the selection is still serialised as the `tags[]` query param
- React Compiler lint (`react-hooks/set-state-in-effect`) rejects synchronous `setState` in effects: fetch in promise callbacks, or derive the value (the `key` comparison pattern used for the fetched photo ids)

### Rules UI

- **`src/lib/rules.ts`**: the rule draft model (`RuleDraft`, `RuleCondition`, `RuleConstraint`) and its conversions — `emptyRule`, `toDraft` (stored rule → editable draft), `toPayload` (draft → API body), `groupFields`, `findField`, `fieldOperators`, `describeCondition`, `describeRule`
- **`src/components/RuleBuilder.tsx`**: the assisted builder — a metadata field select (grouped by kind), an operator select, the detected-object label plus its `confidence`/`surface` constraints, add/remove condition rows, the and/or toggle, and the tag chips a rule assigns
- **`src/components/RulePage.tsx`**: the rule list (name, summary, priority, enable switch, edit/delete) next to the builder; **Test** previews the draft against the library (`POST /api/tag-rules/test`), **Save** creates/updates the rule, **Apply to all photos** re-applies every enabled rule to the whole library (`POST /api/tag-rules/apply`)
- **`src/pages/TagsPage.tsx`**: the **Rules** tab (alongside Overview and Vocabulary) renders `RulePage`; it receives the vocabulary draft so the builder can suggest the existing tag paths

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