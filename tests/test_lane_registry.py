import copy
import dataclasses
import json
import unittest
from pathlib import Path

from runner_riddle.lane_registry import (
    ALL_ROLE_MASK,
    CAPABILITY_CLASS_NAMES,
    CAPABILITY_CLASS_ROLES,
    CONCURRENCY,
    FP_POLICIES,
    GLOBAL_ROLES,
    GLOBAL_ROLE_MASK,
    GROUP_COUNT,
    LANES_PER_GROUP,
    LANE_COUNT,
    LANE_HOME_BYTES,
    LANE_HOME_PAGES,
    LANE_ROLES,
    LANE_ROLE_MASK,
    LANE_ROLE_RANGES,
    NANNET0_PAGE_KEY,
    NANNET0_RING_POSITION,
    PAGE_BYTES,
    ROLES,
    ROLE_BITS,
    ROLE_CAPABILITY_CLASS,
    ROLE_FP_POLICY,
    ROLE_MAX_FANOUT,
    UNIVERSE_BYTES,
    UNIVERSE_PAGES,
    GlobalAuthority,
    LaneBoundsError,
    LaneDuplicateError,
    LanePolicyError,
    LaneRecord,
    LaneRegistry,
    LaneRegistryError,
    LaneRoleError,
    Nannet0LaneError,
    build_ruleset,
    digest_document,
    role_for_lane,
    role_mask,
    roles_from_mask,
    seal_ruleset,
    validate_ruleset,
)


def expected_roles():
    table = [None] * LANE_COUNT
    for role, first, last in LANE_ROLE_RANGES:
        for lane_id in range(first, last + 1):
            table[lane_id] = role
    return table


class LaneRegistryShapeTests(unittest.TestCase):
    def setUp(self):
        self.registry = LaneRegistry()

    def test_exactly_255_lanes_in_17_groups_of_15(self):
        self.assertEqual(LANE_COUNT, 255)
        self.assertEqual(GROUP_COUNT, 17)
        self.assertEqual(LANES_PER_GROUP, 15)
        self.assertEqual(GROUP_COUNT * LANES_PER_GROUP, LANE_COUNT)
        self.assertEqual(len(self.registry), 255)
        self.assertEqual(len(self.registry.lanes), 255)
        self.assertEqual(len(self.registry.groups), 17)
        self.assertEqual(
            [lane.lane_id for lane in self.registry.lanes], list(range(255))
        )
        self.assertEqual(self.registry.lane_ids, tuple(range(255)))
        for group_id in range(GROUP_COUNT):
            group = self.registry.group(group_id)
            self.assertEqual(group.group_id, group_id)
            self.assertEqual(group.pass_index, group_id)
            self.assertEqual(
                group.lane_ids,
                tuple(range(group_id * 15, group_id * 15 + 15)),
            )
            self.assertEqual(group.first_lane, group_id * 15)
            self.assertEqual(group.last_lane, group_id * 15 + 14)
            self.assertEqual(len(group), 15)
            self.assertEqual(
                [lane.lane_id for lane in group], list(group.lane_ids)
            )

    def test_default_spec_is_the_built_ruleset(self):
        built = build_ruleset()
        path = Path(__file__).resolve().parents[1] / "spec" / "lane-ruleset.v1.json"
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded, built)
        self.assertEqual(loaded["digest"], digest_document(loaded))
        self.assertEqual(
            LaneRegistry.from_default_spec().digest, built["digest"]
        )

    def test_lane_255_is_nannet0_and_never_a_lane(self):
        for bad_ref in (
            255, "255", "NANNET0", "nannet0", "nan-net-0",
            "lane:255", "page:255", "head:255", "ring:255",
        ):
            with self.subTest(reference=bad_ref):
                with self.assertRaises(Nannet0LaneError):
                    self.registry.resolve(bad_ref)
        with self.assertRaises(Nannet0LaneError):
            self.registry.lane(255)
        with self.assertRaises(Nannet0LaneError):
            role_for_lane(255)
        with self.assertRaises(Nannet0LaneError):
            LaneRecord.from_dict({
                **self.registry.lane(0).to_dict(),
                "lane_id": 255,
                "ring_position": 255,
                "lane_key": "lane:255",
                "home_page": 255,
                "home_page_key": "page:255",
                "group_id": 17,
                "group_key": "group:17",
                "index_in_group": 0,
            })
        self.assertEqual(self.registry.lane(254).ring_position, 254)
        self.assertNotIn(NANNET0_PAGE_KEY, self.registry.page_keys)
        nannet0 = self.registry.nannet0
        self.assertEqual(nannet0["ring_position"], NANNET0_RING_POSITION)
        self.assertFalse(nannet0["is_lane"])
        self.assertIsNone(nannet0["lane_id"])

    def test_bounds_are_enforced(self):
        for bad_lane in (-1, 256, True, 1.5, None):
            with self.subTest(lane=bad_lane):
                with self.assertRaises(LaneBoundsError):
                    self.registry.lane(bad_lane)
        for bad_group in (-1, GROUP_COUNT, True, 1.5, None):
            with self.subTest(group=bad_group):
                with self.assertRaises(LaneBoundsError):
                    self.registry.group(bad_group)
        with self.assertRaises(LaneRegistryError):
            self.registry.resolve("not-a-lane")
        with self.assertRaises(LaneRegistryError):
            self.registry.resolve("group:00")


