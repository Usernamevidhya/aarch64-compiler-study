// Iterative radix-2 decimation-in-time FFT (in place, split re/im arrays).
//
// Structure of kern_fft_radix2:
//   1. bit-reversal permutation (data-dependent swaps, not vectorizable)
//   2. log2(n) butterfly stages. The twiddle table is read with stride n/len,
//      so early stages (small len) have short inner loops and strided loads,
//      while late stages have long unit-stride butterfly loops that are the
//      vectorization candidates. Both compilers' reports are interesting here.
//
// Correctness is checked two ways: against a double-precision O(n^2) DFT on a
// small size, and via Parseval's theorem on the benchmarked size.
//
// Usage: fft [n=65536 (power of two)] [reps=10]
#include "bench_common.h"

#include <math.h>

struct FftPlan {
    size_t n;
    uint32_t* rev;  // bit-reversal permutation
    float* wr;      // cos(-2*pi*k/n), k in [0, n/2)
    float* wi;      // sin(-2*pi*k/n)
};

static FftPlan make_plan(size_t n) {
    FftPlan p;
    p.n = n;
    p.rev = alloc_array<uint32_t>(n);
    p.wr = alloc_array<float>(n / 2);
    p.wi = alloc_array<float>(n / 2);

    unsigned bits = 0;
    while ((static_cast<size_t>(1) << bits) < n) ++bits;
    for (size_t i = 0; i < n; ++i) {
        uint32_t r = 0;
        for (unsigned b = 0; b < bits; ++b) {
            if (i & (static_cast<size_t>(1) << b)) r |= 1u << (bits - 1 - b);
        }
        p.rev[i] = r;
    }

    const double two_pi = 6.283185307179586476925286766559;
    for (size_t k = 0; k < n / 2; ++k) {
        const double a = -two_pi * static_cast<double>(k) / static_cast<double>(n);
        p.wr[k] = static_cast<float>(cos(a));
        p.wi[k] = static_cast<float>(sin(a));
    }
    return p;
}

static void free_plan(FftPlan& p) {
    free(p.rev);
    free(p.wr);
    free(p.wi);
}

KERNEL_NOINLINE void kern_fft_radix2(float* __restrict__ re, float* __restrict__ im,
                                     const float* __restrict__ wr, const float* __restrict__ wi,
                                     const uint32_t* __restrict__ rev, size_t n) {
    // Bit-reversal permutation.
    for (size_t i = 0; i < n; ++i) {
        const size_t j = rev[i];
        if (j > i) {
            const float tr = re[i];
            const float ti = im[i];
            re[i] = re[j];
            im[i] = im[j];
            re[j] = tr;
            im[j] = ti;
        }
    }

    // Butterfly stages.
    for (size_t len = 2; len <= n; len <<= 1) {
        const size_t half = len >> 1;
        const size_t step = n / len;
        for (size_t base = 0; base < n; base += len) {
            for (size_t k = 0; k < half; ++k) {
                const float c = wr[k * step];
                const float s = wi[k * step];
                const size_t a = base + k;
                const size_t b = a + half;
                const float tr = re[b] * c - im[b] * s;
                const float ti = re[b] * s + im[b] * c;
                re[b] = re[a] - tr;
                im[b] = im[a] - ti;
                re[a] += tr;
                im[a] += ti;
            }
        }
    }
}

// Max |FFT - DFT| over all bins, with the DFT evaluated in double precision.
static double dft_check_error(size_t n) {
    FftPlan plan = make_plan(n);
    float* re = alloc_array<float>(n);
    float* im = alloc_array<float>(n);
    float* re0 = alloc_array<float>(n);
    float* im0 = alloc_array<float>(n);

    uint32_t seed = 777u;
    for (size_t i = 0; i < n; ++i) {
        re0[i] = re[i] = rand_unit(seed);
        im0[i] = im[i] = rand_unit(seed);
    }
    kern_fft_radix2(re, im, plan.wr, plan.wi, plan.rev, n);

    const double two_pi = 6.283185307179586476925286766559;
    double worst = 0.0;
    for (size_t k = 0; k < n; ++k) {
        double sr = 0.0, si = 0.0;
        for (size_t t = 0; t < n; ++t) {
            const double a = -two_pi * static_cast<double>((k * t) % n) / static_cast<double>(n);
            const double c = cos(a), s = sin(a);
            sr += re0[t] * c - im0[t] * s;
            si += re0[t] * s + im0[t] * c;
        }
        const double e = fmax(fabs(sr - re[k]), fabs(si - im[k]));
        if (e > worst) worst = e;
    }

    free_plan(plan);
    free(re);
    free(im);
    free(re0);
    free(im0);
    return worst;
}

int main(int argc, char** argv) {
    const size_t n = arg_or_default(argc, argv, 1, 65536);
    const int reps = static_cast<int>(arg_or_default(argc, argv, 2, 10));
    if (n < 2 || (n & (n - 1)) != 0) {
        fprintf(stderr, "fft: n must be a power of two >= 2 (got %zu)\n", n);
        return 2;
    }

    const double dft_err = dft_check_error(256);

    FftPlan plan = make_plan(n);
    float* re = alloc_array<float>(n);
    float* im = alloc_array<float>(n);
    float* re0 = alloc_array<float>(n);
    float* im0 = alloc_array<float>(n);

    uint32_t seed = 4242u;
    double energy_in = 0.0;
    for (size_t i = 0; i < n; ++i) {
        re0[i] = rand_unit(seed);
        im0[i] = rand_unit(seed);
        energy_in += static_cast<double>(re0[i]) * re0[i] + static_cast<double>(im0[i]) * im0[i];
    }

    double best = 1e300;
    for (int r = 0; r < reps; ++r) {
        memcpy(re, re0, n * sizeof(float));
        memcpy(im, im0, n * sizeof(float));
        compiler_barrier();
        const double t0 = now_ms();
        kern_fft_radix2(re, im, plan.wr, plan.wi, plan.rev, n);
        compiler_barrier();
        const double t1 = now_ms();
        if (t1 - t0 < best) best = t1 - t0;
    }

    // Parseval: sum |X|^2 == n * sum |x|^2
    double energy_out = 0.0;
    for (size_t i = 0; i < n; ++i) {
        energy_out += static_cast<double>(re[i]) * re[i] + static_cast<double>(im[i]) * im[i];
    }
    const double parseval_err = fabs(energy_out / (static_cast<double>(n) * energy_in) - 1.0);

    const double err = fmax(dft_err, parseval_err);
    const bool ok = dft_err <= 1e-3 && parseval_err <= 1e-3;
    report("fft", "radix2_iterative", static_cast<unsigned long>(n), reps, best, err, ok);

    free_plan(plan);
    free(re);
    free(im);
    free(re0);
    free(im0);
    return ok ? 0 : 1;
}
