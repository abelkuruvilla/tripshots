import pytest

from tripshots import encode


@pytest.fixture(autouse=True)
def _forget_choice():
    """These tests fake the encoders: don't let their pick leak into later tests that really render."""
    yield
    encode._choice = None


def test_software_when_asked(monkeypatch):
    monkeypatch.setenv("TRIPSHOTS_ENCODER", "software")
    c = encode.choose(force=True)
    assert c["key"] == "software" and "libx264" in encode.args("final")


def test_auto_falls_back_when_no_hardware_works(monkeypatch):
    monkeypatch.setenv("TRIPSHOTS_ENCODER", "auto")
    monkeypatch.setattr(encode, "_works", lambda args: False)
    assert encode.choose(force=True)["key"] == "software"


def test_auto_takes_hardware_that_passes_its_test(monkeypatch):
    monkeypatch.setenv("TRIPSHOTS_ENCODER", "nvenc")
    monkeypatch.setattr(encode, "_listed", lambda: {"h264_nvenc", "libx264"})
    monkeypatch.setattr(encode, "_works", lambda args: True)
    c = encode.choose(force=True)
    assert c["key"] == "nvenc" and "h264_nvenc" in encode.args("segment")
    encode.disable("driver crashed")
    assert not encode.using_hardware()
    encode.choose(force=True)  # leave a clean state for other tests


def test_software_profiles_keep_quality():
    assert encode.SOFTWARE["final"][encode.SOFTWARE["final"].index("-crf") + 1] == "17"
