# v0.1.x — First release

The first public Trailframe release.

- Automatic photo ingestion with EXIF capture.
- Multi-size thumbnails generated and cached per photo.
- Garmin Connect and GPX activities with trace maps.
- Activity, group, and custom slideshows.
- Self-hosted FastAPI server that also serves the web UI.

---

# v0.2.x — Easier deployment

- Support for running behind an Ingress with a custom root path.
- More reliable shutdown of the server and background services.
- Relative API and asset paths, so the UI works when mounted below a subpath.
- Packaging and dependency fixes for a clean install.

---

# v0.3.x — Reworked processing

The processing core was rebuilt around a shared thread pool.

- Dedicated database thread instead of blocking the event loop.
- One shared thread pool for scanners, maps, and other heavy work.
- Item-based scanners with a provider abstraction, making new photo sources possible.
- Compact activity trace storage and more reliable database writes.
- Custom slideshow URLs, kiosk auto-start, and slideshow map/control options.

---

# v0.4.x — Remote pipelines and smarter groups

- Remote pipelines: a host can delegate selected scanners to another Trailframe instance.
- Duplicate and location-issue groups in the gallery.
- GPS information now takes precedence when photos are linked to activities.
- Pipeline instances and a simpler thread-pool execution model.
- Scanner descriptions in the configuration UI.

---

# v0.5.x — Locations and storage

- Location boundaries are cached in a streaming JSONL format and queried with an R-tree.
- Bounded LRU caches keep ADM1/ADM2 geometry memory under control.
- Boundary download progress is reported through the event stream.
- Datetimes are stored as naive local wall-clock values end to end.
- Collapsible section panes and a more robust location estimate.
- Compatibility fix for SQLModel versions before 0.0.44.

---

# v0.6.x — Schema-driven rules and in-app help

- Rules are embedded on tags with a schema-driven AST; no separate rule table.
- New rule editor: fully local expression language (tokenizer/parser/printer/validator), syntax-coloured editor, generated form from the photo schema, debounced valid-only preview, and apply-to-library.
- Rules run in the pipeline after object detection and only add tags.
- Tag overview shows rule counts from the tag tree; rules move with renamed/moved tags and are removed with deleted tags.
- In-app Help menu with Tutorial and What's new (markdown slides), arrow-key navigation, and automatic What's new on version change.
- Status messages (uploads, activity imports, server shutdown) now appear as stacked, dismissible toasts instead of the footer message box.
- API docs at `/api/docs` and app version at `/api/about/version`.
- Default tags now seed on first start when the `tags` table is empty (no config flag).
- The default vocabulary gains `Processing/Tilt`, `Processing/Crop` and the COCO wildlife animals, and ships with ready-made rules that tag cats, dogs and wildlife only when a detection has `confidence > 85%` and `surface > 7%`, plus rules for straightened and cropped photos. They install once, never overwrite your edits, and are not brought back after you delete them.
- Rule conditions are data-agnostic: scalar fields compare directly, and any multi-valued field (`objects`, `processing`, `alternatives`) is filtered in brackets and quantified — `objects [label = "dog" and confidence >= 80%] has any`. A filter takes the full boolean grammar and binds every key to the same element; `has none`, `has one` and `has all` complement `has any`.
- Units are optional sugar (`80%`, `f/2.8`, `1200px`); `%` is the only meaningful one and is stored as a fraction, so `confidence >= 80%` compares against the stored 0–1 value. Old rules written for the previous detection syntax are skipped rather than migrated; recreate them with the new expressions.
- The rule editor fills in units and quotes as you type, steps over them with space or comma, and selecting a field inserts its quoted value with the caret inside.
- Photo storage now separates an untouched originals archive from derived processed alternatives; pipelines analyse the main alternative and EXIF always comes from the original.
- Alternatives are generated for the configured target sizes on import (WebP by default), with processing provenance recorded on the photo.
- Thumbnails are keyed by the original path and main target, so they survive reprocessing.
- Deleting a photo discards its processed files and thumbnails and moves the original to the trash.
- Automatic horizon straightening detects the dominant near-horizontal lines on a downscaled copy and corrects the processed alternatives only when the estimate is confident; the processing recipe is a two-stage tree (step, headline value, details) recording the angle, confidence, reference point, and crop. Hovering the Tilt step draws the detected horizon in red and the corrected target in green on the photo.
- Preprocessing is a chain of independent steps — tilt correction, crop, and rescale — each recorded in the processing recipe; a step added by a later release re-encodes existing photos once on the next pass.
- The JavaScript expression engine is a configuration toggle (`javascript_modules`) and defaults to off on machines with less than 1 GB of free memory.
- **Adjust processing** on a photo re-encodes its alternatives from the original: choose the output sizes and the main one, set the horizon to automatic, off or a manual angle with a crop mode, and optionally re-run the object and duplicate analysis. The original archive is never modified.
- The processing editor is now a full-app view: the original is shown large with the detected horizon overlaid, rotating live with the correction while the cropped-away area is shadowed, and the remaining crop and output sizes update as you edit. Each step — tilt, crop, rescale and analysis — has its own accordion in the side panel.
- Preprocessing adds optional exposure/gamma, white balance (Gray World or temperature/tint), contrast (S-curve or adaptive tone curve), CLAHE local contrast, vibrance, bilateral/non-local-means noise reduction, and unsharp masking. Each correction is configured under `processing`, runs only on derived alternatives, records its settings in the processing recipe, and re-encodes existing photos once when enabled later.
- The processing editor now exposes every correction as its own enable switch and parameter panel, with per-photo overrides sent through the reprocess API; disabling a configured correction keeps it off on later pipeline passes.
- The editor's preview applies the enabled corrections locally in the browser for instant feedback while retaining the exact tilt/crop overlay; the saved alternatives are still encoded by the backend.
- **Multi-edit** reuses the processing editor: nearby photos live in a collapsible right-pane accordion, ordered by capture time and auto-detected from stored YOLO object signatures, with a small colour/edge fingerprint as a fallback when a photo has no detections. A single `Time window` field (default `30 min`) controls the relative scan. Matching boxes are drawn over the thumbnails in multi-edit mode, green when shared with the active photo. Clicking a thumbnail previews that photo with its own parameters; local edits are kept while you move between thumbnails and marked with an `edited` chip until they are saved.
- Checking two or more photos enters multi-edit. The active thumbnail is the reference (outlined in pink); shared settings can come from it or from a barycentre of the selection (averaged numeric settings, most common methods, majority on/off). Saving asks for confirmation, then reprocesses each selected photo sequentially with its own parameters; partial failures stay visible. Perceptual hashes are still used for the full-library `Similar` group, but no longer for this editor selection.
- Hovering the gallery's **Objects** header now shows every detection at once: duplicate boxes collapse to the most confident one, partial overlaps stay separate, and the shared area uses only the highest confidence for its red fill opacity. Hovering a single object still highlights just that box with the original fixed fill.
