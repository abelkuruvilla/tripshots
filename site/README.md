# tripshots.app

The project's website: one static page, no build step, no framework, no trackers.

```
index.html      the page
style.css       the desktop app's tokens (desktop/src/app.css): graphite, ember accent, mono timecode
download.js     finds the visitor's system and points the buttons at the latest release's files
fonts/          Instrument Sans and Geist Mono (OFL, licences beside them), served from here, not Google
images/         screenshots (copies of docs/images, max 1600 px wide), logo, icons
media/reel.mp4  the hero clip: four shots of a real reel with nobody in them, no sound, 960 px (keep it under about 3 MB)
_headers        Cloudflare Pages caching for fonts, images and the clip
```

**Downloads.** `download.js` asks GitHub's API for the latest release and matches the installers by name
(`TripShots_<v>_aarch64.dmg`, `_x64-setup.exe`, `_x64_en-US.msi`, `_amd64.AppImage`, `_amd64.deb`,
`TripShots-<v>-1.x86_64.rpm`). If a release changes those names, change `ASSETS` there. Without JavaScript, or when
the API can't be reached, every button opens the latest release page. The visitor's own system is listed first and
named on the main button; an Intel Mac gets a warning (the app is Apple Silicon only); phones are told to open the
page on a computer. Every release also carries copies under fixed names (`TripShots-mac.dmg`,
`TripShots-windows-setup.exe`, `TripShots-windows.msi`, `TripShots-linux.AppImage`, `.deb`, `.rpm`), so
`https://github.com/abelkuruvilla/tripshots/releases/latest/download/TripShots-mac.dmg` is a link that never changes.

**Look at it locally:** `python3 -m http.server 8000 --directory site`, then open http://127.0.0.1:8000.

**Publishing.** Cloudflare Pages builds straight from GitHub; there is no workflow in this repository. Every push to
`main` that touches `site/` goes live in about a minute, and every pull request gets its own preview link. A new
release needs no deploy. One-time setup in the Cloudflare dashboard:

1. Workers & Pages > Create > Pages > **Connect to Git**, pick `abelkuruvilla/tripshots`.
2. Production branch `main`; Framework preset **None**; Build command empty (or `exit 0`); Build output directory
   `site`. Save and Deploy.
3. The project's Settings > Build > **Build watch paths**: include `site/*`, so changes elsewhere don't redeploy.
4. Custom domains > **Set up a custom domain**: `tripshots.app` (and `www.tripshots.app` if wanted). With the domain's
   DNS on Cloudflare the records are added for you; otherwise add the CNAME it shows at your registrar.
