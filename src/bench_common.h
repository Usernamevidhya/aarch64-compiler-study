// Shared helpers for the AArch64 compiler study kernels.
//
// Deliberately uses only C library headers (no <iostream>, no libstdc++
// runtime) so every kernel can be compiled and statically linked with a plain
// cross C driver (aarch64-linux-gnu-gcc / clang) and run under qemu-aarch64.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

// Kernels must stay out-of-line so (a) the assembly of each kernel is easy to
// find (symbols contain "kern_") and (b) the optimiser cannot fold them into
// the timing harness.
#define KERNEL_NOINLINE [[gnu::noinline]]

// Opaque to the optimiser: stops loop-invariant hoisting of "pure" kernels out
// of the timing loops.
static inline void compiler_barrier() { __asm__ __volatile__("" ::: "memory"); }

static inline double now_ms() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<double>(ts.tv_sec) * 1e3 + static_cast<double>(ts.tv_nsec) / 1e6;
}

// Small deterministic LCG so every build sees identical input data.
static inline uint32_t lcg_next(uint32_t& state) {
    state = state * 1664525u + 1013904223u;
    return state;
}

// Uniform float in [-0.5, 0.5).
static inline float rand_unit(uint32_t& state) {
    return static_cast<float>(lcg_next(state) >> 8) * (1.0f / 16777216.0f) - 0.5f;
}

template <typename T>
static inline T* alloc_array(size_t count) {
    size_t bytes = (count * sizeof(T) + 63u) & ~static_cast<size_t>(63u);
    if (bytes == 0) bytes = 64;
    void* p = aligned_alloc(64, bytes);
    if (!p) {
        fprintf(stderr, "allocation of %zu bytes failed\n", bytes);
        exit(2);
    }
    return static_cast<T*>(p);
}

// argv[idx] as a positive integer, or `def` when absent/invalid.
static inline size_t arg_or_default(int argc, char** argv, int idx, size_t def) {
    if (argc > idx) {
        char* end = nullptr;
        unsigned long v = strtoul(argv[idx], &end, 10);
        if (end != argv[idx] && v > 0) return static_cast<size_t>(v);
    }
    return def;
}

// One machine-parsable line per benchmarked variant. scripts/analyze_and_run.py
// parses exactly this format.
//   err    : kernel-specific error against a double-precision reference
//   status : OK when err is inside the kernel's tolerance, FAIL otherwise
static inline void report(const char* kernel, const char* variant, unsigned long n, int reps,
                          double best_ms, double err, bool ok) {
    printf("RESULT kernel=%s variant=%s n=%lu reps=%d time_ms=%.4f err=%.3e status=%s\n", kernel,
           variant, n, reps, best_ms, err, ok ? "OK" : "FAIL");
    fflush(stdout);
}