class LaneRoleTests(unittest.TestCase):
    def setUp(self):
        self.registry = LaneRegistry()

    def test_generic_role_assignment_and_masks(self):
        expected = expected_roles()
        for lane in self.registry.lanes:
            self.assertEqual(lane.role, expected[lane.lane_id])
            self.assertEqual(lane.role_mask, ROLE_BITS[lane.role])
            self.assertEqual(lane.roles, (lane.role,))
            self.assertEqual(roles_from_mask(lane.role_mask), (lane.role,))
            self.assertFalse(lane.role_mask & GLOBAL_ROLE_MASK)
            self.assertEqual(lane.role_mask & LANE_ROLE_MASK, lane.role_mask)
            self.assertFalse(lane.global_authority)
            self.assertEqual(lane.scope, "lane")
        self.assertEqual(
            set(expected), set(LANE_ROLES)
        )

    def test_all_roles_are_declared_once_as_vocabulary(self):
        self.assertEqual(len(ROLES), 12)
        self.assertEqual(len(LANE_ROLES), 10)
        self.assertEqual(GLOBAL_ROLES, ("scheduling", "supervisor"))
        self.assertEqual(ALL_ROLE_MASK, LANE_ROLE_MASK | GLOBAL_ROLE_MASK)
        self.assertEqual(set(ROLE_BITS), set(ROLES))
        self.assertEqual(role_mask("scheduling", "supervisor"), GLOBAL_ROLE_MASK)
        with self.assertRaises(LaneRoleError):
            role_mask("not_a_role")
        with self.assertRaises(LaneRoleError):
            roles_from_mask(ALL_ROLE_MASK + 1)

    def test_global_authorities_are_not_per_lane_duplicates(self):
        self.assertEqual(
            self.registry.lanes_with_role("scheduling"), ()
        )
        self.assertEqual(
            self.registry.lanes_with_role("supervisor"), ()
        )
        for role in GLOBAL_ROLES:
            holders = self.registry.role_holders(role)
            self.assertEqual(len(holders), 1)
            authority = holders[0]
            self.assertIsInstance(authority, GlobalAuthority)
            self.assertEqual(authority.role, role)
            self.assertEqual(authority.scope, "global")
            self.assertEqual(authority.concurrency, 1)
            self.assertEqual(authority.max_fanout, 1)
        for lane in self.registry.lanes:
            self.assertNotIn(lane.role, GLOBAL_ROLES)
        self.assertEqual(self.registry.lane(254).role, "execution")
        self.assertEqual(
            len([lane for lane in self.registry.lanes
                 if lane.role == "execution"]),
            71,
        )
        self.assertEqual(
            sum(len(self.registry.lanes_with_role(role))
                for role in LANE_ROLES),
            LANE_COUNT,
        )

    def test_role_mask_rejects_global_bits_and_wrong_primary(self):
        entry = self.registry.lane(0).to_dict()
        bad = dict(entry)
        bad["role_mask"] = ROLE_BITS["address_resolution"] | ROLE_BITS["scheduling"]
        with self.assertRaises(LaneRoleError):
            LaneRecord.from_dict(bad)
        bad = dict(entry)
        bad["role_mask"] = ROLE_BITS["classification"]
        with self.assertRaises(LaneRoleError):
            LaneRecord.from_dict(bad)
        bad = dict(entry)
        bad["role"] = "scheduling"
        bad["role_mask"] = ROLE_BITS["scheduling"]
        with self.assertRaises(LaneRoleError):
            LaneRecord.from_dict(bad)


