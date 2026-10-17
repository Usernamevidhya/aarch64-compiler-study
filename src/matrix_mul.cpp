// Matrix multiplication: naive (ijk) vs loop-reordered (ikj).
//
// C = A * B for row-major float n x n matrices.
//
//  * naive_ijk     : the textbook triple loop. The inner loop walks B with
//                    stride n (cache-hostile, and a strided gather is not
//                    vectorizable) and carries a float reduction, which
//                    neither GCC nor Clang will reassociate without -ffast-math.
//  * reordered_ikj : the k and j loops are swapped. The inner loop is now a
//                    unit-stride axpy, C[i][:] += A[i][k] * B[k][:], with no
//                    loop-carried dependency: ideal for NEON auto-vectorization
//                    and far friendlier to the cache.
//
// Usage: matrix_mul [n=256] [reps=3]
#include "bench_common.h"

#include <math.h>

KERNEL_NOINLINE void kern_matmul_naive(const float* __restrict__ A, const float* __restrict__ B,
                                       float* __restrict__ C, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = 0; j < n; ++j) {
            float acc = 0.0f;
            for (size_t k = 0; k < n; ++k) {
                acc += A[i * n + k] * B[k * n + j];
            }
            C[i * n + j] = acc;
        }
    }
}

KERNEL_NOINLINE void kern_matmul_reordered(const float* __restrict__ A, const float* __restrict__ B,
                                           float* __restrict__ C, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = 0; j < n; ++j) {
            C[i * n + j] = 0.0f;
        }
        for (size_t k = 0; k < n; ++k) {
            const float a = A[i * n + k];
            for (size_t j = 0; j < n; ++j) {
                C[i * n + j] += a * B[k * n + j];
            }
        }
    }
}

typedef void (*MatmulFn)(const float*, const float*, float*, size_t);

// Max absolute error against a double-precision reference on a 16x16 sample
// grid of C (a full reference would be O(n^3) in double).
static double max_sampled_error(const float* A, const float* B, const float* C, size_t n) {
    double worst = 0.0;
    const size_t stride = n > 16 ? n / 16 : 1;
    for (size_t i = 0; i < n; i += stride) {
        for (size_t j = 0; j < n; j += stride) {
            double ref = 0.0;
            for (size_t k = 0; k < n; ++k) {
                ref += static_cast<double>(A[i * n + k]) * static_cast<double>(B[k * n + j]);
            }
            const double e = fabs(ref - static_cast<double>(C[i * n + j]));
            if (e > worst) worst = e;
        }
    }
    return worst;
}

static bool bench_variant(const char* name, MatmulFn fn, const float* A, const float* B, float* C,
                          size_t n, int reps) {
    double best = 1e300;
    for (int r = 0; r < reps; ++r) {
        for (size_t i = 0; i < n * n; ++i) C[i] = 1.0f;  // poison: kernel must overwrite
        compiler_barrier();
        const double t0 = now_ms();
        fn(A, B, C, n);
        compiler_barrier();
        const double t1 = now_ms();
        if (t1 - t0 < best) best = t1 - t0;
    }
    const double err = max_sampled_error(A, B, C, n);
    const bool ok = err <= 1e-3;
    report("matrix_mul", name, static_cast<unsigned long>(n), reps, best, err, ok);
    return ok;
}

int main(int argc, char** argv) {
    const size_t n = arg_or_default(argc, argv, 1, 256);
    const int reps = static_cast<int>(arg_or_default(argc, argv, 2, 3));

    float* A = alloc_array<float>(n * n);
    float* B = alloc_array<float>(n * n);
    float* C = alloc_array<float>(n * n);

    uint32_t seed = 12345u;
    for (size_t i = 0; i < n * n; ++i) A[i] = rand_unit(seed);
    for (size_t i = 0; i < n * n; ++i) B[i] = rand_unit(seed);

    bool ok = true;
    ok &= bench_variant("naive_ijk", kern_matmul_naive, A, B, C, n, reps);
    ok &= bench_variant("reordered_ikj", kern_matmul_reordered, A, B, C, n, reps);

    free(A);
    free(B);
    free(C);
    return ok ? 0 : 1;
}
