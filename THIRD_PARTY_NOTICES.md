# Third-party notices

TripShots is MIT-licensed (see [LICENSE](LICENSE)). It includes, adapts or downloads the following.

## Included in this repository

**Fonts** in `tripshots/fonts/`, each with its licence file next to it:

| Font | Licence |
|---|---|
| Anton, Archivo Black, Bebas Neue, Caveat, DM Serif Display, Montserrat, Playfair Display, Space Mono | SIL Open Font License 1.1 (`*-OFL.txt`) |
| Permanent Marker | Apache License 2.0 (`PermanentMarker-LICENSE.txt`) |

**Adapted code.** Camera file-name time parsing, 360° footage detection and the Gemini "watch" approach (proxy
upload, moments with a peak, in-camera transitions) in `tripshots/media.py` and `tripshots/watch.py` were adapted
from [tripcut](https://github.com/divyankrahoria/tripcut):

```text
MIT License

Copyright (c) 2026 Divyank Rahoria

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The sound-design rules (what gets a sound, alignment, restraint) follow the `real-sound` skill of
[earshot](https://github.com/Leonxlnx/earshot) (MIT).

## Downloaded when you use a feature (not included)

| What | When | Licence |
|---|---|---|
| YuNet face detector (`face_detection_yunet_2023mar.onnx`, Shiqi Yu) | first face search | BSD 3-Clause (libfacedetection.train) / MIT (OpenCV Zoo) |
| SFace face recogniser (`face_recognition_sface_2021dec.onnx`) | first face search | Apache License 2.0 (OpenCV Zoo) |
| rembg + IS-Net model | first pop-out frame | MIT |
| HyperFrames 0.8.191 (HeyGen) | `./install.sh --maps` | Apache License 2.0 |
| GSAP 3.12.5 | `./install.sh --maps` | GSAP Standard "No Charge" License (free to use; not an open-source licence) |
| world-atlas 2.0.2 / sane-topojson 4.0.0 (Natural Earth data) | `./install.sh --maps` | ISC / MIT; Natural Earth data is public domain |
| earshot sound bank | `./install.sh --sound` | MIT |
| Sound effects from Openverse | `tripshots sounds --fetch`, sound design | CC0 / public domain by default; CC BY only if you allow it (credits are written) |

## Services

Place names and outlines come from [OpenStreetMap](https://www.openstreetmap.org/copyright) via Nominatim
(© OpenStreetMap contributors, ODbL); TripShots caches results and stays under Nominatim's one-request-per-second
policy. Reel downloads use [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense). Python dependencies are listed in
[`pyproject.toml`](pyproject.toml); each keeps its own licence.

Music you use and reels you download remain under their own copyright. Only post what you have the right to post.
