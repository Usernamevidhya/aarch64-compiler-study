#!/usr/bin/env python3
"""Run the AArch64 benchmark binaries under QEMU and compare GCC vs Clang.

For every build/<compiler>/<opt>/<kernel> configuration this script:

  1. parses the vectorization report
       gcc   : <kernel>.vec.txt (-fopt-info-vec-all: vectorized + missed)
       clang : <kernel>.vec.txt (-Rpass / -Rpass-missed / -Rpass-analysis = loop-vectorize)
  2. counts NEON (Advanced SIMD) instructions in <kernel>.s, overall and inside
     the kernel functions only (symbols containing "kern_")
  3. runs <kernel>.elf under qemu-aarch64 and parses its RESULT lines
     (timing + self-verification against a double-precision reference)

and writes summary.md, results.json, runtime.csv and vectorization.csv.

Exit status: 0 = everything ran and verified, 1 = a run failed or a result did
not verify, 2 = nothing to analyse / bad invocation.

Note on timing: qemu-aarch64 is a functional emulator (TCG). Its wall-clock
times reflect translated-instruction counts and helper-call costs, not the
pipeline of a real Cortex/Neoverse core. Use them for relative, same-machine
comparisons; use the vectorization and NEON counts for the codegen story.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

COMPILERS = ("gcc", "clang")
OPTS = ("O0", "O2", "O3")
KERNELS = ("matrix_mul", "fft", "dot_product")

# --------------------------------------------------------------------------- #
# Vectorization reports
# --------------------------------------------------------------------------- #

GCC_LINE = re.compile(r"^(?P<loc>[^\s:]+:\d+:\d+): (?P<kind>optimized|missed|note): +(?P<msg>.*)$")
CLANG_LINE = re.compile(
    r"^(?P<loc>[^\s:]+:\d+:\d+): remark: (?P<msg>.*?) \[-Rpass(?P<kind>-missed|-analysis)?=loop-vectorize\]\s*$"
)
GCC_BYTES = re.compile(r"using (\d+) byte vectors")
CLANG_WIDTH = re.compile(r"vectorization width: (\d+), interleaved count: (\d+)")


def empty_vec_report(available: bool = False) -> dict:
    return {
        "available": available,
        "vectorized_events": 0,  # raw "loop vectorized" messages (includes epilogues, instantiations)
        "vectorized_sites": 0,  # distinct source locations that were vectorized
        "slp_events": 0,  # GCC basic-block (SLP) vectorization messages
        "interleaved_events": 0,  # Clang: loops interleaved but not vectorized
        "missed_sites": 0,  # distinct locations reported as not vectorized (and never vectorized)
        "widths": {},
        "missed_reasons": {},
    }


def parse_gcc_vec(opt_text: str | None, missed_text: str | None) -> dict:
    # -fopt-info-vec-all puts optimized and missed messages in one file; older
    # layouts used a separate vec-missed file. Fall back to the main file.
    if missed_text is None:
        missed_text = opt_text
    rep = empty_vec_report(available=opt_text is not None or missed_text is not None)
    vec_locs: set[str] = set()
    miss_locs: set[str] = set()
    widths: Counter = Counter()
    reasons: Counter = Counter()

    for line in (opt_text or "").splitlines():
        m = GCC_LINE.match(line)
        if not m or m["kind"] != "optimized":
            continue
        msg = m["msg"]
        if "loop vectorized" in msg:
            rep["vectorized_events"] += 1
            vec_locs.add(m["loc"])
            w = GCC_BYTES.search(msg)
            if w:
                widths[f"{int(w.group(1)) * 8}-bit"] += 1
        elif "basic block part vectorized" in msg or "basic block vectorized" in msg:
            rep["slp_events"] += 1

    for line in (missed_text or "").splitlines():
        m = GCC_LINE.match(line)
        if not m or m["kind"] != "missed":
            continue
        msg = m["msg"].strip()
        if "couldn't vectorize loop" in msg:
            miss_locs.add(m["loc"])
        r = re.search(r"not vectorized: ([^:]+)", msg)
        if r:
            reasons[r.group(1).strip().rstrip(".")] += 1

    rep["vectorized_sites"] = len(vec_locs)
    rep["missed_sites"] = len(miss_locs - vec_locs)
    rep["widths"] = dict(widths)
    rep["missed_reasons"] = dict(reasons)
    return rep


def parse_clang_vec(text: str | None) -> dict:
    """Clang remarks (-Rpass / -Rpass-missed / -Rpass-analysis = loop-vectorize).

    -Rpass-missed only says "loop not vectorized"; the cause is in the matching
    -Rpass-analysis remark at the same source location, so reasons are collected
    per location and only reported for loops that were never vectorized.
    """
    rep = empty_vec_report(available=text is not None)
    vec_locs: set[str] = set()
    miss_locs: set[str] = set()
    loc_reason: dict[str, str] = {}
    widths: Counter = Counter()

    for line in (text or "").splitlines():
        m = CLANG_LINE.match(line)
        if not m:
            continue
        msg, loc, kind = m["msg"], m["loc"], m["kind"] or ""
        if kind == "-analysis":
            if msg.startswith("loop not vectorized"):
                reason = msg.partition(":")[2].split(";")[0].split(". Use ")[0].strip().rstrip(".")
                if reason and loc not in loc_reason:
                    loc_reason[loc] = reason
            continue
        if msg.startswith("vectorized loop"):
            rep["vectorized_events"] += 1
            vec_locs.add(loc)
            w = CLANG_WIDTH.search(msg)
            if w:
                widths[f"VF{w.group(1)}/IC{w.group(2)}"] += 1
        elif msg.startswith("interleaved loop"):
            rep["interleaved_events"] += 1
        elif msg.startswith("loop not vectorized"):
            miss_locs.add(loc)
            reason = msg.partition(":")[2].split(";")[0].strip().rstrip(".")
            if reason and loc not in loc_reason:
                loc_reason[loc] = reason

    missed = miss_locs - vec_locs
    reasons: Counter = Counter(loc_reason.get(loc, "unspecified") for loc in missed)
    rep["vectorized_sites"] = len(vec_locs)
    rep["missed_sites"] = len(missed)
    rep["widths"] = dict(widths)
    rep["missed_reasons"] = dict(reasons)
    return rep


# --------------------------------------------------------------------------- #
# Assembly analysis (NEON instruction counting)
# --------------------------------------------------------------------------- #

FUNC_TYPE = re.compile(r"^\s*\.type\s+([^,\s]+)\s*,\s*[%@]function")
LABEL = re.compile(r"^([A-Za-z_$][\w$.@]*):")
# Vector register with arrangement or lane: v0.4s, v1.16b, v2.2d, v3.s[1]
VEC_ARR = re.compile(r"\bv\d{1,2}\.\d*[bhsdq](?:\[\d+\])?")
QREG = re.compile(r"\bq\d{1,2}\b")
SCALAR_FP_REG = re.compile(r"\b[hsd]\d{1,2}\b")
Q_LDST = {"ldr", "str", "ldp", "stp", "ldur", "stur", "ldnp", "stnp"}
KERNEL_MARK = "kern_"


def classify(mnemonic: str, operands: str) -> str:
    """'neon' (vector arrangement), 'neon_q' (128-bit q-reg load/store),
    'scalar_fp' (f* instruction on s/d/h regs) or 'other'."""
    if VEC_ARR.search(operands):
        return "neon"
    if mnemonic in Q_LDST and QREG.search(operands):
        return "neon_q"
    if mnemonic.startswith("f") and SCALAR_FP_REG.search(operands):
        return "scalar_fp"
    return "other"


def analyze_asm(path: Path) -> dict | None:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None

    funcs = {m.group(1) for line in lines if (m := FUNC_TYPE.match(line))}
    per_func: dict[str, Counter] = defaultdict(Counter)
    kernel_ops: Counter = Counter()
    current: str | None = None

    for raw in lines:
        line = raw.split("//")[0].strip()
        if not line or line.startswith("#"):
            continue
        lm = LABEL.match(line)
        if lm:
            if lm.group(1) in funcs:
                current = lm.group(1)
            line = line[lm.end():].strip()
            if not line:
                continue
        if line.startswith(".") or current is None:
            continue
        parts = line.split(None, 1)
        mnemonic = parts[0].lower()
        operands = parts[1] if len(parts) > 1 else ""
        kind = classify(mnemonic, operands)
        c = per_func[current]
        c["total"] += 1
        if kind in ("neon", "neon_q"):
            c["neon"] += 1
            if KERNEL_MARK in current:
                kernel_ops[mnemonic + (".q" if kind == "neon_q" else "")] += 1
        elif kind == "scalar_fp":
            c["scalar_fp"] += 1

    def total(key: str, only_kernel: bool = False) -> int:
        return sum(c[key] for name, c in per_func.items() if not only_kernel or KERNEL_MARK in name)

    return {
        "total_insns": total("total"),
        "neon_insns": total("neon"),
        "scalar_fp_insns": total("scalar_fp"),
        "kernel_total_insns": total("total", True),
        "kernel_neon_insns": total("neon", True),
        "kernel_scalar_fp_insns": total("scalar_fp", True),
        "top_neon_ops": kernel_ops.most_common(5),
        "kernel_functions": {
            name: {"total": c["total"], "neon": c["neon"], "scalar_fp": c["scalar_fp"]}
            for name, c in sorted(per_func.items())
            if KERNEL_MARK in name
        },
    }


# --------------------------------------------------------------------------- #
# Running binaries
# --------------------------------------------------------------------------- #

RESULT_TOKEN = re.compile(r"(\w+)=(\S+)")


def parse_results(stdout: str) -> list[dict]:
    rows = []
    for line in stdout.splitlines():
        if not line.startswith("RESULT "):
            continue
        kv = dict(RESULT_TOKEN.findall(line))
        try:
            rows.append(
                {
                    "variant": kv["variant"],
                    "n": int(kv["n"]),
                    "reps": int(kv["reps"]),
                    "time_ms": float(kv["time_ms"]),
                    "err": float(kv["err"]),
                    "status": kv["status"],
                }
            )
        except (KeyError, ValueError):
            continue
    return rows


def run_binary(cmd: list[str], timeout: float) -> dict:
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"state": "timeout", "returncode": None, "wall_s": timeout, "results": [], "stderr": ""}
    except OSError as exc:
        return {"state": "error", "returncode": None, "wall_s": 0.0, "results": [], "stderr": str(exc)}
    wall = time.perf_counter() - t0
    results = parse_results(p.stdout)
    state = "ok" if p.returncode == 0 and results else "failed"
    return {
        "state": state,
        "returncode": p.returncode,
        "wall_s": wall,
        "results": results,
        "stderr": p.stderr.strip()[-500:],
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def md_table(headers: list[str], rows: list[list]) -> str:
    def esc(x) -> str:
        return str(x).replace("|", "\\|")

    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def geomean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else None


def fmt_widths(widths: dict) -> str:
    return ", ".join(f"{k}×{v}" for k, v in sorted(widths.items())) or "—"


def build_summary(cfgs: dict, rows: list[dict], meta: dict) -> str:
    kernels = [k for k in KERNELS if any(c[2] == k for c in cfgs)]
    configs = [(c, o) for c in COMPILERS for o in OPTS]
    out: list[str] = ["# AArch64 compiler study: GCC vs Clang", ""]
    out.append(
        f"- GCC: `{meta['gcc_version']}`  \n- Clang: `{meta['clang_version']}`  \n"
        f"- Execution: `{meta['runner']}`  \n- Host: `{meta['host']}`  \n- Generated: {meta['when']}"
    )

    # ---- highlights -----------------------------------------------------
    by_time = {(r["compiler"], r["opt"], r["kernel"], r["variant"]): r for r in rows}
    out += ["", "## Highlights", ""]
    for k in kernels:
        for o in ("O2", "O3"):
            variants = sorted({r["variant"] for r in rows if r["kernel"] == k})
            ratios = []
            for v in variants:
                g, c = by_time.get(("gcc", o, k, v)), by_time.get(("clang", o, k, v))
                if g and c and g["time_ms"] > 0 and c["time_ms"] > 0:
                    ratios.append(c["time_ms"] / g["time_ms"])
            gm = geomean(ratios)
            gn = cfgs.get(("gcc", o, k), {}).get("asm") or {}
            cn = cfgs.get(("clang", o, k), {}).get("asm") or {}
            parts = []
            if gm is not None:
                parts.append(
                    f"clang/gcc runtime geomean {gm:.2f}× ({'clang faster' if gm < 1 else 'gcc faster' if gm > 1 else 'tie'})"
                )
            if gn or cn:
                parts.append(
                    f"NEON insns in kernel code gcc={gn.get('kernel_neon_insns', 'n/a')} "
                    f"clang={cn.get('kernel_neon_insns', 'n/a')}"
                )
            if parts:
                out.append(f"- **{k} -{o}**: " + "; ".join(parts))

    # ---- vectorization + NEON table ------------------------------------------
    out += ["", "## Vectorization reports and NEON instruction counts", ""]
    out.append(
        "`Vec sites` = distinct source loops reported vectorized (raw messages in parentheses; epilogues and "
        "template instantiations add messages). `Missed` = loops reported not vectorized that were never "
        "vectorized. `NEON (kernel)` counts Advanced SIMD instructions inside the `kern_*` functions only."
    )
    for k in kernels:
        out += ["", f"### {k}", ""]
        trs = []
        for comp, opt in configs:
            c = cfgs.get((comp, opt, k))
            if not c:
                continue
            v, a = c["vec"], c["asm"]
            vec_cell = f"{v['vectorized_sites']} ({v['vectorized_events']})" if v["available"] else "n/a"
            missed = v["missed_sites"] if v["available"] else "n/a"
            if a:
                kt, kn = a["kernel_total_insns"], a["kernel_neon_insns"]
                pct = f"{100 * kn / kt:.1f}%" if kt else "—"
                neon = f"{kn} / {kt}"
                ops = ", ".join(f"{m}×{n}" for m, n in a["top_neon_ops"][:3]) or "—"
            else:
                neon, pct, ops = "n/a", "n/a", "—"
            extra = fmt_widths(v["widths"])
            if v["slp_events"]:
                extra += f"; SLP×{v['slp_events']}"
            trs.append([comp, f"-{opt}", vec_cell, missed, neon, pct, extra, ops])
        out.append(
            md_table(
                ["Compiler", "Opt", "Vec sites (msgs)", "Missed", "NEON / kernel insns", "NEON %", "Vector widths", "Top NEON ops"],
                trs,
            )
        )

    # ---- runtimes ---------------------------------------------------------------
    out += ["", "## Runtime (ms, best of reps, lower is better)", ""]
    out.append(
        "A trailing `!` marks a result that failed self-verification. `clang/gcc` < 1 means Clang's binary ran faster."
    )
    for k in kernels:
        variants = []
        for r in rows:
            if r["kernel"] == k and r["variant"] not in variants:
                variants.append(r["variant"])
        if not variants:
            continue
        headers = ["Variant"] + [f"{c} -{o}" for c, o in configs] + ["clang/gcc O2", "clang/gcc O3"]
        trs = []
        for v in variants:
            cells, vals = [v], {}
            for c, o in configs:
                r = by_time.get((c, o, k, v))
                if r:
                    vals[(c, o)] = r["time_ms"]
                    cells.append(f"{r['time_ms']:.2f}" + ("" if r["status"] == "OK" else "!"))
                else:
                    cells.append("—")
            for o in ("O2", "O3"):
                g, c = vals.get(("gcc", o)), vals.get(("clang", o))
                cells.append(f"{c / g:.2f}" if g and c else "—")
            trs.append(cells)
        out += ["", f"### {k}", "", md_table(headers, trs)]

    # ---- missed reasons ----------------------------------------------------------
    reason_rows = []
    for comp, opt in configs:
        for k in kernels:
            c = cfgs.get((comp, opt, k))
            if c and c["vec"]["missed_reasons"]:
                top = sorted(c["vec"]["missed_reasons"].items(), key=lambda kv: -kv[1])[:3]
                reason_rows.append([comp, f"-{opt}", k, "; ".join(f"{r} (×{n})" for r, n in top)])
    if reason_rows:
        out += ["", "## Most common missed-vectorization reasons", "", md_table(["Compiler", "Opt", "Kernel", "Top reasons"], reason_rows)]

    # ---- problems -------------------------------------------------------------------
    problems = [f"- {p}" for p in meta["problems"]]
    out += ["", "## Run problems", ""] + (problems or ["None: every binary ran and every result verified."])

    out += [
        "",
        "## Reading these numbers",
        "",
        "- QEMU user-mode timing is emulation time, not silicon time. NEON operations are emulated by helper "
        "code, so vectorized code can look slower or faster than it would on a real core. Treat runtime ratios as "
        "indicative and rely on the vectorization/NEON columns for what the compilers generated.",
        "- `-O0` runs no vectorizer, so empty reports and zero NEON instructions there are expected. GCC only "
        "enables auto-vectorization at `-O2` from version 12; older GCC reports nothing at `-O2`.",
        "- Float reductions (matmul `naive_ijk`, `f32` dot product) are not vectorized without `-ffast-math`, because "
        "that would reassociate the sum. Rebuild with `make BUILD=build-fm EXTRA_FLAGS=-ffast-math` to see the difference.",
    ]
    return "\n".join(out) + "\n"


def tool_version(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=20)
        return (p.stdout or p.stderr).splitlines()[0].strip() if (p.stdout or p.stderr) else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "not found"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-dir", default="build", help="directory produced by `make` (default: build)")
    ap.add_argument("--out", default="results", help="output directory (default: results)")
    ap.add_argument("--qemu", default="qemu-aarch64", help="QEMU user-mode binary, or 'none' to run natively on an AArch64 host")
    ap.add_argument("--qemu-args", default="-cpu max", help="extra QEMU arguments (default: '-cpu max')")
    ap.add_argument("--runs", type=int, default=1, help="process launches per binary; best time per variant is kept (default: 1)")
    ap.add_argument("--timeout", type=float, default=900, help="per-run timeout in seconds (default: 900)")
    ap.add_argument("--no-run", action="store_true", help="static analysis only: parse reports and assembly, do not execute")
    ap.add_argument("--arg", action="append", default=[], metavar="KERNEL=VALUE", help="positional argument passed to a kernel (repeatable, e.g. --arg matrix_mul=128)")
    ap.add_argument("--build", action="store_true", help="run `make` first")
    ap.add_argument("--make-args", default="", help="extra arguments for make when --build is given")
    ap.add_argument("--compilers", nargs="+", default=list(COMPILERS), choices=COMPILERS)
    ap.add_argument("--opts", nargs="+", default=list(OPTS))
    ap.add_argument("--kernels", nargs="+", default=list(KERNELS))
    args = ap.parse_args()

    build = Path(args.build_dir)
    out_dir = Path(args.out)

    if args.build:
        cmd = ["make", "-j", str(max(1, __import__("os").cpu_count() or 1)), f"BUILD={build}"] + shlex.split(args.make_args)
        print("+", " ".join(cmd), file=sys.stderr)
        if subprocess.run(cmd).returncode != 0:
            print("error: build failed", file=sys.stderr)
            return 2

    kernel_args: dict[str, list[str]] = defaultdict(list)
    for item in args.arg:
        k, sep, v = item.partition("=")
        if not sep:
            ap.error(f"--arg expects KERNEL=VALUE, got {item!r}")
        kernel_args[k].append(v)

    native = args.qemu.lower() == "none"
    qemu_cmd: list[str] = []
    if not args.no_run and not native:
        qemu_path = shutil.which(args.qemu)
        if not qemu_path:
            print(f"error: {args.qemu!r} not found (install qemu-user, pass --qemu none on an AArch64 host, or use --no-run)", file=sys.stderr)
            return 2
        qemu_cmd = [qemu_path] + shlex.split(args.qemu_args)
    if native and platform.machine() not in ("aarch64", "arm64") and not args.no_run:
        print(f"warning: --qemu none on a {platform.machine()} host will not run AArch64 binaries", file=sys.stderr)

    cfgs: dict[tuple, dict] = {}
    rows: list[dict] = []
    problems: list[str] = []

    for comp in args.compilers:
        for opt in args.opts:
            for kernel in args.kernels:
                d = build / comp / opt
                stem = d / kernel
                asm_path, elf_path = stem.with_suffix(".s"), stem.with_suffix(".elf")
                if not asm_path.exists() and not elf_path.exists():
                    continue

                def rd(p: Path) -> str | None:
                    try:
                        return p.read_text(errors="replace")
                    except OSError:
                        return None

                if comp == "gcc":
                    vec = parse_gcc_vec(rd(d / f"{kernel}.vec.txt"), rd(d / f"{kernel}.vec-missed.txt"))
                else:
                    vec = parse_clang_vec(rd(d / f"{kernel}.vec.txt"))
                asm = analyze_asm(asm_path)
                entry = {"vec": vec, "asm": asm, "run": None}
                cfgs[(comp, opt, kernel)] = entry

                label = f"{comp:5s} -{opt} {kernel:11s}"
                if args.no_run:
                    print(f"[{label}] analysed (no run)", file=sys.stderr)
                    continue
                if not elf_path.exists():
                    problems.append(f"{comp} -{opt} {kernel}: binary missing ({elf_path})")
                    print(f"[{label}] MISSING binary", file=sys.stderr)
                    continue

                cmd = qemu_cmd + [str(elf_path)] + kernel_args.get(kernel, [])
                best: dict[str, dict] = {}
                state, wall = "ok", 0.0
                for _ in range(max(1, args.runs)):
                    res = run_binary(cmd, args.timeout)
                    wall += res["wall_s"]
                    if res["state"] != "ok":
                        state = res["state"]
                        if res["state"] == "failed" and not res["results"]:
                            detail = res["stderr"] or f"exit code {res['returncode']}"
                            problems.append(f"{comp} -{opt} {kernel}: {detail}")
                        elif res["state"] != "failed":
                            problems.append(f"{comp} -{opt} {kernel}: {res['state']}")
                    for r in res["results"]:
                        prev = best.get(r["variant"])
                        if prev is None or r["time_ms"] < prev["time_ms"]:
                            best[r["variant"]] = r
                        if r["status"] != "OK":
                            best[r["variant"]]["status"] = r["status"]
                for v, r in best.items():
                    rows.append({"compiler": comp, "opt": opt, "kernel": kernel, **r})
                    if r["status"] != "OK":
                        problems.append(f"{comp} -{opt} {kernel}/{v}: verification FAILED (err={r['err']:.3e})")
                entry["run"] = {"state": state, "wall_s": round(wall, 2)}
                print(f"[{label}] {state:7s} {wall:7.1f}s  {len(best)} variants", file=sys.stderr)

    if not cfgs:
        print(f"error: no build artifacts found under {build}/<compiler>/<opt>/ (run `make` first)", file=sys.stderr)
        return 2

    meta = {
        "gcc_version": tool_version(["aarch64-linux-gnu-gcc"]),
        "clang_version": tool_version(["clang"]),
        "runner": "analysis only" if args.no_run else ("native" if native else " ".join(qemu_cmd)),
        "host": f"{platform.system()} {platform.machine()}",
        "when": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "problems": problems,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(cfgs, rows, meta)
    (out_dir / "summary.md").write_text(summary)
    (out_dir / "results.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "configs": [{"compiler": c, "opt": o, "kernel": k, **v} for (c, o, k), v in cfgs.items()],
                "runtime": rows,
            },
            indent=2,
        )
    )
    with open(out_dir / "runtime.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["compiler", "opt", "kernel", "variant", "n", "reps", "time_ms", "err", "status"])
        for r in rows:
            w.writerow([r["compiler"], r["opt"], r["kernel"], r["variant"], r["n"], r["reps"], r["time_ms"], r["err"], r["status"]])
    with open(out_dir / "vectorization.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["compiler", "opt", "kernel", "vec_sites", "vec_events", "missed_sites", "slp_events", "kernel_neon_insns", "kernel_insns", "total_neon_insns", "total_insns"])
        for (c, o, k), v in cfgs.items():
            a = v["asm"] or {}
            w.writerow([c, o, k, v["vec"]["vectorized_sites"], v["vec"]["vectorized_events"], v["vec"]["missed_sites"], v["vec"]["slp_events"],
                        a.get("kernel_neon_insns", ""), a.get("kernel_total_insns", ""), a.get("neon_insns", ""), a.get("total_insns", "")])

    print(summary)
    print(f"Wrote {out_dir}/summary.md, results.json, runtime.csv, vectorization.csv", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
