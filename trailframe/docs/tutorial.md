# Welcome to Trailframe

Trailframe is a self-hosted photo gallery for people who move. It keeps photos and GPS activities side by side, linked by time and place.

Use the arrows at the bottom to move between slides, or the left and right arrow keys.

---

## Gallery

The Gallery is the main view of your library.

- Uploaded photos are archived in the originals folder and preprocessed automatically for display and analysis.
- Filter by date range, group, location, tags, and favorites.
- Open a photo to see its metadata: camera, lens, exposure, location, and the activities it belongs to.
- Mark photos as favorites to find them again quickly.

---

## Activities

Activities come from Garmin Connect or GPX files.

- Every activity gets a trace map.
- Photos taken during the activity are shown next to it.
- Open the map to select traces and see distance, duration, and start time.
- Use the activity slideshow to play the photos together with the route.

---

## Slideshows

Slideshows can be started from an activity, a group, or a custom selection.

- Custom slideshows support date ranges, groups, locations, tags, randomization, and favorites-only.
- Thumbnail mode renders slides from cached thumbnails, which is smoother for large libraries.
- The standalone `slideshow.html` entry can be used as a kiosk display.
- Activity photos can be exported as a ZIP archive.

---

## Tags

Tags are hierarchical and are assigned by you.

- Open **Tags** to see the vocabulary and the number of photos using each tag.
- Select a tag to see its photos, its rules, and to apply those rules to the library.
- In a photo's metadata, choose **Edit tags** to assign one or more tag paths.
- In the gallery, the tag tree filters the photos shown below it.

---

## Rules

Rules assign tags automatically from photo metadata and detected objects.

Rules live on the tag they assign. Open a tag and create a rule from there.

- Write the condition in the expression editor, or use the generated form below it.
- Use preview to check how many photos match before saving.
- A rule can test EXIF values, image dimensions, location, dates, tags, and object detections.
- After saving, **Apply to all photos** runs the enabled rules over the existing library.

---

## Tools

The **Tools** page contains the operational views.

- **Scanners** lets you force selected scanners to run again, for example after changing thumbnail sizes.
- **Map** shows all photos and activity traces on one map.
- **Statistics** shows scanner throughput, storage usage, and process memory.

---

## Configuration

The **Configuration** page edits the same `config.yaml` the server uses.

- Each section maps to a configuration branch; change values and press **Save**.
- Pipelines are configured here as well: choose which scanners run and in which order.
- **About** lists the installed packages and their versions.

Use the Help button in the top bar to reopen this tutorial or read the release highlights.
