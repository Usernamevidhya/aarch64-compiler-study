# AArch64 compiler study: GCC vs Clang

- GCC: `aarch64-linux-gnu-gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`  
- Clang: `Ubuntu clang version 18.1.3 (1ubuntu1)`  
- Execution: `/usr/bin/qemu-aarch64 -cpu max`  
- Host: `Linux x86_64`  
- Generated: 2026-10-17 13:24:00 UTC

## Highlights

- **matrix_mul -O2**: clang/gcc runtime geomean 0.79× (clang faster); NEON insns in kernel code gcc=1 clang=6
- **matrix_mul -O3**: clang/gcc runtime geomean 1.02× (gcc faster); NEON insns in kernel code gcc=16 clang=6
- **fft -O2**: clang/gcc runtime geomean 0.87× (clang faster); NEON insns in kernel code gcc=0 clang=23
- **fft -O3**: clang/gcc runtime geomean 0.98× (clang faster); NEON insns in kernel code gcc=34 clang=23
- **dot_product -O2**: clang/gcc runtime geomean 0.69× (clang faster); NEON insns in kernel code gcc=66 clang=293
- **dot_product -O3**: clang/gcc runtime geomean 0.77× (clang faster); NEON insns in kernel code gcc=125 clang=293

## Vectorization reports and NEON instruction counts

`Vec sites` = distinct source loops reported vectorized (raw messages in parentheses; epilogues and template instantiations add messages). `Missed` = loops reported not vectorized that were never vectorized. `NEON (kernel)` counts Advanced SIMD instructions inside the `kern_*` functions only.

### matrix_mul

| Compiler | Opt | Vec sites (msgs) | Missed | NEON / kernel insns | NEON % | Vector widths | Top NEON ops |
|---|---|---|---|---|---|---|---|
| gcc | -O0 | 0 (0) | 0 | 0 / 163 | 0.0% | — | — |
| gcc | -O2 | 0 (0) | 13 | 1 / 83 | 1.2% | — | movi×1 |
| gcc | -O3 | 2 (4) | 12 | 16 / 210 | 7.6% | 128-bit×3, 64-bit×1 | ldr.q×5, fmla×5, dup×3 |
| clang | -O0 | 0 (0) | 0 | 0 / 159 | 0.0% | — | — |
| clang | -O2 | 2 (2) | 2 | 6 / 105 | 5.7% | VF4/IC2×2 | ldp.q×2, fmla×2, dup×1 |
| clang | -O3 | 2 (2) | 3 | 6 / 105 | 5.7% | VF4/IC2×2 | ldp.q×2, fmla×2, dup×1 |

### fft

| Compiler | Opt | Vec sites (msgs) | Missed | NEON / kernel insns | NEON % | Vector widths | Top NEON ops |
|---|---|---|---|---|---|---|---|
| gcc | -O0 | 0 (0) | 0 | 0 / 215 | 0.0% | — | — |
| gcc | -O2 | 0 (0) | 14 | 0 / 68 | 0.0% | — | — |
| gcc | -O3 | 1 (2) | 13 | 34 / 225 | 15.1% | 128-bit×1, 64-bit×1 | ins×8, ldr.q×6, fmul×4 |
| clang | -O0 | 0 (0) | 0 | 0 / 176 | 0.0% | — | — |
| clang | -O2 | 3 (3) | 7 | 23 / 164 | 14.0% | VF2/IC2×1, VF4/IC1×1, VF4/IC2×1 | ld1×6, ldr.q×4, str.q×4 |
| clang | -O3 | 3 (3) | 7 | 23 / 164 | 14.0% | VF2/IC2×1, VF4/IC1×1, VF4/IC2×1 | ld1×6, ldr.q×4, str.q×4 |

### dot_product

| Compiler | Opt | Vec sites (msgs) | Missed | NEON / kernel insns | NEON % | Vector widths | Top NEON ops |
|---|---|---|---|---|---|---|---|
| gcc | -O0 | 0 (0) | 0 | 0 / 942 | 0.0% | — | — |
| gcc | -O2 | 3 (6) | 8 | 66 / 307 | 21.5% | 128-bit×6 | dup×21, ldr.q×16, movi×11 |
| gcc | -O3 | 8 (16) | 3 | 125 / 684 | 18.3% | 128-bit×16 | ldr.q×36, dup×36, movi×20 |
| clang | -O0 | 0 (0) | 0 | 0 / 819 | 0.0% | — | — |
| clang | -O2 | 8 (16) | 2 | 293 / 888 | 33.0% | VF2/IC2×1, VF4/IC2×15 | mov×116, movi×42, mla×30 |
| clang | -O3 | 8 (16) | 2 | 293 / 888 | 33.0% | VF2/IC2×1, VF4/IC2×15 | mov×116, movi×42, mla×30 |

## Runtime (ms, best of reps, lower is better)

A trailing `!` marks a result that failed self-verification. `clang/gcc` < 1 means Clang's binary ran faster.

### matrix_mul