class LanePassTests(unittest.TestCase):
    def setUp(self):
        self.registry = LaneRegistry()

    def test_passes_are_deterministic_and_cover_the_ring(self):
        expected = tuple(
            tuple(range(group_id * 15, group_id * 15 + 15))
            for group_id in range(GROUP_COUNT)
        )
        first = self.registry.passes()
        second = self.registry.passes()
        self.assertEqual(len(first), 17)
        self.assertEqual(
            tuple(tuple(lane.lane_id for lane in group) for group in first),
            expected,
        )
        self.assertEqual(
            tuple(group.lane_ids for group in first), expected
        )
        self.assertEqual(self.registry.pass_lane_ids(), expected)
        self.assertEqual(
            tuple(tuple(lane.lane_id for lane in group) for group in second),
            expected,
        )
        flattened = [lane_id for group in first for lane_id in group.lane_ids]
        self.assertEqual(flattened, list(range(LANE_COUNT)))
        for group_id, group in enumerate(first):
            self.assertEqual(group.group_id, group_id)
        self.assertEqual(
            tuple(group.group_id for group in self.registry.passes(3)),
            (3,),
        )
        self.assertEqual(
            self.registry.passes(3)[0].lane_ids,
            tuple(range(45, 60)),
        )

    def test_group_and_lane_resolution(self):
        lane = self.registry.lane(42)
        self.assertEqual(lane, self.registry.resolve(42))
        self.assertEqual(lane, self.registry.resolve("lane:042"))
        self.assertEqual(lane, self.registry.resolve("page:042"))
        self.assertEqual(lane, self.registry.resolve("head:42"))
        self.assertEqual(lane, self.registry.resolve("ring:042"))
        self.assertEqual(lane, self.registry.resolve("42"))
        self.assertEqual(self.registry.group("group:02"), self.registry.group(2))
        self.assertEqual(self.registry.group("2"), self.registry.group(2))
        self.assertIn(lane, self.registry.group(2))
        self.assertEqual(self.registry.group(2).lane_ids[12], 42)


