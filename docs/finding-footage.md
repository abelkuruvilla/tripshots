# Finding footage

Instead of pointing TripShots at a folder, you can ask for footage by **place**, **dates** and **people**. A search
saves a *selection* (`sel:<id>`) that `make`, `scan` and `clone` accept anywhere a folder is allowed.

```bash
tripshots footage ~/Pictures/Trips /Volumes/SSD/Footage      # once: where to search
tripshots find --place "Yellowstone National Park" --sheet
tripshots make sel:1a2b3c4d -m song.mp3
```

## The catalog

TripShots reads each file's capture time, GPS and dimensions once and keeps them in its library (keyed by file
content, so moving or renaming files doesn't matter). After the first scan of a folder, searches only check file
sizes and dates.

- **Capture time** comes from EXIF / QuickTime metadata, or from the file name (`DJI_20260501123000`, `VID_20260501_124500`, `PXL_…`) when the camera wrote none or wrote UTC.
- **GPS** comes from EXIF (photos) and the QuickTime location tag (iPhone, DJI and most phones). Many action cameras and some exports have none.

## Trips

```bash
tripshots trips
```

Groups everything into trips: a new trip starts after a gap of more than 2 days, or after a jump of more than 500 km
overnight. For each trip you get the dates, the number of days, photo and video counts, the main places (named from
GPS), the main folders, and the places of each day. Use it to find out what "last summer" or "the Iceland trip"
refers to.

## Search options

| Option | Meaning |
|---|---|
| `--place NAME` | A real place: `"Yellowstone National Park"`, `Lisbon`, `"Moraine Lake"`. Be specific. |
| `--near LAT,LON --radius KM` | Around a point instead of a name |
| `--people me mom` | These people must all be in the photo or clip (`--any-people`: any of them) |
| `--since / --until YYYY-MM-DD` | Date range (inclusive) |
| `--kind photo\|video` | Only photos or only videos |
| `--text WORDS` | Words that must appear in the folder, file or place name ("wedding", "day 3") |
| `--only-matching` | Don't add same-day clips without GPS (see below) |
| `--sheet` | Also draw a contact sheet of what was found |
| `--list` | Also print every file |
| `--name LABEL` | Name the selection (used in the reel's file name) |

The result says how many photos and videos were found, which days, which places and people, how each file matched
(`gps`, `folder`, `place name`, `same day, no GPS`), and notes such as what the place name resolved to. Selections
are saved in `~/.tripshots/selections/` and can be reused.

### How places match

A file matches a place when any of these is true:

1. **Its GPS is inside the place's outline.** The outline comes from OpenStreetMap (one search per place name,
   cached), so "Yellowstone National Park" is the park's actual boundary, not a circle around a point. Places that
   OpenStreetMap only knows as a point use their bounding box, or 3 km around the point.
2. **The place name is in the folder or file name** ("Trips/Yellowstone 2025/…").
3. **The place name is in the file's place name**, from earlier reverse-geocoding (location titles, trips).

**Same-day clips.** Phones with location off, GoPros and many cameras record no GPS. With a place (or `--near`) search, files
without GPS taken on the same day as matching files, between the first and last matching file of that day
(±2 hours), are added too. Files whose GPS puts them somewhere else (more than 50 km away) are not. Use
`--only-matching` to turn this off.

## People

Faces are found and recognised **on your computer** with OpenCV's YuNet face detector and SFace face recogniser.
The models (38 MB) are downloaded once into `~/.tripshots/models` and checked against fixed SHA-256 hashes. No photo,
frame or face is uploaded anywhere.

```bash
tripshots people add me selfie1.jpg selfie2.jpg portrait.jpg   # 2-5 photos where your face is the biggest
tripshots people discover                                       # groups everyone else into c1, c2, ... + a sheet
tripshots people name c2 mom
tripshots people list
tripshots people forget mom
```

- **Adding a person** uses the largest face in each photo. Photos with two faces of similar size are skipped,
  because it isn't clear which one is meant. Photos from different days, light and angles work best.
- **Discover** looks at every face that matches nobody yet and groups similar faces into clusters, keeping those
  seen in at least two files. Open the sheet (`~/.tripshots/people/clusters.jpg`), see who is who, and name them.
- `me`, `I`, `myself` all mean the user. People can have aliases.
- Photos are checked as they are; videos are checked at 4 frames spread over the clip. Faces smaller than 40 pixels
  (with the image scaled to 1600 px on its long side) are ignored, because they're too small to recognise reliably.
- A face counts as a person when its similarity to any of that person's reference faces is at least 0.40 (SFace's
  own suggested threshold is 0.363). In tests, photos of the same person scored about 0.8 and different people
  below 0.3.
- Faces are computed once per file and cached in `~/.tripshots/library/faces/`. The first search with `--people`
  over a big library takes a while; later ones are instant. Narrow big searches with a place or dates first
  (searches over more than 4,000 files with `--people` are refused).

**Limits.** Recognition is not perfect: profiles, sunglasses, hats, small faces in wide shots, and children
growing up between trips can all be missed. Check the contact sheet. Face data is personal data: see
[Privacy](privacy.md).
