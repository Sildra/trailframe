# Engineering

* None

# Core-features

* Add features to processing service
  * Tilt enhancement
  * Others
* Add IA-class scanners (need a pipeline that process by IA instead of by Photo)
  * Scenic
  * Wildlife
    * Flora
    * Fauna
  * Persona

# Frontend

* Add Tool to edit and correct the processing algorithms applied to photo
  * Open from the photo metadata Processing accordion
  * Outputs: alternative sizes and main target
  * Horizon: automatic, off or manual angle, with crop mode
  * Re-run analysis (objects, perceptual hash, thumbnails)
  * `POST /api/photos/{id}/reprocess`

# Not planned but possible

* Photo sources (framework should already be extensible for this)
  * NAS
  * Synology
  * Google Photo
  * Immich (totally a concurrent ? :p )
* Activity sources
  * Stravia
  * ?
