# AArch64 compiler study: GCC vs Clang

- GCC: `aarch64-linux-gnu-gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`  
- Clang: `Ubuntu clang version 18.1.3 (1ubuntu1)`  
- Execution: `/usr/bin/qemu-aarch64 -cpu max`  
- Host: `Linux x86_64`  
- Generated: 2026-10-17 13:45:19 UTC

## Highlights

- **matrix_mul -O2**: clang/gcc runtime geomean 0.79× (clang faster); NEON insns in kernel code gcc=1 clang=6
- **matrix_mul -O3**: clang/gcc runtime geomean 1.09× (gcc faster); NEON insns in kernel code gcc=24 clang=5
- **fft -O2**: clang/gcc runtime geomean 0.73× (clang faster); NEON insns in kernel code gcc=0 clang=23
- **fft -O3**: clang/gcc runtime geomean 0.86× (clang faster); NEON insns in kernel code gcc=35 clang=22
- **dot_product -O2**: clang/gcc runtime geomean 0.73× (clang faster); NEON insns in kernel code gcc=66 clang=449
- **dot_product -O3**: clang/gcc runtime geomean 0.78× (clang faster); NEON insns in kernel code gcc=123 clang=449

## Vectorization reports and NEON instruction counts

`Vec sites` = distinct source loops reported vectorized (raw messages in parentheses; epilogues and template instantiations add messages). `Missed` = loops reported not vectorized that were never vectorized. `NEON (kernel)` counts Advanced SIMD instructions inside the `kern_*` functions only.

### matrix_mul

| Compiler | Opt | Vec sites (msgs) | Missed | NEON / kernel insns | NEON % | Vector widths | Top NEON ops |
|---|---|---|---|---|---|---|---|
| gcc | -O0 | 0 (0) | 0 | 0 / 163 | 0.0% | — | — |
| gcc | -O2 | 0 (0) | 13 | 1 / 83 | 1.2% | — | movi×1 |
| gcc | -O3 | 4 (6) | 10 | 24 / 266 | 9.0% | 128-bit×5, 64-bit×1 | ldr.q×6, fmla×6, dup×3 |
| clang | -O0 | 0 (0) | 0 | 0 / 161 | 0.0% | — | — |
| clang | -O2 | 2 (2) | 2 | 6 / 133 | 4.5% | VF4/IC2×2 | ldp.q×2, fmla×2, dup×1 |
| clang | -O3 | 2 (2) | 3 | 5 / 132 | 3.8% | VF4/IC2×2 | ldp.q×2, fmla×2, stp.q×1 |

### fft

| Compiler | Opt | Vec sites (msgs) | Missed | NEON / kernel insns | NEON % | Vector widths | Top NEON ops |
|---|---|---|---|---|---|---|---|
| gcc | -O0 | 0 (0) | 0 | 0 / 215 | 0.0% | — | — |
| gcc | -O2 | 0 (0) | 14 | 0 / 68 | 0.0% | — | — |
| gcc | -O3 | 3 (4) | 11 | 35 / 226 | 15.5% | 128-bit×3, 64-bit×1 | ins×8, ldr.q×6, fmla×6 |
| clang | -O0 | 0 (0) | 0 | 0 / 178 | 0.0% | — | — |
| clang | -O2 | 5 (5) | 5 | 23 / 164 | 14.0% | VF4/IC1×3, VF4/IC2×2 | ld1×6, ldr.q×4, str.q×4 |
| clang | -O3 | 5 (5) | 5 | 22 / 163 | 13.5% | VF4/IC1×3, VF4/IC2×2 | ld1×6, ldr.q×4, str.q×4 |

### dot_product

| Compiler | Opt | Vec sites (msgs) | Missed | NEON / kernel insns | NEON % | Vector widths | Top NEON ops |
|---|---|---|---|---|---|---|---|
| gcc | -O0 | 0 (0) | 0 | 0 / 942 | 0.0% | — | — |
| gcc | -O2 | 3 (6) | 8 | 66 / 300 | 22.0% | 128-bit×6 | dup×21, ldr.q×16, movi×11 |
| gcc | -O3 | 9 (18) | 2 | 123 / 652 | 18.9% | 128-bit×18 | ldr.q×36, movi×23, dup×21 |
| clang | -O0 | 0 (0) | 0 | 0 / 840 | 0.0% | — | — |
| clang | -O2 | 9 (17) | 2 | 449 / 964 | 46.6% | VF2/IC2×1, VF4/IC2×16 | movi×81, mov×68, ldp.q×47 |
| clang | -O3 | 9 (17) | 2 | 449 / 964 | 46.6% | VF2/IC2×1, VF4/IC2×16 | movi×81, mov×68, ldp.q×47 |

## Runtime (ms, best of reps, lower is better)

A trailing `!` marks a result that failed self-verification. `clang/gcc` < 1 means Clang's binary ran faster.

### matrix_mul

