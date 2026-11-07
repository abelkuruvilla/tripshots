import numpy as np

from tripshots import people


def _emb(seed, noise=0.0, base=None):
    rng = np.random.default_rng(seed)
    v = (base if base is not None else rng.normal(size=128)) + noise * rng.normal(size=128)
    return list(v / np.linalg.norm(v))


def test_names_and_matching(monkeypatch, tmp_path):
    monkeypatch.setattr(people, "PEOPLE", tmp_path / "people.json")
    me = np.random.default_rng(1).normal(size=128)
    people._add("me", [_emb(2, 0.3, me), _emb(3, 0.3, me)], ["a.jpg", "b.jpg"], aliases=["Abel"])
    assert people.canonical("I") == "me" and people.canonical("abel") == "me" and people.known("Me")
    faces = [{"emb": _emb(9, 0.3, me)}, {"emb": _emb(42)}]
    got = people.identify(faces)
    assert got[0][0] == "me" and got[1][0] == ""


def test_who_is_in_and_discover(monkeypatch, tmp_path):
    monkeypatch.setattr(people, "PEOPLE", tmp_path / "people.json")
    monkeypatch.setattr(people, "CLUSTERS", tmp_path / "clusters.json")
    monkeypatch.setattr(people, "cluster_sheet", lambda saved, out=None: tmp_path / "sheet.jpg")
    me, mom = np.random.default_rng(1).normal(size=128), np.random.default_rng(2).normal(size=128)
    fake = {"p1": [{"emb": _emb(3, 0.3, me), "px": 100, "box": [0, 0, .1, .1]}],
            "p2": [{"emb": _emb(4, 0.3, mom), "px": 90, "box": [0, 0, .1, .1]}],
            "p3": [{"emb": _emb(5, 0.3, mom), "px": 80, "box": [0, 0, .1, .1]},
                   {"emb": _emb(6, 0.3, me), "px": 70, "box": [0, 0, .1, .1]}]}
    monkeypatch.setattr(people, "index", lambda recs, workers=4: {r["path"]: fake[r["path"]] for r in recs})
    recs = [{"path": p, "kind": "photo"} for p in fake]
    people._add("me", [_emb(7, 0.3, me)], ["x.jpg"])
    assert people.who_is_in(recs) == {"p1": ["me"], "p2": [], "p3": ["me"]}
    d = people.discover(recs)
    assert [c["files"] for c in d["clusters"]] == [2]          # mom, in p2 and p3
    people.name_cluster("c1", "mom")
    assert people.who_is_in(recs)["p3"] == ["me", "mom"]
