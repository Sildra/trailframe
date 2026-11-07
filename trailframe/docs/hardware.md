# Hardware & performance

Trailframe runs its heavy work in the background, but some scanners need a lot of memory. On startup it measures how much RAM is currently free and turns off features that would not fit on a machine that is already short on memory.

---

## What is detected

The free (available) physical memory is read once at startup:

- **Windows** — `GlobalMemoryStatusEx` (`ullAvailPhys`)
- **Linux** — `MemAvailable` from `/proc/meminfo`
- **macOS** — free/inactive/speculative/purgeable pages from `vm_stat`

When less than **1 GB** is free, scanners marked as *heavy* are disabled automatically:

- **Object** — object detection with a YOLO model (the AI scanner). It loads a model into memory and is the most demanding step of the pipeline.

Only scanners that exist the first time detection runs are affected. If a later release adds a new heavy scanner, it is evaluated on the next start; scanners you enabled or disabled yourself stay as you left them.

---

## Re-enabling a heavy scanner

1. Open **Configuration**.
2. Select the **scanners** section.
3. Turn the scanner back on.

The change is saved with the rest of the configuration and is never overridden again by the memory check.

If enough memory is free but the scanner was disabled earlier, enable it the same way and, for the object scanner, download the model from the model chooser.

---

## Where the result is kept

The detection result is stored only in the generic `app_data` table (key `hardware_detection`): the measured free memory, the threshold, the heavy scanners that existed during detection, and the scanners the check disabled. It is internal and not exposed through the API.

This page is opened from **Help → Hardware & performance**.