| Variant | gcc -O0 | gcc -O2 | gcc -O3 | clang -O0 | clang -O2 | clang -O3 | clang/gcc O2 | clang/gcc O3 |
|---|---|---|---|---|---|---|---|---|
| naive_ijk | 266.91 | 158.62 | 139.18 | 298.17 | 150.22 | 141.58 | 0.95 | 1.02 |
| reordered_ikj | 321.52 | 155.07 | 101.01 | 307.85 | 102.33 | 103.76 | 0.66 | 1.03 |

### fft

| Variant | gcc -O0 | gcc -O2 | gcc -O3 | clang -O0 | clang -O2 | clang -O3 | clang/gcc O2 | clang/gcc O3 |
|---|---|---|---|---|---|---|---|---|
| radix2_iterative | 36.64 | 18.94 | 16.87 | 35.62 | 16.55 | 16.59 | 0.87 | 0.98 |

### dot_product

| Variant | gcc -O0 | gcc -O2 | gcc -O3 | clang -O0 | clang -O2 | clang -O3 | clang/gcc O2 | clang/gcc O3 |
|---|---|---|---|---|---|---|---|---|
| f32_basic | 13.03 | 8.10 | 5.59 | 13.44 | 5.64 | 5.43 | 0.70 | 0.97 |
| f32_restrict | 13.29 | 8.05 | 5.58 | 13.78 | 5.40 | 5.44 | 0.67 | 0.97 |
| f32_unroll4 | 11.17 | 5.78 | 5.67 | 12.35 | 5.51 | 5.55 | 0.95 | 0.98 |
| f32_restrict_unroll4 | 10.49 | 5.69 | 5.67 | 11.42 | 5.65 | 5.69 | 0.99 | 1.01 |
| f32_restrict_unroll8 | 10.16 | 5.71 | 5.79 | 10.19 | 5.69 | 5.70 | 1.00 | 0.98 |
| i32_basic | 6.87 | 2.88 | 2.71 | 7.54 | 1.62 | 1.60 | 0.56 | 0.59 |
| i32_restrict | 6.71 | 2.91 | 2.79 | 7.59 | 1.62 | 1.62 | 0.56 | 0.58 |
| i32_unroll4 | 8.47 | 2.81 | 2.77 | 4.65 | 1.19 | 1.23 | 0.42 | 0.44 |
| i32_restrict_unroll4 | 4.59 | 2.80 | 2.78 | 4.66 | 1.20 | 1.41 | 0.43 | 0.51 |
| i32_restrict_unroll8 | 4.32 | 1.55 | 1.55 | 6.27 | 1.60 | 1.67 | 1.03 | 1.08 |

## Most common missed-vectorization reasons

| Compiler | Opt | Kernel | Top reasons |
|---|---|---|---|
| gcc | -O2 | matrix_mul | multiple nested loops (×3); control flow in loop (×2); unsupported use in stmt (×2) |
| gcc | -O2 | fft | relevant stmt not supported (×4); control flow in loop (×4); unsupported use in stmt (×2) |
| gcc | -O2 | dot_product | control flow in loop (×2); relevant stmt not supported (×2); unsupported use in stmt (×1) |
| gcc | -O3 | matrix_mul | multiple nested loops (×2); complicated access pattern (×2); control flow in loop (×2) |
| gcc | -O3 | fft | relevant stmt not supported (×4); control flow in loop (×3); number of iterations cannot be computed (×2) |
| gcc | -O3 | dot_product | control flow in loop (×2); relevant stmt not supported (×2); unsupported use in stmt (×1) |
| clang | -O2 | matrix_mul | value that could not be identified as reduction is used outside the loop (×2) |
| clang | -O2 | fft | value that could not be identified as reduction is used outside the loop (×3); instruction cannot be vectorized (×2); unspecified (×1) |
| clang | -O2 | dot_product | value that could not be identified as reduction is used outside the loop (×2) |
| clang | -O3 | matrix_mul | value that could not be identified as reduction is used outside the loop (×3) |
| clang | -O3 | fft | value that could not be identified as reduction is used outside the loop (×3); instruction cannot be vectorized (×2); unspecified (×1) |
| clang | -O3 | dot_product | value that could not be identified as reduction is used outside the loop (×2) |

## Run problems

None: every binary ran and every result verified.

## Reading these numbers

- QEMU user-mode timing is emulation time, not silicon time. NEON operations are emulated by helper code, so vectorized code can look slower or faster than it would on a real core. Treat runtime ratios as indicative and rely on the vectorization/NEON columns for what the compilers generated.
- `-O0` runs no vectorizer, so empty reports and zero NEON instructions there are expected. GCC only enables auto-vectorization at `-O2` from version 12; older GCC reports nothing at `-O2`.
- Float reductions (matmul `naive_ijk`, `f32` dot product) are not vectorized without `-ffast-math`, because that would reassociate the sum. Rebuild with `make BUILD=build-fm EXTRA_FLAGS=-ffast-math` to see the difference.
