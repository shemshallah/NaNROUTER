"""NaN0S CLI bridge for native MTH pair-tile guest kernels."""
from __future__ import annotations
import re, subprocess, tempfile, threading
from pathlib import Path
from typing import Mapping
from .mth_pair_tile_executor import NAN16_WORD_BYTES, OperatorSnapshot, PairTileExecutionError, PairTilePageSource, OUTPUT_TILE_BYTES
from .wave_tile_orchestrator import TileDescriptor

_WORD_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
_STATUS_RE = re.compile(r"\brc=(\d+),\s*pc=\d+,\s*trap='([^']*)'")

def _payload(raw: bytes) -> int:
    if len(raw) != 8: raise PairTileExecutionError("NaN16 word must be eight bytes")
    return (int.from_bytes(raw, "little") >> 16) & 0xFFFFFFFF

def _raw_word(payload: int) -> bytes:
    if isinstance(payload, bool) or not isinstance(payload, int) or not 0 <= payload <= 0xFFFFFFFF:
        raise PairTileExecutionError("payload must be unsigned 32-bit")
    head = 0x7FF8
    raw = (head << 48) | (payload << 16) | (head >> 8) | ((head & 255) << 8)
    return raw.to_bytes(8, "little")

def _render_words(data: bytes) -> str:
    if len(data) % 8: raise PairTileExecutionError("NaN16 byte data is not word-aligned")
    return "".join(f".word 0x{_payload(data[i:i+8]):08X}\n" for i in range(0, len(data), 8))

def _parse_peek(stdout: str, stderr: str, expected: int) -> bytes:
    status = _STATUS_RE.search(stderr)
    if not status or status.group(1) != "3" or status.group(2):
        raise PairTileExecutionError(f"NaN16 guest did not halt cleanly: {stderr.strip()}")
    words = [x.strip() for x in stdout.splitlines() if _WORD_RE.fullmatch(x.strip())]
    if len(words) != expected: raise PairTileExecutionError(f"--peek returned {len(words)} words, expected {expected}")
    return b"".join(_raw_word(int(x, 16)) for x in words)

