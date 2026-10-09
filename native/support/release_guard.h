/* SPDX-License-Identifier: MIT
 * Caller-owned bookkeeping for reentrant reference-counted object destruction.
 * Does not touch the observed object or change its reference count.
 */
#ifndef NATIVE_RELEASE_GUARD_V1_H
#define NATIVE_RELEASE_GUARD_V1_H

typedef struct {
    unsigned in_flight, terminal_seen, unknown, entered, completed, peak;
} NRGState;

static unsigned nrg_load(const unsigned *p) {
    return __atomic_load_n(p, __ATOMIC_SEQ_CST);
}
static void nrg_unknown(NRGState *g, unsigned bit) {
    __atomic_fetch_or(&g->unknown, bit, __ATOMIC_SEQ_CST);
}
static void nrg_init(NRGState *g) {
    /* Only initialize before publication of a new observed object generation. */
    g->in_flight = g->terminal_seen = g->unknown = 0;
    g->entered = g->completed = g->peak = 0;
}
static unsigned nrg_enter(NRGState *g) {
    unsigned n = nrg_load(&g->in_flight);
    for (;;) {
        if (n >= 64 || nrg_load(&g->entered) >= 0x7ffff000u) {
            nrg_unknown(g, 1); return 0;
        }
        if (__atomic_compare_exchange_n(&g->in_flight, &n, n+1, 0,
                                        __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) break;
    }
    __atomic_add_fetch(&g->entered, 1, __ATOMIC_SEQ_CST);
    unsigned peak = nrg_load(&g->peak);
    while (peak < n+1 && !__atomic_compare_exchange_n(&g->peak, &peak, n+1, 0,
                                                     __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) {}
    return 1;
}
static unsigned nrg_leave(NRGState *g, unsigned original_return) {
    if (!original_return) __atomic_store_n(&g->terminal_seen, 1, __ATOMIC_SEQ_CST);
    unsigned n = nrg_load(&g->in_flight);
    for (;;) {
        if (!n) { nrg_unknown(g, 2); return 0; }
        if (__atomic_compare_exchange_n(&g->in_flight, &n, n-1, 0,
                                        __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) break;
    }
    __atomic_add_fetch(&g->completed, 1, __ATOMIC_SEQ_CST);
    if (original_return && nrg_load(&g->terminal_seen)) nrg_unknown(g, 4);
    return n == 1 && nrg_load(&g->terminal_seen);
}
static unsigned nrg_quiet_live(const NRGState *g) {
    return !nrg_load(&g->in_flight) && !nrg_load(&g->terminal_seen) &&
           !nrg_load(&g->unknown) && nrg_load(&g->entered) == nrg_load(&g->completed);
}
#endif
