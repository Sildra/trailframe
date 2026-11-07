# Engineering

* RAM detection 1st run to disable AI or heavy features, link to markdown renderer.
  * Mark Scanners as heavy intensive and add in generic table which ones were existing during detection to detect new ones.
* DB-migration in case DB need a non PK/FK/Table migration
  * Manually migrate existing DB for now (only me as the user, avoid boilerplate)

# Core-features

* Add UploadPipeline (destructive processing)
  * Reduce file size when above threshold (DownsizeScanner)
  * Enhance image with auto algorithm (maybe a single scanner for everything, to work on full scale image)
* Add IA-class scanners (need a pipeline that process by IA instead of by Photo)
  * Scenic
  * Wildlife
    * Flora
    * Fauna
  * Persona

# Frontend

* Switch text message box to toast
* Add a Markdown slideshow renderer (What's new, configuration help, ...)


# Not planned but possible

* Photo sources (framework should already be extensible for this)
  * NAS
  * Synology
  * Google Photo
  * Immich (totally a concurrent ? :p )
* Activity sources
  * Stravia
  * ?
