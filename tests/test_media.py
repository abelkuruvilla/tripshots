from conftest import clip, needs_ffmpeg

from tripshots import media


def test_time_from_filename():
    assert media.time_from_filename("DJI_20260501123000_0001_D.MP4") == "2026-05-01T12:30:00"
    assert media.time_from_filename("VID_20260501_124500.mp4") == "2026-05-01T12:45:00"
    assert media.time_from_filename("PXL_20260501_130000123.mp4") == "2026-05-01T13:00:00"
    assert media.time_from_filename("GX010042.MP4") is None


def test_equirect():
    assert media.is_equirect(5760, 2880)
    assert media.is_equirect(3840, 1920)
    assert not media.is_equirect(1920, 1080)
    assert not media.is_equirect(2560, 1280)  # too small to be a 360 export


def test_local_time_prefers_filename_for_tz_offsets():
    # camera metadata in UTC, file name in local time (+02:00): the file name wins
    assert media._local_time("2026-05-01T10:30:00", "DJI_20260501123000_0001_D.MP4").startswith("2026-05-01T12:30")
    # a gap that is no time-zone offset (7 min): keep the metadata
    assert media._local_time("2026-05-01T12:37:00", "DJI_20260501123000_0001_D.MP4").startswith("2026-05-01T12:37")


@needs_ffmpeg
def test_find_media_skips_raw_360_and_previews(footage):
    found = [p.name for p in media.find_media([footage])]
    assert not any(n.endswith((".LRV", ".insv")) for n in found)
    assert "GX010042.MP4" in found and "IMG_20260501_131500.jpg" in found


@needs_ffmpeg
def test_probe_flags_equirect(tmp_path):
    p = clip(tmp_path / "x.mp4", dur=1, size="2880x1440")
    assert media.probe_video(p)["equirect"] is True
