"""Point-0 service contract for the full 8 MiB universe relation-point map.

The public ``RiddleService`` ``/healthz`` document does not publish the
universe map, so this contract uses the real ``MthSystem`` service facade:
``MthSystem.health()`` includes the ``universe_map`` report and
``MthSystem.point_zero_route()`` publishes the stable point-0 route.  The same
real ``WaveService``/``WaveRingScheduler`` stack feeds the point-0 HTTP adapter,
whose injectable ``handle()`` core is exercised without opening a socket.

No production code, existing test, or credential is modified here.
"""
from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from runner_riddle import mth_system, point0_bridge, point0_http, universe_map
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.mth_system import POINT_ZERO_ADDRESS, MthSystem
from runner_riddle.point0_bridge import NanFrame, Point0Bridge, Point0Router
from runner_riddle.point0_http import POINT0_PATH, Point0HttpAdapter
from runner_riddle.universe_map import (
    CANONICAL_CELLS,
    MAX_LAYER,
    NANNET0_PAGE,
    PAGE_BYTES,
    PAIR_COUNT,
    ROUTE_ROOT,
    UNIVERSE_BYTES,
    UNIVERSE_PAGES,
    UNIVERSE_WORDS,
    UniverseMapError,
    head,
    mirror_pair,
    page,
    route,
)
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"
UNIVERSE_MAP_SPEC = REPO_ROOT / "spec" / "universe-map.json"

SUBMIT_TOKEN = "universe-map-submit-token-000000000"
WORKER_TOKEN = "universe-map-worker-token-111111111"
ADMIN_TOKEN = "universe-map-admin-token-2222222222"

# Numeric packages that would put mathematical work on the host.  The point-0
# adapter is transport-only; the universe map is control-plane address
# arithmetic, not kernel execution.
FORBIDDEN_MATH_LIBRARIES = {
    "cupy",
    "jax",
    "mpmath",
    "numba",
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "sympy",
    "tensorflow",
    "torch",
}
FORBIDDEN_EXECUTION_ESCAPES = {"ctypes", "mmap", "subprocess"}