class LanePolicyTests(unittest.TestCase):
    def setUp(self):
        self.registry = LaneRegistry()

    def test_duplicate_role_policy(self):
        policy = self.registry.duplicate_role_policy
        self.assertEqual(policy["lane_roles"], "repeat_allowed")
        self.assertEqual(policy["global_roles"], "exactly_once")
        self.assertEqual(policy["lane_ids"], "unique")
        self.assertEqual(policy["lane_keys"], "unique")
        self.assertEqual(policy["home_pages"], "unique")
        self.assertEqual(policy["global_authority_in_lane_mask"], "reject")
        self.assertEqual(policy["nannet0_as_lane"], "reject")
        self.assertEqual(self.registry.duplicate_role_policy(), policy)

        duplicate_lane = build_ruleset()
        duplicate_lane["lanes"].append(copy.deepcopy(duplicate_lane["lanes"][0]))
        duplicate_lane["lanes"].pop(1)
        with self.assertRaises(LaneDuplicateError):
            LaneRegistry(seal_ruleset(duplicate_lane))

        duplicate_authority = build_ruleset()
        duplicate_authority["global_authorities"][1] = copy.deepcopy(
            duplicate_authority["global_authorities"][0]
        )
        with self.assertRaises(LaneDuplicateError):
            LaneRegistry(seal_ruleset(duplicate_authority))

        duplicate_role = build_ruleset()
        duplicate_role["roles"][-1] = copy.deepcopy(duplicate_role["roles"][0])
        with self.assertRaises(LaneDuplicateError):
            LaneRegistry(seal_ruleset(duplicate_role))

        global_mask = build_ruleset()
        global_mask["lanes"][0]["role_mask"] = (
            ROLE_BITS["address_resolution"] | ROLE_BITS["scheduling"]
        )
        with self.assertRaises(LaneRoleError):
            LaneRegistry(seal_ruleset(global_mask))

    def test_page_budget_is_one_32_kib_home_page_per_lane(self):
        self.assertEqual(PAGE_BYTES, 32 * 1024)
        self.assertEqual(LANE_HOME_PAGES, 255)
        self.assertEqual(LANE_HOME_BYTES, 255 * PAGE_BYTES)
        self.assertEqual(LANE_HOME_BYTES, 8_355_840)
        self.assertAlmostEqual(LANE_HOME_BYTES / (1024 * 1024), 7.96875)
        self.assertEqual(UNIVERSE_PAGES, 256)
        self.assertEqual(UNIVERSE_BYTES, 8 * 1024 * 1024)
        budget = self.registry.page_budget
        self.assertEqual(budget["pages_per_lane"], 1)
        self.assertEqual(budget["page_bytes"], PAGE_BYTES)
        self.assertEqual(budget["lane_count"], LANE_COUNT)
        self.assertEqual(budget["declared_home_pages"], 255)
        self.assertEqual(budget["declared_home_bytes"], LANE_HOME_BYTES)
        self.assertEqual(budget["declared_home_mib"], "7.96875")
        self.assertEqual(budget["declared_home_mib_approx"], "7.97")
        self.assertEqual(budget["head_pages"], 255)
        self.assertEqual(budget["nannet0_pages"], 1)
        self.assertEqual(budget["universe_pages"], 256)
        self.assertEqual(budget["universe_bytes"], UNIVERSE_BYTES)
        self.assertEqual(budget["remaining_universe_pages"], 1)
        self.assertEqual(budget["concurrency"], 1)
        self.assertEqual(budget["live_home_pages"], 1)
        self.assertEqual(budget["live_home_bytes"], PAGE_BYTES)
        self.assertEqual(budget["standby_home_pages"], 0)
        self.assertTrue(budget["fits_universe"])
        self.assertEqual(self.registry.page_budget(), budget)
        page_keys = set()
        for lane in self.registry.lanes:
            self.assertEqual(lane.home_page, lane.lane_id)
            self.assertEqual(lane.home_page_key, f"page:{lane.lane_id:03d}")
            self.assertEqual(lane.page_key, lane.home_page_key)
            page_keys.add(lane.home_page_key)
        self.assertEqual(len(page_keys), 255)
        self.assertNotIn("page:255", page_keys)

    def test_capability_and_fp_declarations(self):
        for lane in self.registry.lanes:
            self.assertIn(lane.capability_class, CAPABILITY_CLASS_NAMES)
            self.assertIn(
                lane.role, CAPABILITY_CLASS_ROLES[lane.capability_class]
            )
            self.assertEqual(
                lane.capability_class, ROLE_CAPABILITY_CLASS[lane.role]
            )
            self.assertIn(lane.fp_policy, FP_POLICIES)
            self.assertEqual(lane.fp_policy, ROLE_FP_POLICY[lane.role])
            self.assertEqual(lane.fp, dict(FP_POLICIES[lane.fp_policy]))
            self.assertGreaterEqual(lane.max_fanout, 1)
            self.assertLessEqual(lane.max_fanout, LANES_PER_GROUP)
            self.assertEqual(lane.max_fanout, ROLE_MAX_FANOUT[lane.role])
        execution = self.registry.lane(100)
        self.assertEqual(execution.role, "execution")
        self.assertEqual(execution.capability_class, "math.execute")
        self.assertEqual(execution.fp_policy, "binary32-rne")
        self.assertFalse(execution.fp["fma"])
        self.assertTrue(execution.fp["deterministic"])
        self.assertEqual(self.registry.lane(240).fp_policy, "integer-exact")
        self.assertEqual(self.registry.lane(192).fp_policy, "none")
        declarations = self.registry.role_declarations()
        self.assertEqual(len(declarations), 12)
        for declaration in declarations:
            self.assertEqual(
                declaration["scope"],
                "global" if declaration["role"] in GLOBAL_ROLES else "lane",
            )
            self.assertEqual(
                declaration["authority"],
                declaration["role"] in GLOBAL_ROLES,
            )
        with self.assertRaises(LanePolicyError):
            bad = self.registry.lane(0).to_dict()
            bad["fp_policy"] = "not-a-policy"
            LaneRecord.from_dict(bad)
        with self.assertRaises(LanePolicyError):
            bad = self.registry.lane(0).to_dict()
            bad["max_fanout"] = LANES_PER_GROUP + 1
            LaneRecord.from_dict(bad)

    def test_capability_and_fp_documents_match_spec(self):
        document = self.registry.to_dict()
        self.assertEqual(
            set(document["capability_classes"]), CAPABILITY_CLASS_NAMES
        )
        self.assertEqual(set(document["fp_policies"]), set(FP_POLICIES))
        for name, declaration in document["fp_policies"].items():
            self.assertEqual(declaration, dict(FP_POLICIES[name]))
        for name, declaration in document["capability_classes"].items():
            self.assertEqual(declaration["roles"], list(
                CAPABILITY_CLASS_ROLES[name]
            ))


