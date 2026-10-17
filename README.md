# AArch64 Compiler Optimization Study

GCC vs Clang cross-compiling three kernels for AArch64, executed under `qemu-aarch64`,
with vectorization-report parsing and NEON instruction counting.

| Kernel | Variants |
|---|---|
| `src/matrix_mul.cpp` | `naive_ijk`, `reordered_ikj` |
| `src/fft.cpp` | iterative radix-2 FFT (`radix2_iterative`) |
| `src/dot_product.cpp` | `basic`, `restrict`, `unroll4`, `restrict_unroll4`, `restrict_unroll8`, each for `f32` and `i32` |

Every kernel verifies itself against a double-precision reference and exits non-zero on mismatch.

## Prerequisites (Debian/Ubuntu)

```bash
sudo apt install gcc-aarch64-linux-gnu libc6-dev-arm64-cross clang lld qemu-user python3 make git
make check-tools
```

## Usage

```bash
make                  # 2 compilers x {-O0,-O2,-O3} x 3 kernels: .s, vectorization report, static .elf
make run              # build, run under QEMU, write results/summary.md (+ json/csv)
python3 scripts/analyze_and_run.py --help
```

Build output, per `build/<gcc|clang>/<O0|O2|O3>/`:

| File | Content |
|---|---|
| `<kernel>.s` | raw AArch64 assembly (the binary is linked from this exact file) |
| `<kernel>.vec.txt` | GCC `-fopt-info-vec-all` (vectorized and missed; GCC allows only one opt-info file) / Clang `-Rpass=loop-vectorize -Rpass-missed=loop-vectorize` (+ `-Rpass-analysis=loop-vectorize` for the reasons) |
| `<kernel>.elf` | static AArch64 executable |

Useful variations:

```bash
make V=1                                              # show full command lines
make gcc | make clang                                 # one compiler only
make BUILD=build-fm EXTRA_FLAGS=-ffast-math           # float reductions become vectorizable
python3 scripts/analyze_and_run.py --build-dir build-fm --out results-fm
python3 scripts/analyze_and_run.py --arg matrix_mul=128 --runs 3     # smaller size, best of 3 launches
python3 scripts/analyze_and_run.py --no-run           # reports + NEON counts only, no QEMU needed
```

Clang's assembly is linked with the GNU cross driver (`CLANG_LINK` defaults to `$(GCC_CC)`): `clang --sysroot=`
breaks glibc's `libm.a` linker script on Debian/Ubuntu. Compilation and vectorization reports are pure Clang.

## Reading the results

- QEMU user-mode timing is emulation time, not real-core time; NEON instructions are emulated by helper
  code. Trust the vectorization and NEON columns for codegen questions; treat runtimes as relative.
- `-O0` runs no vectorizer, so empty reports and zero NEON instructions there are expected.
  GCC enables auto-vectorization at `-O2` only from version 12.
- Float reductions (naive matmul, `f32` dot) do not vectorize without `-ffast-math`; the multi-accumulator
  dot-product variants and the `i32` rows show how much of that is reassociation rather than aliasing.

## Publishing

```bash
./scripts/push_to_github.sh
```

Creates/updates `.gitignore` (binaries, `*.s`, `build*/` are never committed), commits, and pushes to
`https://github.com/Usernamevidhya/aarch64-compiler-study.git`. The empty GitHub repo must already exist and
git must have credentials for it. Override the target with `REPO_URL=...`.
