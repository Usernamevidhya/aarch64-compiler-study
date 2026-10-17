// Dot product kernels: aliasing (restrict) and unrolling variants, for float
// and int32.
//
//  basic             : plain loop, a and b may alias.
//  restrict          : same loop, pointers qualified __restrict__.
//  unroll4           : 4 independent accumulators, no restrict.
//  restrict_unroll4  : 4 independent accumulators + restrict.
//  restrict_unroll8  : 8 independent accumulators + restrict.
//
// Why both element types? A float sum is a strictly ordered reduction, so
// without -ffast-math the compilers may not reassociate it into vector lanes;
// the manual multi-accumulator variants hand them that reassociation. An int32
// sum is associative, so the compilers can vectorize the rolled loop on their
// own. Comparing the two shows what each optimisation actually buys.
//
// Usage: dot_product [n=1048576] [reps=10]
#include "bench_common.h"

#include <math.h>

template <typename T>
KERNEL_NOINLINE T kern_dot_basic(const T* a, const T* b, size_t n) {
    T s = 0;
    for (size_t i = 0; i < n; ++i) s += a[i] * b[i];
    return s;
}

template <typename T>
KERNEL_NOINLINE T kern_dot_restrict(const T* __restrict__ a, const T* __restrict__ b, size_t n) {
    T s = 0;
    for (size_t i = 0; i < n; ++i) s += a[i] * b[i];
    return s;
}

template <typename T>
KERNEL_NOINLINE T kern_dot_unroll4(const T* a, const T* b, size_t n) {
    T s0 = 0, s1 = 0, s2 = 0, s3 = 0;
    size_t i = 0;
    for (; i + 4 <= n; i += 4) {
        s0 += a[i + 0] * b[i + 0];
        s1 += a[i + 1] * b[i + 1];
        s2 += a[i + 2] * b[i + 2];
        s3 += a[i + 3] * b[i + 3];
    }
    for (; i < n; ++i) s0 += a[i] * b[i];
    return (s0 + s1) + (s2 + s3);
}

template <typename T>
KERNEL_NOINLINE T kern_dot_restrict_unroll4(const T* __restrict__ a, const T* __restrict__ b,
                                            size_t n) {
    T s0 = 0, s1 = 0, s2 = 0, s3 = 0;
    size_t i = 0;
    for (; i + 4 <= n; i += 4) {
        s0 += a[i + 0] * b[i + 0];
        s1 += a[i + 1] * b[i + 1];
        s2 += a[i + 2] * b[i + 2];
        s3 += a[i + 3] * b[i + 3];
    }
    for (; i < n; ++i) s0 += a[i] * b[i];
    return (s0 + s1) + (s2 + s3);
}

template <typename T>
KERNEL_NOINLINE T kern_dot_restrict_unroll8(const T* __restrict__ a, const T* __restrict__ b,
                                            size_t n) {
    T s0 = 0, s1 = 0, s2 = 0, s3 = 0, s4 = 0, s5 = 0, s6 = 0, s7 = 0;
    size_t i = 0;
    for (; i + 8 <= n; i += 8) {
        s0 += a[i + 0] * b[i + 0];
        s1 += a[i + 1] * b[i + 1];
        s2 += a[i + 2] * b[i + 2];
        s3 += a[i + 3] * b[i + 3];
        s4 += a[i + 4] * b[i + 4];
        s5 += a[i + 5] * b[i + 5];
        s6 += a[i + 6] * b[i + 6];
        s7 += a[i + 7] * b[i + 7];
    }
    for (; i < n; ++i) s0 += a[i] * b[i];
    return ((s0 + s1) + (s2 + s3)) + ((s4 + s5) + (s6 + s7));
}

// Float results are compared to a double reference, normalised by sum|a_i*b_i|
// (so a near-zero dot product cannot inflate the relative error). Integer
// results must match exactly.
static bool within_tolerance(float got, double ref, double scale, double* err) {
    *err = fabs(static_cast<double>(got) - ref) / scale;
    return *err <= 1e-4;
}
static bool within_tolerance(int32_t got, double ref, double /*scale*/, double* err) {
    *err = fabs(static_cast<double>(got) - ref);
    return *err == 0.0;
}

template <typename T>
static void reference(const T* a, const T* b, size_t n, double* ref, double* sum_abs) {
    double s = 0.0, sa = 0.0;
    for (size_t i = 0; i < n; ++i) {
        const double p = static_cast<double>(a[i]) * static_cast<double>(b[i]);
        s += p;
        sa += fabs(p);
    }
    *ref = s;
    *sum_abs = sa > 0.0 ? sa : 1.0;
}

template <typename T>
static bool bench_dot(const char* type_name, const char* variant, T (*fn)(const T*, const T*, size_t),
                      const T* a, const T* b, size_t n, int reps, double ref, double scale) {
    double best = 1e300;
    T result = 0;
    for (int r = 0; r < reps; ++r) {
        compiler_barrier();
        const double t0 = now_ms();
        result = fn(a, b, n);
        compiler_barrier();
        const double t1 = now_ms();
        if (t1 - t0 < best) best = t1 - t0;
    }
    double err = 0.0;
    const bool ok = within_tolerance(result, ref, scale, &err);
    char name[64];
    snprintf(name, sizeof name, "%s_%s", type_name, variant);
    report("dot_product", name, static_cast<unsigned long>(n), reps, best, err, ok);
    return ok;
}

template <typename T>
static bool bench_all(const char* type_name, const T* a, const T* b, size_t n, int reps) {
    double ref = 0.0, scale = 1.0;
    reference<T>(a, b, n, &ref, &scale);
    bool ok = true;
    ok &= bench_dot<T>(type_name, "basic", kern_dot_basic<T>, a, b, n, reps, ref, scale);
    ok &= bench_dot<T>(type_name, "restrict", kern_dot_restrict<T>, a, b, n, reps, ref, scale);
    ok &= bench_dot<T>(type_name, "unroll4", kern_dot_unroll4<T>, a, b, n, reps, ref, scale);
    ok &= bench_dot<T>(type_name, "restrict_unroll4", kern_dot_restrict_unroll4<T>, a, b, n, reps,
                       ref, scale);
    ok &= bench_dot<T>(type_name, "restrict_unroll8", kern_dot_restrict_unroll8<T>, a, b, n, reps,
                       ref, scale);
    return ok;
}

int main(int argc, char** argv) {
    const size_t n = arg_or_default(argc, argv, 1, 1u << 20);
    const int reps = static_cast<int>(arg_or_default(argc, argv, 2, 10));

    float* fa = alloc_array<float>(n);
    float* fb = alloc_array<float>(n);
    int32_t* ia = alloc_array<int32_t>(n);
    int32_t* ib = alloc_array<int32_t>(n);

    uint32_t seed = 2024u;
    for (size_t i = 0; i < n; ++i) {
        fa[i] = rand_unit(seed);
        fb[i] = rand_unit(seed);
        // 0..15: products <= 225, so even 2^24 elements stay inside int32.
        ia[i] = static_cast<int32_t>((lcg_next(seed) >> 16) & 15u);
        ib[i] = static_cast<int32_t>((lcg_next(seed) >> 16) & 15u);
    }

    bool ok = true;
    ok &= bench_all<float>("f32", fa, fb, n, reps);
    ok &= bench_all<int32_t>("i32", ia, ib, n, reps);

    free(fa);
    free(fb);
    free(ia);
    free(ib);
    return ok ? 0 : 1;
}