class LaneHealthAndImmutableTests(unittest.TestCase):
    def setUp(self):
        self.registry = LaneRegistry()

    def test_health_is_deterministic_and_never_claims_255_runners(self):
        health = self.registry.health()
        self.assertEqual(health, self.registry.health())
        self.assertEqual(health["schema"], "nanrouter.lane-registry-health.v1")
        self.assertEqual(health["status"], "green")
        self.assertTrue(health["healthy"])
        self.assertEqual(health["lanes"], 255)
        self.assertEqual(health["lane_count"], 255)
        self.assertEqual(health["groups"], 17)
        self.assertEqual(health["lanes_per_group"], 15)
        self.assertEqual(health["passes"], 17)
        self.assertEqual(health["concurrency"], 1)
        self.assertEqual(health["active_runner_slots"], 1)
        identity = health["active_execution_identity"]
        self.assertEqual(identity["concurrency"], 1)
        self.assertEqual(identity["executing_lane_runs"], 1)
        self.assertEqual(identity["active_runner_slots"], 1)
        self.assertEqual(identity["standby_slots_with_live_working_sets"], 0)
        self.assertEqual(identity["native_kernel_invocations_in_flight"], 1)
        self.assertEqual(identity["live_home_pages"], 1)
        self.assertEqual(health["nannet0_ring_position"], 255)
        self.assertFalse(health["nannet0_is_lane"])
        self.assertTrue(health["lane_255_rejected"])
        self.assertEqual(
            sum(health["roles"].values()), LANE_COUNT
        )
        self.assertEqual(
            health["global_authorities"],
            {"scheduling": 1, "supervisor": 1},
        )
        self.assertEqual(health["page_budget"]["declared_home_pages"], 255)
        self.assertEqual(health["page_budget"]["concurrency"], 1)
        summary = self.registry.summary()
        self.assertEqual(summary["concurrency"], 1)
        self.assertEqual(summary["health"], "green")
        self.assertEqual(self.registry.execution_identity()["concurrency"], 1)

    def test_public_calls_do_not_mutate_shared_registry_state(self):
        original_digest = str(self.registry.digest)
        document = self.registry.to_dict()
        document["lanes"][0]["role"] = "hashing"
        document["lanes"][0]["role_mask"] = ROLE_BITS["hashing"]
        document["page_budget"]["pages_per_lane"] = 99
        document["concurrency"] = 255
        self.assertEqual(self.registry.lane(0).role, "address_resolution")
        self.assertEqual(self.registry.lane(0).role_mask, ROLE_BITS["address_resolution"])
        self.assertEqual(self.registry.page_budget["pages_per_lane"], 1)
        self.assertEqual(self.registry.concurrency, 1)
        self.assertEqual(str(self.registry.digest), original_digest)

        records = self.registry.lane_records()
        records[0]["role"] = "hashing"
        records[0]["digest"] = "0" * 64
        self.assertEqual(self.registry.lane(0).role, "address_resolution")
        self.assertEqual(
            self.registry.lane_records()[0]["digest"],
            self.registry.lane(0).digest,
        )

        budget = self.registry.page_budget
        budget["pages_per_lane"] = 99
        self.assertEqual(self.registry.page_budget["pages_per_lane"], 1)
        policy = self.registry.duplicate_role_policy
        policy["global_roles"] = "many"
        self.assertEqual(
            self.registry.duplicate_role_policy["global_roles"], "exactly_once"
        )
        nannet0 = self.registry.nannet0
        nannet0["is_lane"] = True
        self.assertFalse(self.registry.nannet0["is_lane"])

        built = build_ruleset()
        built["lanes"][0]["role"] = "hashing"
        self.assertEqual(build_ruleset()["lanes"][0]["role"], "address_resolution")
        self.assertEqual(str(self.registry.digest), original_digest)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.registry.lane(0).role = "hashing"

    def test_version_and_digest_are_immutable(self):
        self.assertEqual(self.registry.version, 1)
        self.assertEqual(len(str(self.registry.digest)), 64)
        self.assertEqual(self.registry.digest, self.registry.digest())
        seen = set()
        for lane in self.registry.lanes:
            self.assertEqual(lane.version, 1)
            self.assertEqual(len(str(lane.digest)), 64)
            self.assertEqual(lane.digest, lane.digest())
            self.assertNotIn(lane.digest, seen)
            seen.add(lane.digest)
            payload = lane.to_dict()
            self.assertEqual(payload["digest"], lane.digest)
            payload.pop("digest")
            self.assertEqual(digest_document({"lane": payload}), digest_document(
                {"lane": {key: value for key, value in lane.to_dict().items()
                          if key != "digest"}}
            ))
        self.assertEqual(len(seen), LANE_COUNT)
        document = self.registry.to_dict()
        tampered = copy.deepcopy(document)
        tampered["version"] = 2
        with self.assertRaises(LaneRegistryError):
            LaneRegistry(tampered)
        sealed = seal_ruleset(tampered)
        self.assertNotEqual(sealed["digest"], document["digest"])
        self.assertEqual(LaneRegistry(sealed).version, 2)
        bad_lane = copy.deepcopy(document)
        bad_lane["lanes"][0]["max_fanout"] = 99
        with self.assertRaises(LanePolicyError):
            seal_ruleset(bad_lane)
        with self.assertRaises(LaneRegistryError):
            LaneRegistry(bad_lane)

    def test_validate_returns_true_and_rejects_stale_digest(self):
        self.assertTrue(self.registry.validate())
        stale = self.registry.to_dict()
        stale["version"] = 2
        with self.assertRaises(LaneRegistryError):
            validate_ruleset(stale, require_digest=True)
        with self.assertRaises(LaneRegistryError):
            LaneRegistry(stale)


if __name__ == "__main__":
    unittest.main()
