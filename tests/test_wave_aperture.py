import unittest

from runner_riddle.wave_aperture import ApertureDescriptor, ApertureError


class ApertureTests(unittest.TestCase):
    def test_hermitian_filter_uses_eigendecomposition(self):
        descriptor = ApertureDescriptor("a1", "u1", role="filter", hermitian=True)
        self.assertEqual(descriptor.decomposition(), "eigendecomposition")

    def test_general_filter_uses_svd(self):
        descriptor = ApertureDescriptor("a1", "u1", role="filter")
        self.assertEqual(descriptor.decomposition(), "svd")

    def test_scattering_uses_svd(self):
        descriptor = ApertureDescriptor("a1", "u1", role="scattering")
        self.assertEqual(descriptor.decomposition(), "svd")

    def test_coupling_nonhermitian_uses_schur_or_svd(self):
        descriptor = ApertureDescriptor("a1", "u1", role="coupling")
        self.assertEqual(descriptor.decomposition(), "schur_or_svd")

    def test_head_only_dimensions(self):
        descriptor = ApertureDescriptor("a1", "u1", rows=255, cols=255)
        descriptor.validate()

    def test_bad_dimensions_rejected(self):
        with self.assertRaises(ApertureError):
            ApertureDescriptor("a1", "u1", rows=128, cols=128).validate()

    def test_rank_bounds(self):
        with self.assertRaises(ApertureError):
            ApertureDescriptor("a1", "u1", rank=300).validate()

    def test_dict_contains_decomposition(self):
        value = ApertureDescriptor("a1", "u1", role="memory").to_dict()
        self.assertEqual(value["decomposition"], "svd")
        self.assertEqual(value["schema"], "nanrouter.wave-aperture.v1")

    def test_digest_format(self):
        with self.assertRaises(ApertureError):
            ApertureDescriptor("a1", "u1", operator_digest="bad").validate()


if __name__ == "__main__":
    unittest.main()
