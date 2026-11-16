"""Style inboxes: one .txt per style, only new reels, one re-learn per style, bad downloads skipped."""
import pytest
import yaml

from tripshots import inbox as I
from tripshots.util import ReelError


@pytest.fixture
def home(tmp_path, monkeypatch):
    for k, v in {"HOME": tmp_path, "STATE": tmp_path / "inbox.json", "LOCK": tmp_path / "inbox.lock",
                 "USER_STYLES": tmp_path / "styles", "BUILTIN_STYLES": tmp_path / "builtin"}.items():
        monkeypatch.setattr(I, k, v)
    (tmp_path / "styles").mkdir()
    (tmp_path / "builtin").mkdir()
    root = tmp_path / "inbox"
    I.setup(root)
    return root


def test_file_names_and_links():
    assert I.style_name("westcoast") == "westcoast"
    assert I.style_name("Calm sunsets") == "calm-sunsets"
    assert I.style_name("TripShots beach") == "beach"
    text = ("look https://www.instagram.com/reel/AbC_1-x/?igsh=zz\nhttps://instagram.com/reels/AbC_1-x/\n"
            "https://www.instagram.com/someone/reel/Q9/ and https://example.com/reel/X/")
    assert I.links(text) == [I.reel_url("AbC_1-x"), I.reel_url("Q9")]


def test_sync_learns_only_new_reels_once_per_style_and_skips_bad_downloads(home):
    I.USER_STYLES.joinpath("westcoast.yaml").write_text(yaml.safe_dump(
        {"name": "westcoast", "learned_from": ["https://www.instagram.com/reel/OLD1/?igsh=x"]}))
    (home / "westcoast.txt").write_text(f"{I.reel_url('OLD1')}\n{I.reel_url('NEW1')}?igsh=1\nhello\n"
                                        f"{I.reel_url('GONE')}\n")
    (home / "TripShots westcoast.txt").write_text(f"{I.reel_url('NEW1')}\n{I.reel_url('NEW2')}\n")
    (home / "notes.md").write_text(I.reel_url("MD"))
    learned = []

    def fetch(url, dest, *a):
        if "GONE" in url:
            raise ReelError("this reel is private")

    rep = I.sync(root=home, learn_fn=lambda refs, name, *a: learned.append((name, refs)), fetch_fn=fetch)
    assert list(rep["styles"]) == ["westcoast"]
    assert learned == [("westcoast", ["https://www.instagram.com/reel/OLD1/?igsh=x",
                                      I.reel_url("NEW1"), I.reel_url("NEW2")])]
    assert rep["styles"]["westcoast"]["skipped"] == [I.reel_url("GONE")]
    assert not I.LOCK.exists()
    assert "westcoast learned 2" in I.summary(rep)

    I.USER_STYLES.joinpath("westcoast.yaml").write_text(yaml.safe_dump(
        {"name": "westcoast", "learned_from": learned[0][1]}))
    for _ in range(I.GIVE_UP):   # nothing new; the failing reel is tried a few more times, then left alone
        learned.clear()
        I.sync(root=home, learn_fn=lambda refs, name, *a: learned.append(name), fetch_fn=fetch)
        assert learned == []
    assert I.load_state()["failed"]["GONE"]["n"] == I.GIVE_UP
    rep = I.sync(root=home, dry_run=True)
    assert rep["styles"]["westcoast"] == {"new": [], "skipped": [I.reel_url("GONE")]}


def test_a_new_file_makes_a_style_and_hand_made_styles_are_left_alone(home):
    I.BUILTIN_STYLES.joinpath("travel-diary.yaml").write_text("name: travel-diary\n")
    (home / "Beach days.txt").write_text(I.reel_url("B1"))
    (home / "travel-diary.txt").write_text(I.reel_url("T1"))
    learned = []
    rep = I.sync(root=home, learn_fn=lambda refs, name, *a: learned.append((name, refs)), fetch_fn=lambda *a: None)
    assert learned == [("beach-days", [I.reel_url("B1")])]
    assert "hand-made" in rep["styles"]["travel-diary"]["error"]


def test_a_failed_learn_is_retried_next_time(home):
    (home / "west.txt").write_text(I.reel_url("A"))

    def boom(*a):
        raise ReelError("usage limit")

    rep = I.sync(root=home, learn_fn=boom, fetch_fn=lambda *a: None)
    assert "usage limit" in rep["styles"]["west"]["error"]
    learned = []
    I.sync(root=home, learn_fn=lambda refs, name, *a: learned.append(refs), fetch_fn=lambda *a: None)
    assert learned == [[I.reel_url("A")]]


def test_missing_inbox_and_running_twice(home, tmp_path):
    assert "inbox setup" in I.sync(root=tmp_path / "nope")["hint"]
    I.LOCK.write_text("1")
    with pytest.raises(ReelError, match="running"):
        I.sync(root=home)


def test_watch_plist_runs_sync_when_the_folder_changes(tmp_path):
    xml = I.plist(tmp_path, 6, "chrome", None)
    assert "<string>inbox</string>" in xml and "<string>chrome</string>" in xml
    assert f"<string>{tmp_path}</string>" in xml and "WatchPaths" in xml and "<integer>21600</integer>" in xml
