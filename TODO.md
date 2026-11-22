# Engineering

* None

# Core-features

* [x] Add features to processing service (implemented as opt-in processors under `trailframe/services/processors/`):
  Enhancement	Algorithm
  Exposure correction	Exposure compensation, gamma
  Contrast	Adaptive tone curve, S-curve
  White balance	Gray World, temperature/tint
  Local contrast	CLAHE
  Vibrance	Adaptive saturation in perceptual color space
  Sharpening	Unsharp Mask
  Noise reduction	Bilateral / Non-Local Means
* Add IA-class scanners (need a pipeline that process by IA instead of by Photo)
  * Scenic
  * Wildlife
    * Flora
    * Fauna
  * Persona

# Frontend

* None

# Not planned but possible

* Photo sources (framework should already be extensible for this)
  * NAS
  * Synology
  * Google Photo
  * Immich (totally a concurrent ? :p )
* Activity sources
  * Stravia
  * ?
