"""Borrowing the Instagram login from a browser: clear reasons when it can't, auto picks the logged-in one."""
import sqlite3
import sys

import pytest

from tripshots import browsercookies as bc
from tripshots.util import ReelError

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="uses the Linux browser folders")


def _chrome_db(path, cookies):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('version', '24')")
    db.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, path TEXT, "
               "expires_utc INTEGER, is_secure INTEGER)")
    for host, name, value in cookies:
        db.execute("INSERT INTO cookies VALUES (?, ?, ?, ?, '/', 0, 1)", (host, name, value, b""))
    db.commit()
    db.close()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    bc._cache.clear()
    return tmp_path


def test_reasons(home):
    assert bc.check("brave")["status"] == "not_installed"
    (home / ".config/BraveSoftware/Brave-Browser/Default").mkdir(parents=True)
    (home / ".config/BraveSoftware/Brave-Browser/Default/Preferences").write_text("{}")
    st = bc.check("brave")
    assert st["status"] == "no_store" and "Default" in st["detail"]
    with pytest.raises(ReelError, match="no cookie database"):
        bc.cookie_file("brave")


def test_not_logged_in_then_auto_finds_the_logged_in_browser(home):
    _chrome_db(home / ".config/BraveSoftware/Brave-Browser/Default/Network/Cookies",
               [(".instagram.com", "csrftoken", "x")])
    _chrome_db(home / ".config/google-chrome/Profile 1/Cookies",
               [(".instagram.com", "sessionid", "abc"), (".instagram.com", "csrftoken", "y"),
                (".example.com", "other", "z")])
    with pytest.raises(ReelError, match="isn't logged in to Instagram"):
        bc.cookie_file("brave")
    path, label = bc.cookie_file("auto")
    assert label == "Chrome"
    text = open(path).read()
    assert "sessionid" in text and "example.com" not in text      # only Instagram's cookies are handed over
    assert oct(__import__("os").stat(path).st_mode)[-3:] == "600"


def test_unknown_browser(home):
    with pytest.raises(ReelError, match="unknown browser"):
        bc.cookie_file("netscape")
