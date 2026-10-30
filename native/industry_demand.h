// One industry-demand history for the two game states of a world (0.6): the decisions of mpfever_native.cpp's scheduler
// detour (see "one industry-demand history" there), kept apart so that tests/test_industrydemand.py builds them with a
// stand-in for the game's memory. Ported from TPF3-MP (MIT; crates/tpf3mp-hook/src/industry_shared.rs).
//
// The engine runs each batch of steps on one of its two game states, the other one by turns. The industries' demand
// scheduler is a lambda made once per game state, each with its own IndustryChainSpawnState held by a std::shared_ptr: the
// lambda's captures are six words { system, game state, job queue, resources, history, history's control block }. Every
// active call (the game state's engine flag at +0x1f8 is 1) is given one history for the world: the one of the first active
// call after the world was made, kept by one more reference until the next world. A call of the other state (flag 0, as when
// the world is copied into it) returns at once in the game's own code and is left alone.
//
// Before including: win.h (its types, _InterlockedIncrement and _InterlockedCompareExchange) and IdReadable(const void*, u64).
#pragma once

struct IndDemand {
    u64 vtable, destroy, del;        // the histories' control block: its vtable, and that vtable's _Destroy and _Delete_this
    volatile u64 made[2];            // the control blocks of the last two histories the game made (one per game state of a world)
    volatile long madeN;             // histories made since the start
    u64 kept;                        // the control block whose history every active call is given (one reference is held)
    volatile long on;                // 1 while the fix is in; 0 after a refusal: the scheduler then runs as the game's own
    volatile long shared, own, other, refused, kept_n, released;   // counters for native.log
    const char* why;                 // the first refusal
};

// a reference more on a shared_ptr's count (strong at +8, weak at +12, as MSVC's _Ref_count_base), when it is a live one
static bool IdAddRef(volatile long* n)
{
    for (;;) {
        long v = *n;
        if (v < 1 || v >= 0x7FFFFFFE) return false;
        if (_InterlockedCompareExchange(n, v + 1, v) == v) return true;
    }
}
static long IdDecrement(volatile long* n)
{
    for (;;) {
        long v = *n;
        if (_InterlockedCompareExchange(n, v - 1, v) == v) return v - 1;
    }
}

// the game made a history (its setup of a game state's industries, right after make_shared): rcx is its control block
static void IdMade(IndDemand* d, u64 ctl)
{
    if (!ctl) return;
    long n = _InterlockedIncrement(&d->madeN);
    d->made[(n - 1) & 1] = ctl;
}

// the kept history let go: the game's own release of a shared_ptr (the last reference destroys the history, the last weak
// one frees the block)
static void IdRelease(IndDemand* d)
{
    u64 k = d->kept;
    d->kept = 0;
    if (!k) return;
    _InterlockedIncrement(&d->released);
    if (IdDecrement((volatile long*)(k + 8)) != 0) return;
    ((void (*)(u64))d->destroy)(k);
    if (IdDecrement((volatile long*)(k + 12)) == 0) ((void (*)(u64))d->del)(k);
}

static void IdRefuse(IndDemand* d, const char* why)
{
    _InterlockedIncrement(&d->refused);
    if (_InterlockedCompareExchange(&d->on, 0, 1) == 1) d->why = why;
}

// the call's game state: 1 the active one, 0 the other one, -1 not readable as expected (*why says what)
static int IdFlag(u64 cap, const char** why)
{
    if (!cap || !IdReadable((const void*)cap, 48)) { *why = "captures unreadable"; return -1; }
    u64 gs = ((const u64*)cap)[1];
    if (!gs || !IdReadable((const void*)(gs + 0x18), 8)) { *why = "game state unreadable"; return -1; }
    u64 eng = *(const u64*)(gs + 0x18);
    if (!eng || !IdReadable((const void*)(eng + 0x1f8), 1)) { *why = "engine unreadable"; return -1; }
    u8 flag = *(const u8*)(eng + 0x1f8);
    if (flag > 1) { *why = "engine flag neither 0 nor 1"; return -1; }
    return flag;
}

// The captures the scheduler runs with: `cap` itself, or `copy` (six words) holding the kept history. *active: the call is
// the active state's (its history is then the one named in the returned captures' [4]).
static u64 IdPick(IndDemand* d, u64 cap, u64* copy, int* active)
{
    *active = 0;
    if (!d->on) return cap;
    const char* why = "";
    int flag = IdFlag(cap, &why);
    if (flag < 0) { IdRefuse(d, why); return cap; }
    if (flag == 0) return cap;                     // the other state's call: the game's own code returns at once
    *active = 1;
    const u64* c = (const u64*)cap;
    u64 ctl = c[5];
    // (a history the game made before the module's hooks, or for anything else than the latest world: left as the game's own)
    if (!ctl || (ctl != d->made[0] && ctl != d->made[1])) { _InterlockedIncrement(&d->other); return cap; }
    // (a history kept for a world before this one: let go first, the world it belonged to is gone)
    if (d->kept && d->kept != d->made[0] && d->kept != d->made[1]) IdRelease(d);
    if (!d->kept) {
        if ((ctl & 7) || c[4] != ctl + 16 || !IdReadable((const void*)ctl, 0x80) || *(const u64*)ctl != d->vtable) {
            IdRefuse(d, "history not laid out as expected"); return cap;
        }
        long weak = *(const volatile long*)(ctl + 12);
        if (weak < 1 || !IdAddRef((volatile long*)(ctl + 8))) { IdRefuse(d, "history's counts not as expected"); return cap; }
        d->kept = ctl;
        _InterlockedIncrement(&d->kept_n);
    }
    if (ctl == d->kept) { _InterlockedIncrement(&d->own); return cap; }
    for (int i = 0; i < 6; i++) copy[i] = c[i];
    copy[4] = d->kept + 16;
    copy[5] = d->kept;
    _InterlockedIncrement(&d->shared);
    return (u64)copy;
}