class NaN0SCLIPairTileGuest:
    """Each method launches an isolated native NaN0S VM; host performs no arithmetic."""
    def __init__(self, *, source: PairTilePageSource, repo_root: str|Path|None=None,
                 nan0s_root: str|Path="nan0s", k16_steps: int=5_000_000,
                 reference_steps: int=30_000_000, timeout_seconds: float=180.0):
        self.source=source
        self.repo_root=Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
        nr=Path(nan0s_root); self.nan0s_root=nr if nr.is_absolute() else (self.repo_root/nr).resolve()
        self.assembler=self.nan0s_root/"tools"/"nmk.awk"
        self.nan_cli=self.nan0s_root/"aarch64"/"android"/"nan_cli"
        if k16_steps<1 or reference_steps<1 or timeout_seconds<=0: raise PairTileExecutionError("invalid guest limits")
        self.k16_steps=k16_steps; self.reference_steps=reference_steps; self.timeout_seconds=timeout_seconds
        self._lock=threading.Lock(); self._u_cache={}; self._row_cache={}

    def _run(self, text: str, status: int, output: int, steps: int) -> bytes:
        if not self.assembler.is_file(): raise PairTileExecutionError(f"assembler missing: {self.assembler}")
        if not self.nan_cli.is_file(): raise PairTileExecutionError(f"nan_cli missing: {self.nan_cli}")
        source_dir=self.repo_root/"mth"/"tests"; source_dir.mkdir(parents=True,exist_ok=True)
        src=None
        try:
            with tempfile.NamedTemporaryFile("w",encoding="utf-8",suffix=".nas",prefix=".pair_guest_",dir=source_dir,delete=False) as f:
                src=Path(f.name); f.write(text)
            with tempfile.TemporaryDirectory(prefix="mth-pair-guest-") as td:
                image=Path(td)/"guest.nan"
                a=subprocess.run(["awk","-f",str(self.assembler),"-v","CMD=emit",str(src)],cwd=self.repo_root,text=True,capture_output=True,timeout=self.timeout_seconds)
                if a.returncode: raise PairTileExecutionError(f"NaN16 assembly failed: {a.stderr.strip()}")
                image.write_text(a.stdout,encoding="utf-8")
                x=subprocess.run([str(self.nan_cli),"--img",str(image),"--steps",str(steps),"--peek",f"{status}:1,{output}:256"],cwd=self.repo_root,text=True,capture_output=True,timeout=self.timeout_seconds)
                if x.returncode: raise PairTileExecutionError(f"nan_cli exited {x.returncode}: {x.stderr.strip()}")
                return _parse_peek(x.stdout,x.stderr,257)
        except subprocess.TimeoutExpired as exc: raise PairTileExecutionError("NaN16 guest timed out") from exc
        finally:
            if src is not None: src.unlink(missing_ok=True)

    @staticmethod
    def _tile(raw: bytes) -> bytes:
        if len(raw)!=257*8: raise PairTileExecutionError("invalid status/tile result length")
        if _payload(raw[:8])!=1: raise PairTileExecutionError("NaN16 guest reported kernel failure")
        tile=raw[8:]
        if len(tile)!=OUTPUT_TILE_BYTES: raise PairTileExecutionError("invalid tile byte length")
        return tile

    def run_k16_driver(self, descriptor: TileDescriptor, strips: Mapping[str,bytes], snapshot: OperatorSnapshot) -> bytes:
        snapshot.validate()
        names=("L_IK","U_KJ","U_IK","L_JK")
        if tuple(strips)!=names or any(not isinstance(strips[n],bytes) or len(strips[n])!=32768 for n in names):
            raise PairTileExecutionError("K16 guest requires four ordered 4096-word strips")
        src=[
            ".org 0","JMP @pair_guest_entry",
            '.include "../nan16/mth_graph_pair_tile16_k16_f32.nas"',
            '.include "../nan16/mth_graph_pair_tile16_k16_driver_f32.nas"',
            "pair_guest_entry:","MOVI r13,1","LA r1,@pair_li","LA r2,@pair_ukj","LA r3,@pair_uik","LA r4,@pair_ljk",
            "LA r5,@pair_acc_lu","LA r6,@pair_acc_ult","LA r7,@pair_scratch","LA r8,@pair_output",
            "CALL @mth_graph_pair_tile16_k16_driver_f32","MOVI r2,1","CMP r1,r2","JMP[NE] @pair_fail",
            "MOVI r1,1","LA r2,@pair_status","ST r1,r2,0","HALT","pair_fail:",
            "MOVI r1,0","LA r2,@pair_status","ST r1,r2,0","HALT",".org 1024",
            "pair_li:",_render_words(strips["L_IK"]),"pair_ukj:",_render_words(strips["U_KJ"]),
            "pair_uik:",_render_words(strips["U_IK"]),"pair_ljk:",_render_words(strips["L_JK"]),
            ".org 17408","pair_acc_lu:",*[".word 0"]*256,"pair_acc_ult:",*[".word 0"]*256,
            "pair_output:",*[".word 0"]*256,"pair_scratch:",*[".word 0"]*6,
            ".org 18440","pair_status:",".word 0"]
        return self._tile(self._run("\n".join(src)+"\n",18440,17920,self.k16_steps))

    def _row(self,snapshot:OperatorSnapshot,matrix:str,row_base:int)->bytes:
        key=(snapshot.operator_digest,matrix,row_base)
        with self._lock: cached=self._row_cache.get(key)
        if cached is not None:return cached
        page=self.source.read_strip(snapshot,matrix=matrix,row_base=row_base,col_base=0,rows=16,cols=256)
        page.validate_for(snapshot,matrix=matrix,row_base=row_base,col_base=0,rows=16,cols=256)
        with self._lock:self._row_cache[key]=page.data
        return page.data

    def _full_u(self,snapshot:OperatorSnapshot)->bytes:
        with self._lock: cached=self._u_cache.get(snapshot.operator_digest)
        if cached is not None:return cached
        data=b"".join(self._row(snapshot,"U",r) for r in range(0,256,16))
        if len(data)!=65536*8:raise PairTileExecutionError("full-U staging length mismatch")
        with self._lock:self._u_cache[snapshot.operator_digest]=data
        return data

    def run_full_u_reference(self,descriptor:TileDescriptor,snapshot:OperatorSnapshot)->bytes:
        snapshot.validate(); u=self._full_u(snapshot)
        li=self._row(snapshot,"L",descriptor.i_base); lj=self._row(snapshot,"L",descriptor.j_base)
        src=[
            ".org 0","JMP @pair_ref_entry",'.include "../nan16/mth_graph_pair_tile16_f32.nas"',
            "pair_ref_entry:","LA r1,@pair_u","LA r2,@pair_li","LA r3,@pair_lj","LA r4,@pair_y",
            f"MOVI r5,{descriptor.i_base}",f"MOVI r6,{descriptor.j_base}","LA r7,@pair_scratch","MOVI r13,1",
            "CALL @mth_graph_pair_tile16_f32","MOVI r2,1","CMP r1,r2","JMP[NE] @pair_ref_fail",
            "MOVI r1,1","LA r2,@pair_status","ST r1,r2,0","HALT","pair_ref_fail:",
            "MOVI r1,0","LA r2,@pair_status","ST r1,r2,0","HALT",".org 1024",
            "pair_u:",_render_words(u),"pair_li:",_render_words(li),"pair_lj:",_render_words(lj),
            "pair_y:",*[".word 0"]*256,"pair_scratch:",*[".word 0"]*6,
            ".org 75014","pair_status:",".word 0"]
        return self._tile(self._run("\n".join(src)+"\n",75014,74752,self.reference_steps))

__all__=["NaN0SCLIPairTileGuest","_payload","_raw_word","_render_words","_parse_peek"]
