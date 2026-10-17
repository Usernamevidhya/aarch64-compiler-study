# AArch64 compiler optimisation study: GCC vs Clang cross-compilation
#
# For every (compiler, -O level, kernel) this produces, under $(BUILD)/<cc>/<opt>/:
#   <kernel>.s              raw AArch64 assembly (the program that actually gets linked)
#   <kernel>.vec.txt        vectorization report
#                             gcc  : -fopt-info-vec-all (vectorized + missed, one file:
#                                    GCC accepts only one -fopt-info output file)
#                             clang: -Rpass=loop-vectorize -Rpass-missed=loop-vectorize
#                                    plus -Rpass-analysis=loop-vectorize (the reasons)
#   <kernel>.elf            static AArch64 executable (runs under qemu-aarch64)
#
# The .s file is generated once, with the reports, and the binary is linked from
# that very file, so assembly, report and binary can never disagree.
#
# Usage:
#   make                 build everything (both compilers, O0/O2/O3, all kernels)
#   make gcc | make clang
#   make run             build, then run scripts/analyze_and_run.py
#   make check-tools     show which cross tools are installed
#   make V=1             echo full command lines
#   make BUILD=build-fm EXTRA_FLAGS=-ffast-math    experiment with extra flags
#
# Toolchain overrides (all `?=`, so they can come from the environment):
#   GCC_CC CLANG_CC QEMU PYTHON TRIPLE SYSROOT ARCH GCC_LINK CLANG_LINK

SHELL := /bin/bash

# ---- toolchain ---------------------------------------------------------------
GCC_CC       ?= aarch64-linux-gnu-gcc
CLANG_CC     ?= clang
QEMU         ?= qemu-aarch64
PYTHON       ?= python3

TRIPLE       ?= aarch64-linux-gnu
SYSROOT      ?= /usr/aarch64-linux-gnu
ARCH         ?= armv8-a
CLANG_TARGET ?= --target=$(TRIPLE) --sysroot=$(SYSROOT)

# -fno-addrsig (clang): keeps .addrsig directives out of the .s so GNU as can
# assemble it too.
# Linkers. Sources use only the C library, so the C drivers link them (no
# libstdc++ needed). Clang's .s is linked with the GNU cross driver by default:
# with `clang --sysroot=...` the glibc linker scripts (libm.a etc.) contain
# absolute paths that ld re-prefixes with the sysroot, so the link fails on
# Debian/Ubuntu. Compilation and the vectorization reports are still pure clang.
# To try a pure-clang link:  make CLANG_LINK='clang --target=aarch64-linux-gnu --sysroot=/' ...
GCC_LINK     ?= $(GCC_CC)
CLANG_LINK   ?= $(GCC_CC)

# ---- project layout ----------------------------------------------------------
KERNELS    := matrix_mul fft dot_product
OPTS       := O0 O2 O3
COMPILERS  := gcc clang
BUILD      ?= build
RESULTS    ?= results
HDRS       := src/bench_common.h
EXTRA_FLAGS ?=
RUN_ARGS   ?=

# -g0 keeps the assembly free of .loc/.debug noise; remarks and opt-info still
# carry source line numbers. -fno-exceptions/-fno-rtti: no C++ runtime needed.
CXXFLAGS_COMMON := -std=c++17 -Wall -Wextra -g0 -fno-exceptions -fno-rtti -Isrc -march=$(ARCH)

Q := $(if $(V),,@)

ALL_ASM := $(foreach c,$(COMPILERS),$(foreach o,$(OPTS),$(foreach k,$(KERNELS),$(BUILD)/$(c)/$(o)/$(k).s)))
ALL_ELF := $(ALL_ASM:.s=.elf)

.PHONY: all asm gcc clang run report check-tools clean distclean help
.SECONDARY:

all: $(ALL_ASM) $(ALL_ELF)

asm: $(ALL_ASM)

gcc: $(filter $(BUILD)/gcc/%,$(ALL_ELF))

clang: $(filter $(BUILD)/clang/%,$(ALL_ELF))

# ---- GCC rules (one set per -O level) ---------------------------------------
define GCC_RULES
$(BUILD)/gcc/$(1)/%.s: src/%.cpp $(HDRS) Makefile
	@mkdir -p $$(@D)
	@echo "  GCC     -$(1)  $$<"
	$$(Q)$$(GCC_CC) -x c++ $$(CXXFLAGS_COMMON) -$(1) -S $$< -o $$@ \
	    -fopt-info-vec-all=$$(@D)/$$*.vec.txt \
	    $$(EXTRA_FLAGS)

$(BUILD)/gcc/$(1)/%.elf: $(BUILD)/gcc/$(1)/%.s
	@echo "  LINK    gcc -$(1)  $$@"
	$$(Q)$$(GCC_LINK) $$< -o $$@ -static -lm
endef

# ---- Clang rules --------------------------------------------------------------
# Remarks go to stderr; capture them in the .vec.txt file (and show them if the
# compile itself fails).
define CLANG_RULES
$(BUILD)/clang/$(1)/%.s: src/%.cpp $(HDRS) Makefile
	@mkdir -p $$(@D)
	@echo "  CLANG   -$(1)  $$<"
	$$(Q)$$(CLANG_CC) $$(CLANG_TARGET) -x c++ $$(CXXFLAGS_COMMON) -$(1) -S $$< -o $$@ \
	    -Rpass=loop-vectorize -Rpass-missed=loop-vectorize -Rpass-analysis=loop-vectorize \
	    -fno-caret-diagnostics -fno-addrsig \
	    $$(EXTRA_FLAGS) 2> $$(@D)/$$*.vec.txt \
	    || { cat $$(@D)/$$*.vec.txt >&2; exit 1; }

$(BUILD)/clang/$(1)/%.elf: $(BUILD)/clang/$(1)/%.s
	@echo "  LINK    clang -$(1)  $$@"
	$$(Q)$$(CLANG_LINK) $$< -o $$@ -static -lm
endef

$(foreach o,$(OPTS),$(eval $(call GCC_RULES,$(o))))
$(foreach o,$(OPTS),$(eval $(call CLANG_RULES,$(o))))

# ---- run / report -------------------------------------------------------------
run report: all
	$(PYTHON) scripts/analyze_and_run.py --build-dir $(BUILD) --out $(RESULTS) --qemu $(QEMU) $(RUN_ARGS)

check-tools:
	@for t in $(GCC_CC) $(CLANG_CC) $(QEMU) $(PYTHON) git; do \
	  if command -v $$t >/dev/null 2>&1; then printf "  ok       %s\n" "$$t"; \
	  else printf "  MISSING  %s\n" "$$t"; fi; \
	done
	@echo
	@echo "Debian/Ubuntu: sudo apt install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu \\"
	@echo "                   libc6-dev-arm64-cross clang lld qemu-user python3"

clean:
	rm -rf $(BUILD)

distclean: clean
	rm -rf $(RESULTS) scripts/__pycache__

help:
	@sed -n '1,/^SHELL/p' Makefile | sed -e '$$d' -e 's/^# \{0,1\}//'
