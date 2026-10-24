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
- API docs at `/api/docs` and app version at `/api/about/version`.
- Default tags now seed on first start when the `tags` table is empty (no config flag).
