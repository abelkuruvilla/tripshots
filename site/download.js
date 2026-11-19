// Download buttons: find the visitor's system, then point every button at the file in the latest GitHub release.
// Without JavaScript, or if GitHub's API can't be reached, the links open the latest release page instead.
(function () {
  "use strict";
  var REPO = "abelkuruvilla/tripshots";
  var RELEASES = "https://github.com/" + REPO + "/releases/latest";

  // the installers Tauri names TripShots_<version>_<arch>.<ext> (rpm: TripShots-<version>-1.x86_64.rpm)
  var ASSETS = {
    mac: /_aarch64\.dmg$/,
    exe: /_x64-setup\.exe$/,
    msi: /_x64_en-US\.msi$/,
    appimage: /_amd64\.AppImage$/,
    deb: /_amd64\.deb$/,
    rpm: /\.x86_64\.rpm$/,
  };
  var PRIMARY = { mac: "mac", windows: "exe", linux: "appimage" };
  var NAMES = { mac: "Mac", windows: "Windows", linux: "Linux" };

  function detectOS() {
    var uad = navigator.userAgentData;
    var p = ((uad && uad.platform) || navigator.platform || "").toLowerCase();
    var ua = navigator.userAgent.toLowerCase();
    if (/iphone|ipad|ipod|android/.test(ua) || (uad && uad.mobile)) return "mobile";
    // iPadOS reports itself as a Mac; a Mac has no touch screen
    if (/mac/.test(p) && navigator.maxTouchPoints > 1) return "mobile";
    if (/mac/.test(p) || /mac os x/.test(ua)) return "mac";
    if (/win/.test(p) || /windows/.test(ua)) return "windows";
    if (/linux|x11/.test(p) || /linux/.test(ua)) return "linux";
    return null;
  }

  // Apple Silicon or Intel? Chromium says so directly; Safari and Firefox only through the graphics chip's name.
  function macIsIntel() {
    var uad = navigator.userAgentData;
    if (uad && uad.getHighEntropyValues) {
      return uad.getHighEntropyValues(["architecture"]).then(function (v) {
        return v.architecture === "x86" ? true : v.architecture === "arm" ? false : null;
      }, function () { return null; });
    }
    try {
      var gl = document.createElement("canvas").getContext("webgl");
      var ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
      var r = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : "";
      if (/apple m\d|apple gpu/i.test(r)) return Promise.resolve(false);
      if (/intel|amd|radeon|nvidia/i.test(r)) return Promise.resolve(true);
    } catch (e) { /* no WebGL */ }
    return Promise.resolve(null);
  }

  function each(sel, fn) { Array.prototype.forEach.call(document.querySelectorAll(sel), fn); }

  var os = detectOS();
  var hero = document.querySelector(".js-dl");
  var label = document.querySelector(".js-dl-label");
  var note = document.querySelector(".js-dl-note");

  if (os && os !== "mobile") {
    var card = document.querySelector('.platform[data-os="' + os + '"]');
    if (card) {
      card.classList.add("mine");
      card.parentNode.insertBefore(card, card.parentNode.firstChild);
    }
    label.textContent = "Download for " + NAMES[os];
    note.innerHTML = 'Free and open source. <a href="#download">Other systems</a>';
  } else {
    hero.setAttribute("href", "#download");
    if (os === "mobile") note.textContent = "TripShots runs on a computer: Mac, Windows or Linux. Open this page there to download it.";
  }

  if (os === "mac") {
    macIsIntel().then(function (intel) {
      if (!intel) return;
      label.textContent = "Download for Mac (Apple Silicon)";
      note.textContent = "This Mac looks like an Intel Mac. TripShots needs a Mac with Apple Silicon (M1 or newer).";
      var card = document.querySelector('.platform[data-os="mac"]');
      var warn = document.createElement("p");
      warn.className = "warn";
      warn.textContent = "This Mac looks like an Intel Mac, which TripShots doesn't support.";
      card.insertBefore(warn, card.querySelector(".btn"));
    });
  }

  fetch("https://api.github.com/repos/" + REPO + "/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (rel) {
      var urls = {};
      (rel.assets || []).forEach(function (a) {
        Object.keys(ASSETS).forEach(function (k) {
          if (!urls[k] && ASSETS[k].test(a.name)) urls[k] = a.browser_download_url;
        });
      });
      each("[data-asset]", function (a) {
        var u = urls[a.getAttribute("data-asset")];
        if (u) a.setAttribute("href", u);
      });
      if (os && PRIMARY[os] && urls[PRIMARY[os]]) hero.setAttribute("href", urls[PRIMARY[os]]);
      var v = document.querySelector(".js-version");
      if (v && rel.tag_name) {
        var when = rel.published_at ? new Date(rel.published_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "";
        v.textContent = "TripShots " + rel.tag_name + (when ? ", released " + when : "") + ".";
      }
    })
    .catch(function () { /* the links already open the latest release page */ });
})();