| Variant | gcc -O0 | gcc -O2 | gcc -O3 | clang -O0 | clang -O2 | clang -O3 | clang/gcc O2 | clang/gcc O3 |
|---|---|---|---|---|---|---|---|---|
| naive_ijk | 257.72 | 136.70 | 109.42 | 268.44 | 126.20 | 127.82 | 0.92 | 1.17 |
| reordered_ikj | 285.40 | 150.04 | 100.26 | 278.24 | 101.62 | 102.19 | 0.68 | 1.02 |

### fft

| Variant | gcc -O0 | gcc -O2 | gcc -O3 | clang -O0 | clang -O2 | clang -O3 | clang/gcc O2 | clang/gcc O3 |
|---|---|---|---|---|---|---|---|---|
| radix2_iterative | 35.27 | 23.56 | 21.49 | 34.74 | 17.24 | 18.43 | 0.73 | 0.86 |

### dot_product

| Variant | gcc -O0 | gcc -O2 | gcc -O3 | clang -O0 | clang -O2 | clang -O3 | clang/gcc O2 | clang/gcc O3 |
|---|---|---|---|---|---|---|---|---|
| f32_basic | 12.57 | 8.08 | 5.71 | 13.79 | 5.79 | 5.96 | 0.72 | 1.04 |
| f32_restrict | 15.24 | 8.11 | 5.94 | 13.07 | 5.77 | 5.81 | 0.71 | 0.98 |
| f32_unroll4 | 10.72 | 5.93 | 5.75 | 11.39 | 6.14 | 5.93 | 1.03 | 1.03 |
| f32_restrict_unroll4 | 10.94 | 5.76 | 5.75 | 11.23 | 6.26 | 6.31 | 1.09 | 1.10 |
| f32_restrict_unroll8 | 9.83 | 6.05 | 5.75 | 10.52 | 6.71 | 6.76 | 1.11 | 1.18 |
| i32_basic | 6.65 | 2.91 | 2.95 | 7.59 | 1.62 | 1.60 | 0.56 | 0.54 |
| i32_restrict | 6.69 | 2.88 | 2.92 | 7.55 | 1.60 | 1.63 | 0.56 | 0.56 |
| i32_unroll4 | 8.18 | 2.78 | 2.80 | 4.57 | 1.22 | 1.21 | 0.44 | 0.43 |
| i32_restrict_unroll4 | 4.59 | 2.80 | 2.80 | 4.53 | 1.22 | 1.21 | 0.43 | 0.43 |
| i32_restrict_unroll8 | 4.52 | 1.57 | 1.57 | 4.27 | 1.68 | 1.63 | 1.07 | 1.04 |

## Most common missed-vectorization reasons

| Compiler | Opt | Kernel | Top reasons |
|---|---|---|---|
| gcc | -O2 | matrix_mul | multiple nested loops (×3); unsupported use in stmt (×2); not suitable for strided load _10 = *_9; (×1) |
| gcc | -O2 | fft | relevant stmt not supported (×5); control flow in loop (×2); unsupported use in stmt (×2) |
| gcc | -O2 | dot_product | relevant stmt not supported (×2); unsupported use in stmt (×1) |
| gcc | -O3 | matrix_mul | multiple nested loops (×2); complicated access pattern (×2); unsupported use in stmt (×2) |
| gcc | -O3 | fft | relevant stmt not supported (×3); number of iterations cannot be computed (×2); unsupported use in stmt (×2) |
| gcc | -O3 | dot_product | unsupported use in stmt (×1) |
| clang | -O2 | matrix_mul | value that could not be identified as reduction is used outside the loop (×2) |
| clang | -O2 | fft | value that could not be identified as reduction is used outside the loop (×2); could not determine number of loop iterations (×1); instruction cannot be vectorized (×1) |
| clang | -O2 | dot_product | value that could not be identified as reduction is used outside the loop (×1); instruction cannot be vectorized (×1) |
| clang | -O3 | matrix_mul | value that could not be identified as reduction is used outside the loop (×2); instruction cannot be vectorized (×1) |
| clang | -O3 | fft | value that could not be identified as reduction is used outside the loop (×2); could not determine number of loop iterations (×1); instruction cannot be vectorized (×1) |
| clang | -O3 | dot_product | value that could not be identified as reduction is used outside the loop (×1); instruction cannot be vectorized (×1) |

## Run problems

None: every binary ran and every result verified.

## Reading these numbers

- QEMU user-mode timing is emulation time, not silicon time. NEON operations are emulated by helper code, so vectorized code can look slower or faster than it would on a real core. Treat runtime ratios as indicative and rely on the vectorization/NEON columns for what the compilers generated.
- `-O0` runs no vectorizer, so empty reports and zero NEON instructions there are expected. GCC only enables auto-vectorization at `-O2` from version 12; older GCC reports nothing at `-O2`.
- Float reductions (matmul `naive_ijk`, `f32` dot product) are not vectorized without `-ffast-math`, because that would reassociate the sum. Rebuild with `make BUILD=build-fm EXTRA_FLAGS=-ffast-math` to see the difference.
