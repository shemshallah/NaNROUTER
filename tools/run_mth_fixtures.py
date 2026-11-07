#!/usr/bin/env python3
"""Run NaN16 MTH fixtures with the canonical NaN0S assembler and harness.

This is a test-harness orchestrator only. It does not calculate expected
mathematical results on behalf of the guest; it assembles, launches, collects
serial output, and checks the fixture's PASS marker.
"""
from __future__ import annotations

import argparse
import re
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


FIXTURES: tuple[Fixture, ...] = (
    Fixture("k256", "mth/tests/mth_k256_laplacian_test.nas", 2_000_000, "MTH K256 LAPLACIAN PASS", "native_verified"),
    Fixture("k255", "mth/tests/mth_k255_laplacian_test.nas", 4_000_000, "MTH K255 LAPLACIAN PASS", "native_verified"),
    Fixture("ring255", "mth/tests/mth_ring255_laplacian_test.nas", 4_000_000, "MTH RING255 LAPLACIAN PASS", "native_verified"),
    Fixture("ring255_port", "mth/tests/mth_ring255_port_test.nas", 4_000_000, "MTH RING255 PORT ASSEMBLE PASS", "native_verified"),
    Fixture("sparse", "mth/tests/mth_sparse_graph_laplacian_test.nas", 4_000_000, "MTH SPARSE GRAPH LAPLACIAN PASS", "native_verified"),
    Fixture("weighted_sparse", "mth/tests/mth_sparse_weighted_graph_laplacian_v2_test.nas", 8_000_000, "MTH WEIGHTED CSR LAPLACIAN V2 PASS", "native_verified"),
    Fixture("energy", "mth/tests/mth_graph_energy_weighted_u8_q32_32_test.nas", 8_000_000, "MTH WEIGHTED GRAPH ENERGY PASS", "native_verified"),
    Fixture("components", "mth/tests/mth_graph_components_256_test.nas", 8_000_000, "MTH GRAPH COMPONENTS PASS", "native_verified"),
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
    Fixture("centro128", "mth/tests/mth_centrosymmetry_128_test.nas", 10_000_000, "MTH CENTROSYMMETRY 128 PASS", "native_verified"),
    Fixture("centro256b", "mth/tests/mth_centrosymmetry_block16_test.nas", 20_000_000, "MTH CENTROSYMMETRY BLOCK16 PASS", "native_verified"),
    Fixture("centro255b", "mth/tests/mth_centrosymmetry255_block15_test.nas", 20_000_000, "MTH CENTROSYMMETRY 255 BLOCK15 PASS", "native_verified"),
    Fixture("power128", "mth/tests/mth_power_iter128_test.nas", 50_000_000, "MTH POWER_ITER128 PASS", "native_verified"),
    Fixture("pair_full", "mth/tests/mth_graph_pair_test.nas", 100_000_000, "MTH GRAPH PAIR FULL 128 PASS", "native_verified"),
    Fixture("pair_tile16", "mth/tests/mth_graph_pair_tile16_f32_test.nas", 30_000_000, "MTH PAIR TILE16 F32 PASS", "native_verified"),
    Fixture("pair_tile16_k16", "mth/tests/mth_graph_pair_tile16_k16_f32_test.nas", 1_000_000, "MTH PAIR TILE16 K16 ACCUM PASS", "native_verified"),
    Fixture("pair_rank1", "mth/tests/mth_graph_pair_rank1_128_test.nas", 30_000_000, "MTH GRAPH PAIR RANK1 128 PASS", "native_verified"),
    Fixture("lowrank128", "mth/tests/mth_lowrank_add_128_test.nas", 20_000_000, "MTH LOWRANK ADD 128 PASS", "native_verified"),
    Fixture("adapter128", "mth/tests/mth_adapter_residual_128_test.nas", 30_000_000, "MTH ADAPTER RESIDUAL 128 PASS", "native_verified"),
    Fixture("adapter256b", "mth/tests/mth_adapter_residual_256_block16_test.nas", 20_000_000, "MTH ADAPTER RESIDUAL 256 BLOCK16 PASS", "native_verified"),
    Fixture("encode_decode", "mth/tests/mth_encode_decode_test.nas", 30_000_000, "MTH ENCODE DECODE PASS", "native_verified"),
    Fixture("svd128", "mth/tests/mth_svd_top128_test.nas", 100_000_000, "MTH SVD TOP128 PASS", "native_verified"),
    Fixture("dft256", "mth/tests/mth_graph_dft256_test.nas", 50_000_000, "MTH GRAPH DFT256 PASS", "native_verified"),
    Fixture("dft255", "mth/tests/mth_graph_dft255_test.nas", 40_000_000, "MTH GRAPH DFT255 PASS", "native_verified"),
    Fixture("couple128", "mth/tests/mth_graph_couple_128_test.nas", 4_000_000, "MTH GRAPH COUPLE 128 PASS", "native_verified"),
    Fixture("transmission128", "mth/tests/mth_graph_transmission_128_test.nas", 4_000_000, "MTH GRAPH TRANSMISSION 128 PASS", "native_verified"),
    Fixture("two_level", "mth/tests/mth_two_level_spectrum_test.nas", 1_000_000, "MTH TWO LEVEL SPECTRUM PASS", "native_verified"),
    Fixture("phase_coherence", "mth/tests/mth_phase_coherence_128_test.nas", 4_000_000, "MTH PHASE COHERENCE 128 PASS", "native_verified"),
)


def run_one(fixture: Fixture, nan0s: Path, out_dir: Path) -> tuple[bool, str]:
    source = REPO_ROOT / fixture.path
    if not source.exists():
        return False, f"MISSING {fixture.path}"
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
