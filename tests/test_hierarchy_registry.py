"""Identity-locked BS0 HW maps; future routing is never phantom execution."""
import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from runner_riddle.hierarchy_registry import HierarchyRegistry, HierarchyError


def key(i):
    return base64.urlsafe_b64encode(bytes([i % 255 + 1]) * 32).decode().rstrip("=")


class HierarchyRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = Path(self.tmp.name)
        self.registry = HierarchyRegistry(p / "router-hw.sqlite",
                                          p / "sc0db.sqlite3", p / "gm0db.sqlite3")

    def test_reserved_hw0_to_hw4_and_unique_hermes_pairing(self):
        self.assertEqual([self.registry.hardware(i)["state"] for i in range(5)],
                         ["reserved"] * 5)
        self.assertEqual(self.registry.hardware(5)["state"], "unallocated")
        first = self.registry.bind_hermes("hermes-install-01", key(1))
        self.assertEqual(first["hw"], 2)
        self.assertEqual(first["node_point"], 3)
        self.assertEqual(first["route"],
                         "nan://GM0:SC0:MC0:BS0:0:HW2:0")
        self.assertEqual(self.registry.bind_hermes("hermes-install-01", key(1)), first)
        second = self.registry.bind_hermes("hermes-install-02", key(2))
        self.assertEqual(second["hw"], 5)
        self.assertEqual(second["node_point"], 6)
        self.assertNotEqual(first["hw"], second["hw"])
        third = self.registry.bind_hermes("hermes-install-03", key(3))
        self.assertEqual(third["hw"], 6)
        self.assertEqual(self.registry.hardware(1)["state"], "reserved")
        self.assertEqual(self.registry.hardware(3)["state"], "reserved")
        self.assertEqual(self.registry.hardware(4)["state"], "reserved")
        with self.assertRaises(HierarchyError):
            self.registry.bind_hermes("hermes-install-01", key(4))
        with self.assertRaises(HierarchyError):
            self.registry.bind_hermes("hermes-install-other", key(2))
        self.assertEqual(self.registry.binding_for("hermes-install-02", key(2))["hw"], 5)
        with self.assertRaises(HierarchyError):
            self.registry.binding_for("hermes-install-02", key(1))

    def test_concurrent_allocations_are_atomic_and_stable_after_restart(self):
        def allocate(i):
            return self.registry.bind_hermes(f"hermes-installed-{i:04d}", key(i))["hw"]
        with ThreadPoolExecutor(max_workers=12) as workers:
            allocations = list(workers.map(allocate, range(24)))
        self.assertEqual(len(allocations), len(set(allocations)))
        self.assertEqual(len(allocations), 24)
        self.assertEqual(sorted(allocations), [2] + list(range(5, 28)))
        restarted = HierarchyRegistry(Path(self.tmp.name) / "router-hw.sqlite")
        for i, hw in enumerate(allocations):
            self.assertEqual(restarted.binding_for(f"hermes-installed-{i:04d}", key(i))["hw"], hw)

    def test_future_bootstrap_mapping_in_mc0_does_not_create_runner_or_hw(self):
        future = self.registry.reserve_future_bootstrap(1)
        self.assertEqual(future["route"], "nan://GM0:SC0:MC0:BS1:0")
        self.assertFalse(future["runner_instantiated"])
        self.assertEqual(self.registry.resolve(future["route"])["state"], "future")
        hw = self.registry.resolve(future["route"] + ":HW5:0")
        self.assertEqual(hw["state"], "future")
        self.assertFalse(hw["transport_active"])
        self.assertEqual(self.registry.resolve("nan://GM0:SC0:MC0:BS0:0")["state"], "live")
        self.assertFalse(self.registry.resolve("nan://GM0:SC0:0")["transport_active"])
        self.assertFalse(self.registry.resolve("nan://GM0:0")["transport_active"])
        with self.assertRaises(HierarchyError):
            self.registry.reserve_future_bootstrap(0)
        with self.assertRaises(HierarchyError):
            self.registry.reserve_future_bootstrap(1, 1)
        for address in ("nan://GM0:SC0:MC0:BS999:0", "nan://GM0:SC1:MC0:BS0:0",
                        "nan://GM0:SC0:MC0:BS0:0:HW256:0", "nan://BS0:/../HW1:0"):
            with self.assertRaises(HierarchyError):
                self.registry.resolve(address)
        self.assertEqual(self.registry.summary()["future_bootstrap_points"], 1)
        with sqlite3.connect(Path(self.tmp.name) / "sc0db.sqlite3") as db:
            self.assertEqual(db.execute("SELECT state FROM sc0_children WHERE sc=0 AND mc=0").fetchone()[0],
                             "database-only")
        with sqlite3.connect(Path(self.tmp.name) / "gm0db.sqlite3") as db:
            self.assertEqual(db.execute("SELECT state FROM gm0_children WHERE gm=0 AND sc=0").fetchone()[0],
                             "database-only")

    def test_bad_keys_and_hardware_ids_are_rejected(self):
        for candidate in ("", "a" * 43, "***", key(3) + "A", None):
            with self.assertRaises(HierarchyError):
                self.registry.bind_hermes("hermes-install-04", candidate)
        for hw in (-1, True, 256):
            with self.assertRaises(HierarchyError):
                self.registry.hardware(hw)


if __name__ == "__main__":
    unittest.main()