def imported_roots(module) -> set[str]:
    """Return absolute import roots for one Python module's source."""
    tree = ast.parse(inspect.getsource(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(
                alias.name.split(".", 1)[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add((node.module or "").split(".", 1)[0])
    return roots


def attribute_calls(module, root: str) -> set[str]:
    """Return attribute names called on a module-level name in *module*."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == root
        ):
            names.add(node.func.attr)
    return names


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, bytes]] = []

    def __call__(self, active_slot: int, epoch: int,
                 binary_payload: bytes) -> bytes:
        self.calls.append((active_slot, epoch, binary_payload))
        return binary_payload


class Point0UniverseMapContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = MthRegistry.load(MANIFEST)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = WaveStore(root / "bs0db.sqlite3", root / "mc0db.sqlite3")
        self.service = WaveService(
            self.store, SUBMIT_TOKEN, WORKER_TOKEN, ADMIN_TOKEN,
        )
        self.scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
        self.scheduler.start(0)
        self.system = MthSystem(
            self.registry, self.store, self.service, self.scheduler,
        )
        self.executor = RecordingExecutor()
        self.router = Point0Router(self.scheduler, self.executor)
        self.adapter = Point0HttpAdapter(self.router, self.service)

    # -- Helpers --------------------------------------------------------------

    def assert_secret_free(self, payload: str) -> None:
        for token in (SUBMIT_TOKEN, WORKER_TOKEN, ADMIN_TOKEN):
            self.assertNotIn(token, payload)
        lowered = payload.lower()
        for marker in ("authorization", "bearer", "credential", "token"):
            self.assertNotIn(marker, lowered)

    # -- Service health contract ---------------------------------------------

    def test_service_health_exposes_full_universe_map_contract(self):
        health = self.system.health()
        self.assertEqual(health["schema"], "nanrouter.mth-system-health.v1")
        self.assertEqual(health["status"], "green")

        # The public point-0 route is stable and matches the address root.
        self.assertEqual(POINT_ZERO_ADDRESS, ROUTE_ROOT)
        self.assertEqual(health["point_zero"]["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(health["point_zero"]["point_zero"], "BS0:0")
        self.assertEqual(health["point_zero"]["wire"], "BSR0")
        self.assertEqual(self.system.point_zero_route()["route"], POINT_ZERO_ADDRESS)

        report = health["universe_map"]
        self.assertEqual(report["schema"], "nanrouter.universe-map.v1")
        self.assertEqual(report["status"], "green")
        self.assertEqual(report["pages"], 256)
        self.assertEqual(report["pages"], UNIVERSE_PAGES)
        self.assertEqual(report["universe_bytes"], 8 * 1024 * 1024)
        self.assertEqual(report["universe_bytes"], UNIVERSE_BYTES)
        self.assertEqual(report["universe_words"], 1_048_576)
        self.assertEqual(report["universe_words"], UNIVERSE_WORDS)
        self.assertEqual(report["relation_points"], 32_896)
        self.assertEqual(report["relation_points"], CANONICAL_CELLS)
        self.assertEqual(report["fixed_heads"], 256)
        self.assertEqual(report["mirror_pairs"], 32_640)
        self.assertEqual(report["mirror_pairs"], PAIR_COUNT)
        self.assertEqual(report["real_heads"], 255)
        self.assertEqual(report["nannet0_head"], 0)
        self.assertEqual(report["nannet0_page"], 255)
        self.assertEqual(report["nannet0_ring_position"], 255)
        self.assertEqual(
            report["nannet0_aliases"],
            ["HW0:0", "page:255", "ring:255"],
        )
        self.assertEqual(report["coverage"], 1.0)
        self.assertEqual(report["max_guest_word"], 1_044_480)
        self.assertEqual(report["mp_slots_per_page"], 128)
        self.assertEqual(report["mp_slot_base_word"], 3840)
        self.assertEqual(report["mp_slot_words"], 2)
        self.assertTrue(report["native_required"])
        self.assertFalse(report["executes_math"])
        self.assertFalse(report["claims_relations_true"])
        self.assertEqual(len(report["page_directory_sha256"]), 64)

        # The health report is the same contract as the service method and
        # the checked-in generated universe-map document.
        self.assertEqual(report, self.system.universe_map())
        spec = json.loads(UNIVERSE_MAP_SPEC.read_text(encoding="utf-8"))
        self.assertEqual(
            report["page_directory_sha256"],
            spec["page_directory_sha256"],
        )
        self.assertEqual(report["nannet0_aliases"], spec["nannet0_aliases"])
        self.assertEqual(
            json.loads(json.dumps(health, sort_keys=True)), health,
        )
        self.assertEqual(
            self.system.health()["universe_map"], report,
        )

    def test_point_zero_route_is_stable_across_ring_cycles_and_credential_free(self):
        first = self.system.point_zero_route()
        self.assertEqual(first["schema"], "nanrouter.mth-point-zero.v1")
        self.assertEqual(first["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(first["point_zero"], "BS0:0")
        self.assertEqual(first["wire"], "BSR0")
        self.assertEqual(first["active_slot"], 0)
        self.assertEqual(first["epoch"], 1)
        self.assertEqual(first["health"], "green")

        self.scheduler.cycle(1)
        second = self.system.point_zero_route()
        self.assertEqual(second["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(second["active_slot"], 1)
        self.assertEqual(second["epoch"], 2)
        self.assertEqual(second["health"], "green")

        # The same stable route and full universe map survive the handoff.
        health = self.system.health()
        self.assertEqual(health["point_zero"]["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(health["universe_map"]["pages"], 256)
        self.assertEqual(health["universe_map"]["relation_points"], 32_896)
        self.assertEqual(health["universe_map"]["coverage"], 1.0)

        for document in (first, second, health):
            self.assert_secret_free(json.dumps(document, sort_keys=True))
        for document in (first, second):
            self.assertNotIn("/R", document["route"])
            self.assertNotIn("NANROUTER", document["route"])
            self.assertNotIn("MC0:0/R", document["route"])

    # -- Relation-point route resolution -------------------------------------

    def test_universe_route_resolves_heads_mirror_pairs_and_boundaries(self):
        stable = POINT_ZERO_ADDRESS

        # Explicitly pin the head/mirror-pair transitions and both endpoints.
        expected = {
            0: f"{stable}::HW0:0",       # NANNET0 control point
            1: f"{stable}::HW0:1",       # first real head
            254: f"{stable}::HW0:254",
            255: f"{stable}::HW0:255",   # last real head
            256: f"{stable}::HW0:MP0",   # first mirror pair
            257: f"{stable}::HW0:MP1",
            511: f"{stable}::HW0:MP255",
            32767: f"{stable}::HW0:MP32511",
            32895: f"{stable}::HW0:MP32639",  # last canonical cell
        }
        for cell, path in expected.items():
            with self.subTest(cell=cell):
                self.assertEqual(self.system.universe_route(cell), path)
                self.assertEqual(route(cell), path)
                if cell < 256:
                    self.assertEqual(head(cell).route, path)
                else:
                    self.assertEqual(mirror_pair(cell - 256).route, path)

        # Every fixed head route is addressable through the service.
        for head_id in range(256):
            with self.subTest(head=head_id):
                self.assertEqual(
                    self.system.universe_route(head_id),
                    f"{stable}::HW0:{head_id}",
                )
                self.assertEqual(head(head_id).canonical_cell, head_id)

        # First and last mirror pair on every real-head page stay addressable.
        for page_id in range(255):
            for pair_index in (page_id, page_id + 255 * 127):
                with self.subTest(page=page_id, mp=pair_index):
                    self.assertEqual(
                        self.system.universe_route(256 + pair_index),
                        f"{stable}::HW0:MP{pair_index}",
                    )
                    record = mirror_pair(pair_index)
                    self.assertEqual(record.page, page_id)
                    self.assertEqual(
                        record.word, 3840 + 2 * (pair_index // 255)
                    )
                    self.assertLess(record.word, 4096)

        # Layer qualification is available for heads, mirror pairs, and edges.
        for cell in (0, 1, 255, 256, 32767, 32895):
            for layer in range(MAX_LAYER + 1):
                with self.subTest(cell=cell, layer=layer):
                    value = self.system.universe_route(cell, layer)
                    self.assertEqual(value, f"{expected[cell]}::L{layer}")
                    self.assertEqual(value, route(cell, layer))
                    self.assertTrue(value.endswith(f"::L{layer}"))
                    self.assertNotIn("/R", value)
                    self.assertNotIn("NANROUTER", value)

        # Page and word boundaries cover the complete 8 MiB universe.
        self.assertEqual(page(0).head, 1)
        self.assertEqual(page(254).head, 255)
        self.assertEqual(page(NANNET0_PAGE).head, 0)
        self.assertEqual(page(NANNET0_PAGE).kind, "nannet0")
        self.assertEqual(page(NANNET0_PAGE).relation_slots, 0)
        self.assertEqual(
            page(UNIVERSE_PAGES - 1).offset_bytes + PAGE_BYTES,
            UNIVERSE_BYTES,
        )
        self.assertEqual(head(0).guest_word, 1_044_480)
        self.assertEqual(mirror_pair(PAIR_COUNT - 1).guest_word, 1_044_478)
        self.assertLess(mirror_pair(PAIR_COUNT - 1).guest_word, UNIVERSE_WORDS)

        for bad_cell in (-1, CANONICAL_CELLS, True):
            with self.assertRaises(UniverseMapError):
                self.system.universe_route(bad_cell)
        for bad_layer in (-1, MAX_LAYER + 1, True):
            with self.assertRaises(UniverseMapError):
                self.system.universe_route(0, bad_layer)

    # -- Transport-only adapter and credential hygiene -----------------------

    def test_point0_http_adapter_is_transport_only_and_uses_no_host_math_library(self):
        modules = (point0_http, universe_map, mth_system, point0_bridge)
        for module in modules:
            with self.subTest(module=module.__name__):
                roots = imported_roots(module)
                self.assertEqual(
                    roots & FORBIDDEN_MATH_LIBRARIES, set(), module.__name__,
                )
                self.assertEqual(
                    roots & FORBIDDEN_EXECUTION_ESCAPES, set(), module.__name__,
                )

        # The map and facade perform no host math at all.  The HTTP adapter's
        # only standard-library math use is finite-JSON validation; frame
        # words are transported unchanged.
        self.assertNotIn("math", imported_roots(universe_map))
        self.assertNotIn("math", imported_roots(mth_system))
        self.assertNotIn("math", imported_roots(point0_bridge))
        self.assertEqual(attribute_calls(point0_http, "math"), {"isfinite"})

        words = (0, 1, (1 << 64) - 1, 0x9E3779B97F4A7C15)
        raw = json.dumps(
            {"request_id": 91, "words": list(words)},
            separators=(",", ":"),
        ).encode("utf-8")
        response = self.adapter.handle(
            "POST",
            POINT0_PATH,
            {
                "Content-Type": "application/json",
                "Content-Length": str(len(raw)),
                "Authorization": "Bearer " + SUBMIT_TOKEN,
            },
            raw,
        )
        self.assertEqual(response.status, 200)
        document = response.json()
        self.assertEqual(document["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(document["point_zero"], "BS0:0")
        self.assertEqual(document["wire"], "BSR0")
        self.assertEqual(document["words"], list(words))
        self.assertEqual(document["word_count"], len(words))

        # The executor receives the exact point-0 binary framing; no adapter
        # layer transformed the words.
        self.assertEqual(len(self.executor.calls), 1)
        slot, epoch, payload = self.executor.calls[0]
        self.assertEqual((slot, epoch), (0, 1))
        self.assertEqual(
            payload,
            Point0Bridge().encode(
                NanFrame(words=words, request_id=91),
                active_slot=0,
                epoch=1,
            ).payload,
        )

    def test_health_route_and_http_payloads_contain_no_tokens_or_credentials(self):
        raw = b'{"request_id":7,"words":[1,2,3]}'
        response = self.adapter.handle(
            "POST",
            POINT0_PATH,
            {
                "Content-Type": "application/json",
                "Content-Length": str(len(raw)),
                "Authorization": "Bearer " + SUBMIT_TOKEN,
            },
            raw,
        )
        self.assertEqual(response.status, 200)

        payloads = (
            json.dumps(self.system.health(), sort_keys=True),
            json.dumps(self.system.point_zero_route(), sort_keys=True),
            response.body.decode("utf-8"),
            json.dumps(response.headers, sort_keys=True),
        )
        for payload in payloads:
            with self.subTest(payload=payload[:80]):
                self.assert_secret_free(payload)

        # The route string never names a runner slot or alias; slot identity
        # remains separate evidence in the same document.
        route_document = self.system.point_zero_route()
        self.assertNotIn("MC0:0/R", route_document["route"])
        self.assertNotIn("NANROUTER", route_document["route"])
        self.assertEqual(route_document["route"], POINT_ZERO_ADDRESS)


if __name__ == "__main__":
    unittest.main()
