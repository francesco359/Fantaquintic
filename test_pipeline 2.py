"""Test offline della pipeline (nessuna rete): python -m unittest discover -s tests"""
import importlib, json, os, random, shutil, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for d in ("scripts", "data"):
            shutil.copytree(REPO / d, self.tmp / d, ignore=shutil.ignore_patterns("history", "__pycache__"))
        shutil.copy(REPO / "config.json", self.tmp / "config.json")
        os.environ["FANTASUITE_ROOT"] = str(self.tmp)
        sys.path.insert(0, str(self.tmp / "scripts"))
        for m in ("update_fantasuite", "html_sources", "expectation_model"):
            sys.modules.pop(m, None)
        self.u = importlib.import_module("update_fantasuite")
        players = json.loads((self.tmp / "data/latest.json").read_text(encoding="utf-8"))["players"]
        rnd = random.Random(7)

        def lineup(noise):
            return [{"name": p["name"], "club": p["club"], "role": p["role"],
                     "starter": float(max(0, min(100, round((p["starter"] if p["status"] != "unavailable" else 90)
                                                            + rnd.uniform(-noise, noise)))))}
                    for p in players if rnd.random() < .85]
        self.recs = {"lineups_fantacalcio": lineup(10), "lineups_sosfanta": lineup(12), "lineups_gazzetta": lineup(25)}
        self.u.parse_source = lambda n, h: {"records": self.recs.get(n, []), "updated_at": None,
                                            "kind": "lineups" if n in self.recs else "unsupported"}
        self.u.fetch_with_retry = lambda url, **k: (b"x", "", 1, 1)

    def tearDown(self):
        sys.path.remove(str(self.tmp / "scripts"))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def status(self):
        return json.loads((self.tmp / "data/status.json").read_text(encoding="utf-8"))

    def test_second_run_with_same_input_changes_nothing(self):
        self.assertEqual(self.u.main(), 0)
        n = len(list((self.tmp / "data/history").glob("*.json")))
        self.assertEqual(self.u.main(), 0)
        self.assertEqual(self.status()["player_updates"], 0)
        self.assertFalse(self.status()["latest_rewritten"])
        self.assertEqual(len(list((self.tmp / "data/history").glob("*.json"))), n)

    def test_all_sources_down_keeps_data_and_fails(self):
        before = (self.tmp / "data/latest.json").read_text(encoding="utf-8")

        def down(url, **k):
            raise OSError("rete giù")
        self.u.fetch_with_retry = down
        self.assertEqual(self.u.main(), 3)
        self.assertEqual((self.tmp / "data/latest.json").read_text(encoding="utf-8"), before)

    def test_injured_player_not_revived_by_weak_lineup_signal(self):
        d = self.u.load(self.u.LATEST)
        injured = next(p for p in d["players"] if p["status"] == "unavailable")
        for recs in self.recs.values():
            recs.append({"name": injured["name"], "club": injured["club"], "role": injured["role"], "starter": 40.0})
        self.u.main()
        after = next(p for p in self.u.load(self.u.LATEST)["players"] if p["id"] == injured["id"])
        self.assertEqual(after["status"], "unavailable")

    def test_formations_are_complete_and_roles_match(self):
        self.u.main()
        f = self.u.load(self.u.LATEST)["recommended_formations"]
        for m, (d, c, a) in self.u.MODULES.items():
            x = f["best_by_module"][m]
            self.assertTrue(x["complete"])
            self.assertEqual([sum(1 for p in x["players"] if p["role"] == r) for r in "PDCA"], [1, d, c, a])
        self.assertEqual(len(f["best_global_433"]["players"]), 11)
        self.assertEqual(len(f["surprises_global_433"]["players"]), 11)


if __name__ == "__main__":
    unittest.main()
