#!/usr/bin/env python3
"""Run NaN16 MTH fixtures with the canonical NaN0S assembler and harness.

This is a test-harness orchestrator only. It does not calculate expected
mathematical results on behalf of the guest; it assembles, launches, collects
serial output, and checks the fixture's PASS marker.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAN0S = Path("/data/data/com.termux/files/home/nan0s")
STEP_RE = re.compile(r"nan-text:\s+(\d+)\s+steps")


@dataclass(frozen=True)
class Fixture:
    name: str
    path: str
    steps: int
    marker: str
    status: str = "source_written"
    requires_nan0s_sources: bool = False


FIXTURES: tuple[Fixture, ...] = (
    Fixture("k256", "mth/tests/mth_k256_laplacian_test.nas", 2_000_000, "MTH K256 LAPLACIAN PASS", "native_verified"),
    Fixture("k256_pair_space", "mth/tests/mth_k256_pair_space_v1_test.nas", 2_500_000, "MTH K256 PAIR SPACE V1 PASS", "native_verified"),
    Fixture("k255", "mth/tests/mth_k255_laplacian_test.nas", 4_000_000, "MTH K255 LAPLACIAN PASS", "native_verified"),
    Fixture("ring255", "mth/tests/mth_ring255_laplacian_test.nas", 4_000_000, "MTH RING255 LAPLACIAN PASS", "native_verified"),
    Fixture("ring255_port", "mth/tests/mth_ring255_port_test.nas", 4_000_000, "MTH RING255 PORT ASSEMBLE PASS", "native_verified"),
    Fixture("sparse", "mth/tests/mth_sparse_graph_laplacian_test.nas", 4_000_000, "MTH SPARSE GRAPH LAPLACIAN PASS", "native_verified"),
    Fixture("weighted_sparse", "mth/tests/mth_sparse_weighted_graph_laplacian_v2_test.nas", 8_000_000, "MTH WEIGHTED CSR LAPLACIAN V2 PASS", "native_verified"),
    Fixture("energy", "mth/tests/mth_graph_energy_weighted_u8_q32_32_test.nas", 8_000_000, "MTH WEIGHTED GRAPH ENERGY PASS", "native_verified"),
    Fixture("components", "mth/tests/mth_graph_components_256_test.nas", 8_000_000, "MTH GRAPH COMPONENTS PASS", "native_verified"),
    Fixture("graph_degree", "mth/tests/mth_graph_degree_test.nas", 1_000_000, "MTH GRAPH DEGREE 256 PASS", "native_verified"),
    Fixture("graph_pattern", "mth/tests/mth_graph_pattern_test.nas", 1_000_000, "MTH GRAPH PATTERN 256 PASS", "native_verified"),
    Fixture("graph_filter", "mth/tests/mth_graph_filter_test.nas", 2_000_000, "MTH GRAPH FILTER Q16.16 PASS", "native_verified"),
    Fixture("graph_claim_probe", "mth/tests/mth_graph_claim_probe_test.nas", 2_000_000, "MTH GRAPH CLAIM PROBE PASS", "native_verified"),
    Fixture("graph_laplacian_csr", "mth/tests/mth_graph_laplacian_csr_test.nas", 1_000_000, "MTH GRAPH LAPLACIAN CSR PASS", "native_verified"),
    Fixture("rss_contract", "mth/tests/mth_rss_contract_test.nas", 100_000, "MTH RSS CONTRACT PASS", "native_verified"),
    Fixture("fold", "mth/tests/mth_graph_fold_test.nas", 4_000_000, "MTH GRAPH FOLD VECTOR PASS", "native_verified"),
    Fixture("dot256", "mth/tests/mth_dot256_test.nas", 4_000_000, "MTH DOT256 PASS", "native_verified"),
    Fixture("norm256", "mth/tests/mth_norm256_test.nas", 4_000_000, "MTH NORM256 PASS", "native_verified"),
    Fixture("cosine256", "mth/tests/mth_cosine256_test.nas", 4_000_000, "MTH COSINE256 PASS", "native_verified"),
    Fixture("axpy256", "mth/tests/mth_axpy256_test.nas", 4_000_000, "MTH AXPY256 PASS", "native_verified"),
    Fixture("void", "mth/tests/mth_graph_void_test.nas", 4_000_000, "MTH GRAPH VOID POTENTIAL PASS", "native_verified"),
    Fixture("wave", "mth/tests/mth_graph_wave_test.nas", 4_000_000, "MTH GRAPH WAVE STEP PASS", "native_verified"),
    Fixture("step_energy", "mth/tests/mth_graph_step_energy_256_test.nas", 4_000_000, "MTH GRAPH STEP ENERGY PASS", "native_verified"),
    Fixture("harmonic_energy", "mth/tests/mth_harmonic_wave_energy_test.nas", 10_000_000, "MTH HARMONIC WAVE ENERGY PASS", "native_verified"),
    Fixture("harmonic_damped", "mth/tests/mth_harmonic_damped_energy_test.nas", 10_000_000, "MTH HARMONIC DAMPED ENERGY PASS", "native_verified"),
    Fixture("ring256", "mth/tests/mth_ring256_laplacian_test.nas", 20_000_000, "MTH RING256 LAPLACIAN PASS", "native_verified"),
    Fixture("ring_wave_energy", "mth/tests/mth_ring_wave_energy_test.nas", 20_000_000, "MTH RING WAVE ENERGY PASS", "native_verified"),
    Fixture("matvec128", "mth/tests/mth_matvec128_test.nas", 10_000_000, "MTH MATVEC128 PASS", "native_verified"),
    Fixture("matvec256b", "mth/tests/mth_matvec256_block16_test.nas", 20_000_000, "MTH MATVEC256 BLOCK16 PASS", "native_verified"),
    Fixture("matvec256full", "mth/tests/mth_matvec256_full_test.nas", 50_000_000, "MTH MATVEC256 FULL PASS", "native_verified"),
    Fixture("jahs_gate", "mth/tests/mth_jahs_gate_test.nas", 2_000_000, "MTH JAHS GATE PASS", "native_verified"),
    Fixture("centro128", "mth/tests/mth_centrosymmetry_128_test.nas", 10_000_000, "MTH CENTROSYMMETRY 128 PASS", "native_verified"),
    Fixture("centro256b", "mth/tests/mth_centrosymmetry_block16_test.nas", 20_000_000, "MTH CENTROSYMMETRY BLOCK16 PASS", "native_verified"),
    Fixture("centro255b", "mth/tests/mth_centrosymmetry255_block15_test.nas", 20_000_000, "MTH CENTROSYMMETRY 255 BLOCK15 PASS", "native_verified"),
    Fixture("centro255full", "mth/tests/mth_centrosymmetry_255_full_test.nas", 10_000_000, "MTH CENTROSYMMETRY 255 FULL PASS", "native_verified"),
    Fixture("power128", "mth/tests/mth_power_iter128_test.nas", 50_000_000, "MTH POWER_ITER128 PASS", "native_verified"),
    Fixture("pair_full", "mth/tests/mth_graph_pair_test.nas", 100_000_000, "MTH GRAPH PAIR FULL 128 PASS", "native_verified"),
    Fixture("pair_tile16", "mth/tests/mth_graph_pair_tile16_f32_test.nas", 30_000_000, "MTH PAIR TILE16 F32 PASS", "native_verified"),
    Fixture("pairtile16_driver", "mth/tests/mth_graph_pair_tile16_k16_driver_f32_test.nas", 50_000_000, "MTH PAIR K16 DRIVER PASS", "native_verified"),
    Fixture("preflight_gate", "mth/tests/mth_preflight_gate_test.nas", 200_000, "MTH PREFLIGHT GATE PASS", "native_verified"),
    Fixture("admission", "mth/tests/mth_admission_test.nas", 2_000_000, "MTH COMPOSED ADMISSION PASS", "native_verified"),
    Fixture("pair_tile16_k16", "mth/tests/mth_graph_pair_tile16_k16_f32_test.nas", 1_000_000, "MTH PAIR TILE16 K16 ACCUM PASS", "native_verified"),
    Fixture("pair_rank1", "mth/tests/mth_graph_pair_rank1_128_test.nas", 30_000_000, "MTH GRAPH PAIR RANK1 128 PASS", "native_verified"),
    Fixture("lowrank128", "mth/tests/mth_lowrank_add_128_test.nas", 20_000_000, "MTH LOWRANK ADD 128 PASS", "native_verified"),
    Fixture("adapter128", "mth/tests/mth_adapter_residual_128_test.nas", 30_000_000, "MTH ADAPTER RESIDUAL 128 PASS", "native_verified"),
    Fixture("adapter256b", "mth/tests/mth_adapter_residual_256_block16_test.nas", 20_000_000, "MTH ADAPTER RESIDUAL 256 BLOCK16 PASS", "native_verified"),
    Fixture("adapter256full", "mth/tests/mth_adapter_residual_256_full_test.nas", 50_000_000, "MTH ADAPTER RESIDUAL 256 FULL PASS", "native_verified"),
    Fixture("encode_decode", "mth/tests/mth_encode_decode_test.nas", 30_000_000, "MTH ENCODE DECODE PASS", "native_verified"),
    Fixture("encode_decode256", "mth/tests/mth_encode_decode256_test.nas", 30_000_000, "MTH ENCODE DECODE 256 PASS", "native_verified"),
    Fixture("svd128", "mth/tests/mth_svd_top128_test.nas", 100_000_000, "MTH SVD TOP128 PASS", "native_verified"),
    Fixture("svd256", "mth/tests/mth_svd_top256_test.nas", 150_000_000, "MTH SVD TOP256 PASS", "native_verified"),
    Fixture("svd_top2_256", "mth/tests/mth_svd_top2_256_test.nas", 150_000_000, "MTH SVD TOP2 256 PASS", "native_verified"),
    Fixture("dft256", "mth/tests/mth_graph_dft256_test.nas", 50_000_000, "MTH GRAPH DFT256 PASS", "native_verified"),
    Fixture("dft255", "mth/tests/mth_graph_dft255_test.nas", 40_000_000, "MTH GRAPH DFT255 PASS", "native_verified"),
    Fixture("couple128", "mth/tests/mth_graph_couple_128_test.nas", 4_000_000, "MTH GRAPH COUPLE 128 PASS", "native_verified"),
    Fixture("transmission128", "mth/tests/mth_graph_transmission_128_test.nas", 4_000_000, "MTH GRAPH TRANSMISSION 128 PASS", "native_verified"),
    Fixture("two_level", "mth/tests/mth_two_level_spectrum_test.nas", 1_000_000, "MTH TWO LEVEL SPECTRUM PASS", "native_verified"),
    Fixture("avoided_crossing_sweep", "mth/tests/mth_avoided_crossing_sweep_test.nas", 4_000_000, "MTH AVOIDED CROSSING SWEEP PASS", "native_verified"),
    Fixture("drive_source_256", "mth/tests/mth_drive_source_256_test.nas", 5_000_000, "MTH DRIVE SOURCE 256 PASS", "native_verified"),
    Fixture("cfl_guard_256", "mth/tests/mth_cfl_guard_256_test.nas", 5_000_000, "MTH CFL GUARD 256 PASS", "native_verified"),
    Fixture("radial_tridiagonal", "mth/tests/mth_radial_tridiagonal_test.nas", 5_000_000, "MTH RADIAL TRIDIAGONAL PASS", "native_verified"),
    Fixture("radial_energy", "mth/tests/mth_radial_energy_test.nas", 5_000_000, "MTH RADIAL ENERGY PASS", "native_verified"),
    Fixture("colored_noise_256", "mth/tests/mth_colored_noise_256_test.nas", 10_000_000, "MTH COLORED NOISE 256 PASS", "native_verified"),
    Fixture("lanczos_256", "mth/tests/mth_lanczos_256_test.nas", 200_000_000, "MTH LANCZOS 256 PASS", "native_verified"),
    Fixture("reachability_256", "mth/tests/mth_reachability_256_test.nas", 20_000_000, "MTH REACHABILITY 256 PASS", "native_verified"),
    Fixture("phase_coherence", "mth/tests/mth_phase_coherence_128_test.nas", 4_000_000, "MTH PHASE COHERENCE 128 PASS", "native_verified"),
    Fixture("topk256", "mth/tests/mth_topk_256_test.nas", 10_000_000, "MTH TOPK 256 PASS", "native_verified"),
    Fixture("bool2", "mth/tests/mth_bool2_test.nas", 100_000, "MTH BOOL2 ALL 16 PASS", "native_verified"),
    Fixture("bitwise", "mth/tests/mth_bitwise_test.nas", 100_000, "MTH BITWISE/COMPARE PASS", "native_verified"),
    Fixture("integer", "mth/tests/mth_integer_test.nas", 100_000, "MTH INT32 CHECKED PASS", "native_verified"),
    Fixture("shift", "mth/tests/mth_shift_test.nas", 100_000, "MTH SHIFT PASS", "native_verified"),
    Fixture("multiply", "mth/tests/mth_multiply_test.nas", 100_000, "MTH MUL WIDE PASS", "native_verified"),
    Fixture("divide", "mth/tests/mth_divide_test.nas", 100_000, "MTH DIVMOD PASS", "native_verified"),
    Fixture("stage0", "mth/tests/mth_stage0_test.nas", 200_000, "MTH STAGE0 PASS", "native_verified"),
    Fixture("double_endian", "mth/tests/mth_double_endian_test.nas", 200_000, "MTH DOUBLE-ENDIAN REENTRANT PASS", "native_verified"),
    Fixture("matrix_transpose256", "mth/tests/mth_matrix_transpose256_f32_test.nas", 4_000_000, "MTH MATRIX TRANSPOSE256 F32 PASS", "native_verified"),
    Fixture("vector_argmax256_f32", "mth/tests/mth_vector_argmax256_f32_test.nas", 200_000, "MTH VECTOR ARGMAX256 F32 PASS", "native_verified"),
    Fixture("vector_argmin256_f32", "mth/tests/mth_vector_argmin256_f32_test.nas", 200_000, "MTH VECTOR ARGMIN256 F32 PASS", "native_verified"),
    Fixture("vector_scale256_f32", "mth/tests/mth_vector_scale256_f32_test.nas", 200_000, "MTH VECTOR SCALE256 F32 PASS", "native_verified"),
    Fixture("matrix_diagonal256", "mth/tests/mth_matrix_diagonal256_f32_test.nas", 200_000, "MTH MATRIX DIAGONAL256 F32 PASS", "native_verified"),
    Fixture("matrix_add256", "mth/tests/mth_matrix_add256_f32_test.nas", 4_000_000, "MTH MATRIX ADD256 F32 PASS", "native_verified"),
    Fixture("vector_add", "mth/tests/mth_vector_test.nas", 200_000, "MTH U32 VECTOR ADD PASS", "native_verified"),
    Fixture("vector_add256_f32", "mth/tests/mth_vector_add256_f32_test.nas", 100_000, "MTH VECTOR ADD256 F32 PASS", "native_verified"),
    Fixture("vector_sub256_f32", "mth/tests/mth_vector_sub256_f32_test.nas", 100_000, "MTH VECTOR SUB256 F32 PASS", "native_verified"),
    Fixture("vector_mean256_f32", "mth/tests/mth_vector_mean256_f32_test.nas", 100_000, "MTH VECTOR MEAN256 F32 PASS", "native_verified"),
    Fixture("vector_abs256_f32", "mth/tests/mth_vector_abs256_f32_test.nas", 100_000, "MTH VECTOR ABS256 PASS", "native_verified"),
    Fixture("vector_relu256_f32", "mth/tests/mth_vector_relu256_f32_test.nas", 100_000, "MTH VECTOR RELU256 PASS", "native_verified"),
    Fixture("vector_normalize256_f32", "mth/tests/mth_vector_normalize256_f32_test.nas", 200_000, "MTH VECTOR NORMALIZE256 F32 PASS", "native_verified"),
    Fixture("vector_prefix_sum256_u32", "mth/tests/mth_vector_prefix_sum256_u32_test.nas", 100_000, "MTH VECTOR PREFIX SUM256 U32 PASS", "native_verified"),
    Fixture("vector_mask256_f32", "mth/tests/mth_vector_mask256_f32_test.nas", 300_000, "MTH VECTOR MASK256 F32 PASS", "native_verified"),
    Fixture("vector_weighted_sum256_f32", "mth/tests/mth_vector_weighted_sum256_f32_test.nas", 300_000, "MTH VECTOR WEIGHTED SUM256 F32 PASS", "native_verified"),
    Fixture("vector_softmax256_f32", "mth/tests/mth_vector_softmax256_f32_test.nas", 200_000, "MTH VECTOR SOFTMAX256 F32 PASS", "native_verified"),
    Fixture("vector_sum256_f32", "mth/tests/mth_vector_sum256_f32_test.nas", 100_000, "MTH VECTOR SUM256 F32 PASS", "native_verified"),
    Fixture("vector_max256_f32", "mth/tests/mth_vector_max256_f32_test.nas", 100_000, "MTH VECTOR MAX256 F32 PASS", "native_verified"),
    Fixture("vector_min256_f32", "mth/tests/mth_vector_min256_f32_test.nas", 100_000, "MTH VECTOR MIN256 F32 PASS", "native_verified"),
    Fixture("vector_head_concat256_f32", "mth/tests/mth_vector_head_concat256_f32_test.nas", 200_000, "MTH VECTOR HEAD CONCAT256 F32 PASS", "native_verified"),
    Fixture("pair_full_grid_driver", "mth/tests/mth_graph_pair_full_grid_driver_f32_test.nas", 600_000_000, "MTH FULL GRID 256 TILE DRIVER PASS", "native_verified"),
    Fixture("vector_sqrt256_f32", "mth/tests/mth_vector_sqrt256_f32_test.nas", 500_000, "MTH VECTOR SQRT256 F32 PASS", "native_verified"),
    Fixture("vector_rsqrt256_f32", "mth/tests/mth_vector_rsqrt256_f32_test.nas", 500_000, "MTH VECTOR RSQRT256 F32 PASS", "native_verified"),
    Fixture("vector_exp256_f32", "mth/tests/mth_vector_exp256_f32_test.nas", 1_000_000, "MTH VECTOR EXP256 F32 PASS", "native_verified"),
    Fixture("vector_log256_f32", "mth/tests/mth_vector_log256_f32_test.nas", 500_000, "MTH VECTOR LOG256 F32 PASS", "native_verified"),
    Fixture("vector_logsumexp256_f32", "mth/tests/mth_vector_logsumexp256_f32_test.nas", 500_000, "MTH VECTOR LOGSUMEXP256 F32 PASS", "native_verified"),
    Fixture("sequence_step_u32", "mth/tests/mth_sequence_step_u32_test.nas", 10_000, "MTH SEQUENCE STEP U32 PASS", "native_verified"),
    Fixture("vector_sigmoid256_f32", "mth/tests/mth_vector_sigmoid256_f32_test.nas", 500_000, "MTH VECTOR SIGMOID256 F32 PASS", "native_verified"),
    Fixture("vector_tanh256_f32", "mth/tests/mth_vector_tanh256_f32_test.nas", 500_000, "MTH VECTOR TANH256 F32 PASS", "native_verified"),
    Fixture("prng_xorshift64", "mth/tests/mth_prng_xorshift64_test.nas", 20_000, "MTH PRNG XORSHIFT64 PASS", "native_verified"),
    Fixture("universe_map", "mth/tests/mth_universe_map_test.nas", 13_000_000, "MTH UNIVERSE MAP PASS", "native_verified"),
    # These include ../../nan0s/... sources. Pass --nan0s-root at the canonical
    # pinned commit (fe63617) so the registry exposes nmr_contract_put and the
    # route linker sources.
    Fixture("preflight_typed", "mth/tests/mth_preflight_test.nas", 2_000_000, "MTH TYPED PREFLIGHT PASS", "native_verified", requires_nan0s_sources=True),
    Fixture("native_dispatch", "mth/tests/mth_linker_preflight_test.nas", 3_000_000, "MTH NATIVE DISPATCH PASS", "native_verified", requires_nan0s_sources=True),
    Fixture("native_vector_addsub_dispatch", "mth/tests/mth_native_vector_addsub_dispatch_test.nas", 4_000_000, "MTH NATIVE VECTOR ADDSUB DISPATCH PASS", "native_verified"),
)


def _staged_source(fixture: Fixture, nan0s: Path, out_dir: Path) -> Path:
    """Mirror ``mth/`` beside the canonical NaN0S tree for external includes."""
    stage_root = out_dir / "stage"
    if not stage_root.exists():
        shutil.copytree(REPO_ROOT / "mth", stage_root / "mth")
        (stage_root / "nan0s").symlink_to(nan0s.resolve(), target_is_directory=True)
    return stage_root / fixture.path


def run_one(fixture: Fixture, nan0s: Path, out_dir: Path) -> tuple[bool, str]:
    source = REPO_ROOT / fixture.path
    if not source.exists():
        return False, f"MISSING {fixture.path}"
    if fixture.requires_nan0s_sources:
        source = _staged_source(fixture, nan0s, out_dir)
    image = out_dir / f"{fixture.name}.nan"
    assemble = subprocess.run(
        ["awk", "-f", str(nan0s / "tools/nmk.awk"), "-v", "CMD=emit", str(source)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    image.write_text(assemble.stdout, encoding="utf-8")
    if assemble.returncode != 0:
        return False, f"ASSEMBLE FAIL\n{assemble.stderr.strip()}"
    execute = subprocess.run(
        [
            str(nan0s / "aarch64/android/nan_cli"),
            "--img", str(image),
            "--steps", str(fixture.steps),
            "--serial",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    output = execute.stdout + execute.stderr
    step_match = STEP_RE.search(output)
    steps = step_match.group(1) if step_match else "?"
    if fixture.marker not in output:
        return False, f"MARKER FAIL ({fixture.marker}); steps={steps}\n{output.strip()}"
    return True, f"PASS steps={steps} marker={fixture.marker}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nan0s-root", type=Path, default=DEFAULT_NAN0S)
    parser.add_argument("--only", action="append", default=[], help="run only these fixture names")
    parser.add_argument("--list", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        for fixture in FIXTURES:
            print(f"{fixture.name}\t{fixture.status}\t{fixture.path}")
        return 0
    selected = set(args.only)
    fixtures = [f for f in FIXTURES if not selected or f.name in selected]
    if selected - {f.name for f in fixtures}:
        print(f"unknown fixture(s): {sorted(selected - {f.name for f in fixtures})}", file=sys.stderr)
        return 2
    failures = 0
    with tempfile.TemporaryDirectory(prefix="mth-fixtures-") as temp:
        out_dir = Path(temp)
        for fixture in fixtures:
            ok, detail = run_one(fixture, args.nan0s_root, out_dir)
            print(f"[{'PASS' if ok else 'FAIL'}] {fixture.name}: {detail}")
            failures += 0 if ok else 1
    print(f"{len(fixtures) - failures}/{len(fixtures)} fixtures passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
