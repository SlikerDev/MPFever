"""One industry-demand history for the two game states of a world (native/industry_demand.h, 0.6, ported from TPF3-MP),
offline: the header is built with MSVC into a small DLL (the way native/build.bat builds the module: freestanding, /WX) and
driven through ctypes with a stand-in for the game's memory: the scheduler's six captures, the game states' engines and their
flag at +0x1f8, the histories' control blocks (MSVC's shared_ptr counts at +8 and +12, the history at +0x10 with its attempts
due at +0x68 and its "seen" byte at +0x60).

Cases: the first active call keeps its own history (one reference more); the other state's active calls get it (captures [4]
and [5] replaced, the other four kept); a call of the inactive state and a history not made for the latest world are left
alone; a new world lets the old history go (the game's _Destroy then _Delete_this, once, when the reference was the last);
every layout that differs is refused and turns the fix off; the fix off. Then TPF3-MP's scenario: two games whose batches
fell on the two states in another order spend their attempts at other intervals with the game's two histories, at the same
intervals with one.
With the game installed (build 40425, stamp 6ad9ce10), the signatures and every byte the native module checks before it
patches (read from InstallIndustryDemand in mpfever_native.cpp) are checked in TransportFever3.exe too; another build is
only reported (the module turns the fix off there by itself).
Needs Visual Studio's C++ tools (as build.bat). Run: python tests/test_industrydemand.py
"""
import ctypes
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NATIVE = ROOT / "native"
fails = []


def check(what, cond):
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        fails.append(what)
    return cond


HARNESS = r'''
#include "win.h"
extern "C" void* memcpy(void*, const void*, size_t);
extern "C" void* memset(void*, int, size_t);
#pragma function(memcpy)
#pragma function(memset)
extern "C" void* memcpy(void* d, const void* s, size_t n) { u8* a = (u8*)d; const u8* b = (const u8*)s; while (n--) *a++ = *b++; return d; }
extern "C" void* memset(void* d, int v, size_t n) { u8* a = (u8*)d; while (n--) *a++ = (u8)v; return d; }
static bool IdReadable(const void* p, u64 n)
{
    u64 a = (u64)p, end = a + n;
    while (a < end) {
        MEMORY_BASIC_INFORMATION mi;
        if (!VirtualQuery((void*)a, &mi, sizeof(mi))) return false;
        if (mi.State != 0x1000 || (mi.Protect & 0x101) || mi.Protect == 0) return false;
        a = (u64)mi.BaseAddress + mi.RegionSize;
    }
    return true;
}
#include "industry_demand.h"
static IndDemand g;
extern "C" __declspec(dllexport) void id_init(u64 vt, u64 destroy, u64 del, long on)
{
    g.vtable = vt; g.destroy = destroy; g.del = del; g.made[0] = 0; g.made[1] = 0; g.madeN = 0; g.kept = 0; g.on = on;
    g.shared = 0; g.own = 0; g.other = 0; g.refused = 0; g.kept_n = 0; g.released = 0; g.why = 0;
}
extern "C" __declspec(dllexport) void id_made(u64 ctl) { IdMade(&g, ctl); }
extern "C" __declspec(dllexport) u64 id_pick(u64 cap, u64* copy, int* active) { return IdPick(&g, cap, copy, active); }
extern "C" __declspec(dllexport) void id_stats(i64* out)
{
    out[0] = g.shared; out[1] = g.own; out[2] = g.other; out[3] = g.refused; out[4] = g.kept_n; out[5] = g.released; out[6] = g.on;
    out[7] = (i64)g.kept;
}
extern "C" __declspec(dllexport) const char* id_why() { return g.why ? g.why : ""; }
'''


def msvc_env():
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        return None
    p = subprocess.run([vswhere, "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                        "-property", "installationPath"], capture_output=True, text=True)
    vs = (p.stdout or "").strip().splitlines()
    if not vs:
        return None
    ver = (pathlib.Path(vs[0]) / "VC" / "Auxiliary" / "Build" / "Microsoft.VCToolsVersion.default.txt").read_text().strip()
    vc = pathlib.Path(vs[0]) / "VC" / "Tools" / "MSVC" / ver
    bin_ = vc / "bin" / "Hostx64" / "x64"
    return bin_, dict(os.environ, PATH=str(bin_) + os.pathsep + os.environ.get("PATH", ""),
                      INCLUDE=str(vc / "include"), LIB=str(vc / "lib" / "x64"))


def build(tmp):
    found = msvc_env()
    if not check("Visual Studio's C++ tools found (vswhere)", found is not None):
        return None
    bin_, env = found
    (tmp / "harness.cpp").write_text(HARNESS, encoding="utf-8")
    steps = [
        [str(bin_ / "lib.exe"), "/nologo", "/def:" + str(NATIVE / "kernel32.def"), "/out:" + str(tmp / "kernel32.lib"), "/machine:x64"],
        [str(bin_ / "cl.exe"), "/nologo", "/c", "/WX", "/O2", "/GS-", "/Zl", "/EHs-c-", "/GR-", "/std:c++17", "/I", str(NATIVE),
         str(tmp / "harness.cpp"), "/Fo:" + str(tmp / "harness.obj")],
        [str(bin_ / "link.exe"), "/nologo", "/WX", "/DLL", "/NODEFAULTLIB", "/NOENTRY", "/OUT:" + str(tmp / "harness.dll"),
         str(tmp / "harness.obj"), str(tmp / "kernel32.lib")],
    ]
    for s in steps:
        p = subprocess.run(s, cwd=tmp, env=env, capture_output=True, text=True)
        if p.returncode != 0:
            check("build: " + pathlib.Path(s[0]).name, False)
            print(p.stdout + p.stderr)
            return None
    check("industry_demand.h built (cl /WX, link)", True)
    lib = ctypes.CDLL(str(tmp / "harness.dll"))
    lib.id_init.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_long]
    lib.id_made.argtypes = [ctypes.c_uint64]
    lib.id_pick.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p]
    lib.id_pick.restype = ctypes.c_uint64
    lib.id_stats.argtypes = [ctypes.c_void_p]
    lib.id_why.restype = ctypes.c_char_p
    return lib


# ---------------------------------------------------------------- the stand-in for the game's memory
KEEP = []
DESTROYED, DELETED = [], []
CB = ctypes.CFUNCTYPE(None, ctypes.c_uint64)
_destroy = CB(lambda c: DESTROYED.append(c))
_delete = CB(lambda c: DELETED.append(c))
VTABLE = (ctypes.c_uint64 * 2)(ctypes.cast(_destroy, ctypes.c_void_p).value, ctypes.cast(_delete, ctypes.c_void_p).value)
VT = ctypes.addressof(VTABLE)


def words(n):
    b = (ctypes.c_uint64 * n)()
    KEEP.append(b)
    return ctypes.addressof(b)


def w64(a, v): ctypes.c_uint64.from_address(a).value = v
def r64(a): return ctypes.c_uint64.from_address(a).value
def w32(a, v): ctypes.c_int32.from_address(a).value = v
def r32(a): return ctypes.c_int32.from_address(a).value
def w8(a, v): ctypes.c_uint8.from_address(a).value = v
def r8(a): return ctypes.c_uint8.from_address(a).value


class World:
    """Two game states, each with its engine, its history (control block) and its scheduler's captures."""
    def __init__(self, lib, made=True):
        self.eng = [words(0x40), words(0x40)]
        self.gs = [words(0x44), words(0x44)]
        self.ctl = [words(0x10), words(0x10)]
        self.cap = [words(6), words(6)]
        for i in range(2):
            w64(self.gs[i] + 0x18, self.eng[i])
            w64(self.ctl[i], VT)
            w32(self.ctl[i] + 8, 1)       # the lambda's own reference
            w32(self.ctl[i] + 12, 1)
            for k, v in enumerate((0x1000 + i, self.gs[i], 0x2000 + i, 0x3000 + i, self.ctl[i] + 16, self.ctl[i])):
                w64(self.cap[i] + 8 * k, v)
            if made:
                lib.id_made(self.ctl[i])

    def active(self, b):
        w8(self.eng[b] + 0x1f8, 1)
        w8(self.eng[1 - b] + 0x1f8, 0)


def pick(lib, cap):
    copy = (ctypes.c_uint64 * 6)()
    KEEP.append(copy)
    active = ctypes.c_int(-1)
    used = lib.id_pick(cap, ctypes.addressof(copy), ctypes.addressof(active))
    return used, active.value, ctypes.addressof(copy)


def stats(lib):
    s = (ctypes.c_int64 * 8)()
    lib.id_stats(ctypes.addressof(s))
    return dict(zip(("shared", "own", "other", "refused", "kept", "released", "on", "keptctl"), list(s)))


def init(lib, on=1):
    lib.id_init(VT, VTABLE[0], VTABLE[1], on)


def caps(a):
    return [r64(a + 8 * k) for k in range(6)]


# ---------------------------------------------------------------- cases
def unit_cases(lib):
    init(lib)
    w = World(lib)
    w.active(0)
    # the other state's call first (as when the world is copied into it): left alone, nothing kept
    used, act, _ = pick(lib, w.cap[1])
    check("inactive call: its own captures, not active", used == w.cap[1] and act == 0 and stats(lib)["kept"] == 0)
    used, act, _ = pick(lib, w.cap[0])
    s = stats(lib)
    check("first active call: its own captures, its history kept", used == w.cap[0] and act == 1 and s["keptctl"] == w.ctl[0] and s["own"] == 1)
    check("one reference more on the kept history", r32(w.ctl[0] + 8) == 2 and r32(w.ctl[0] + 12) == 1)
    w.active(1)
    used, act, copy = pick(lib, w.cap[1])
    c = caps(used)
    check("the other state's active call gets the kept history in a copy", used == copy and act == 1
          and c[4] == w.ctl[0] + 16 and c[5] == w.ctl[0] and c[:4] == caps(w.cap[1])[:4])
    check("the other state's captures themselves unchanged", caps(w.cap[1])[4:] == [w.ctl[1] + 16, w.ctl[1]])
    check("no reference taken on the other state's history", r32(w.ctl[1] + 8) == 1 and r32(w.ctl[0] + 8) == 2)
    used, act, _ = pick(lib, w.cap[0])
    check("the inactive state again: left alone", used == w.cap[0] and act == 0)
    s = stats(lib)
    check("counters: 1 shared, 1 own, 1 kept", s["shared"] == 1 and s["own"] == 1 and s["kept"] == 1 and s["refused"] == 0)

    # a history the game made for anything else than the latest world: left alone
    stranger = World(lib, made=False)
    stranger.active(0)
    used, act, _ = pick(lib, stranger.cap[0])
    check("a history not of the latest world: left alone", used == stranger.cap[0] and stats(lib)["other"] == 1
          and r32(stranger.ctl[0] + 8) == 1 and stats(lib)["keptctl"] == w.ctl[0])

    # a new world while the old one's lambda still holds its history: our reference let go, nothing destroyed
    DESTROYED.clear(); DELETED.clear()
    w2 = World(lib)
    w2.active(1)
    used, act, _ = pick(lib, w2.cap[1])
    s = stats(lib)
    check("new world: its first active call keeps its own history", used == w2.cap[1] and s["keptctl"] == w2.ctl[1] and r32(w2.ctl[1] + 8) == 2)
    check("new world: the old history let go (2 -> 1), not destroyed", r32(w.ctl[0] + 8) == 1 and not DESTROYED and not DELETED and s["released"] == 1)

    # a new world when the old one is gone: the last reference destroys the history, then frees its block
    w32(w2.ctl[1] + 8, 1)       # the old world's lambdas destroyed: only the kept reference is left
    w3 = World(lib)
    w3.active(0)
    pick(lib, w3.cap[0])
    check("the last reference: _Destroy then _Delete_this, once each", DESTROYED == [w2.ctl[1]] and DELETED == [w2.ctl[1]]
          and r32(w2.ctl[1] + 8) == 0 and r32(w2.ctl[1] + 12) == 0)
    w3.active(1)
    used, act, _ = pick(lib, w3.cap[1])
    check("the new world's other state gets the new history", caps(used)[5] == w3.ctl[0])

    # the fix off: everything left alone
    init(lib, on=0)
    w4 = World(lib)
    w4.active(0)
    used, act, _ = pick(lib, w4.cap[0])
    w4.active(1)
    used2, _, _ = pick(lib, w4.cap[1])
    check("fix off: the game's two histories", used == w4.cap[0] and used2 == w4.cap[1] and r32(w4.ctl[0] + 8) == 1 and stats(lib)["kept"] == 0)


def refusals(lib):
    def one(name, spoil, why):
        init(lib)
        w = World(lib)
        w.active(0)
        cap = spoil(w)
        before = (r32(w.ctl[0] + 8), r32(w.ctl[0] + 12))
        used, act, _ = pick(lib, cap)
        s = stats(lib)
        ok = used == cap and s["refused"] == 1 and s["on"] == 0 and s["kept"] == 0 and (r32(w.ctl[0] + 8), r32(w.ctl[0] + 12)) == before
        ok = ok and why in lib.id_why().decode()
        # (once refused, the other state's calls are left alone too)
        w.active(1)
        used2, _, _ = pick(lib, w.cap[1])
        check("refused: " + name, ok and used2 == w.cap[1])

    def data_off(w):
        w64(w.cap[0] + 32, w.ctl[0] + 24)
        return w.cap[0]

    def misaligned(w):
        lib.id_made(w.ctl[0] + 1)
        w64(w.cap[0] + 40, w.ctl[0] + 1)
        w64(w.cap[0] + 32, w.ctl[0] + 17)
        return w.cap[0]

    def vtable(w):
        w64(w.ctl[0], VT + 8)
        return w.cap[0]

    def strong0(w):
        w32(w.ctl[0] + 8, 0)
        return w.cap[0]

    def strongmax(w):
        w32(w.ctl[0] + 8, 0x7FFFFFFE)
        return w.cap[0]

    def weak0(w):
        w32(w.ctl[0] + 12, 0)
        return w.cap[0]

    def flag2(w):
        w8(w.eng[0] + 0x1f8, 2)
        return w.cap[0]

    def unreadable(w):
        return 0x10

    def nogs(w):
        w64(w.cap[0] + 8, 0)
        return w.cap[0]

    one("history not right after its control block", data_off, "laid out")
    one("control block not aligned", misaligned, "laid out")
    one("another vtable", vtable, "laid out")
    one("no strong reference left", strong0, "counts")
    one("strong count at its end", strongmax, "counts")
    one("no weak reference", weak0, "counts")
    one("engine flag 2", flag2, "flag")
    one("captures unreadable", unreadable, "captures")
    one("no game state", nogs, "game state")


def run(lib, schedule, on):
    """TPF3-MP's scenario: at each interval the batch is on state schedule[t]; the game's code spends one attempt due, then
    counts the demand change once per history it is given (five attempts)."""
    init(lib, on)
    w = World(lib)
    spawns = []
    for t, b in enumerate(schedule):
        w.active(b)
        used, act, _ = pick(lib, w.cap[1 - b])       # the copy into the other state: its call returns at once
        if used != w.cap[1 - b] or act != 0:
            spawns.append("inactive call changed")
        used, act, _ = pick(lib, w.cap[b])
        st = r64(used + 32)
        if r32(st + 0x68) > 0:
            w32(st + 0x68, r32(st + 0x68) - 1)
            spawns.append(t)
        if not r8(st + 0x60):
            w8(st + 0x60, 1)
            w32(st + 0x68, r32(st + 0x68) + 5)
    return spawns


def scenario(lib):
    a = [0, 1, 0, 1, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0]
    b = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1]
    ga, gb = run(lib, a, 0), run(lib, b, 0)
    check(f"two histories (the game's own): batches cut otherwise, other spawn steps ({ga} / {gb})", ga != gb)
    fa, fb = run(lib, a, 1), run(lib, b, 1)
    check(f"one history: the same spawn steps whatever the batches ({fa})", fa == fb == [1, 2, 3, 4, 5])


# ---------------------------------------------------------------- the installed game (build 40425)
def game_exe():
    if os.environ.get("TF3_EXE"):
        return pathlib.Path(os.environ["TF3_EXE"])
    for d in [ROOT] + list(ROOT.parents)[:6]:
        p = d / "TransportFever3.exe"
        if p.is_file():
            return p
    return None


def exe_layout():
    exe = game_exe()
    if exe is None:
        print("note: TransportFever3.exe not found next to the repository (TF3_EXE names it): the game's layout is not checked here")
        return
    data = exe.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3c)[0]
    nsec, = struct.unpack_from("<H", data, pe + 6)
    stamp, = struct.unpack_from("<I", data, pe + 8)
    optsize, = struct.unpack_from("<H", data, pe + 20)
    base, = struct.unpack_from("<Q", data, pe + 24 + 24)
    secs = []
    for i in range(nsec):
        o = pe + 24 + optsize + 40 * i
        name = data[o:o + 8].rstrip(b"\0").decode("latin1")
        vsize, va, rsize, raw = struct.unpack_from("<IIII", data, o + 8)
        secs.append((name, va, vsize, raw, rsize))
    if stamp != 0x6ad9ce10:
        print(f"note: the installed game is build stamp {stamp:08x}, not 40425 (6ad9ce10): its layout is not checked here "
              "(the native module checks it at the game's start and turns the fix off if it differs)")
        return
    text = next(s for s in secs if s[0] == ".text")
    tbytes = data[text[3]:text[3] + text[4]]

    def rd(rva, n):
        for name, va, vs, raw, rs in secs:
            if va <= rva < va + max(vs, rs):
                return data[raw + rva - va:raw + rva - va + n]
        return b""

    src = (NATIVE / "mpfever_native.cpp").read_text(encoding="utf-8")
    m = re.search(r"^static void InstallIndustryDemand\(\)\n\{\n.*?^\}\n", src, re.S | re.M)
    if not check("InstallIndustryDemand found in mpfever_native.cpp", m is not None):
        return
    body = m.group(0)
    sigs = re.findall(r'FindSigRva\("([0-9A-F? ]+)"\)', body)
    found = []
    for s in sigs:
        pat = b"".join(b"." if t == "??" else re.escape(bytes([int(t, 16)])) for t in s.split())
        hits = [text[1] + x.start() for x in re.finditer(pat, tbytes, re.S)]
        found.append(hits)
    check(f"40425: both signatures found once each ({[[hex(h) for h in x] for x in found]})", len(found) == 2 and all(len(x) == 1 for x in found))
    if len(found) != 2 or not all(len(x) == 1 for x in found):
        return
    at = {"s": found[0][0], "m": found[1][0]}
    arrays = {n: bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", v)) for n, v in re.findall(r"static const u8 (\w+)\[\] = \{([^}]*)\}", body)}
    cmps = re.findall(r"memcmp\(([sm]) \+ (0x[0-9a-f]+), (\w+), (\d+)\)", body)
    bad = [f"{w}+{off} {name}" for w, off, name, n in cmps if rd(at[w] + int(off, 16), int(n)) != arrays[name][:int(n)]]
    check(f"40425: the {len(cmps)} layout checks of the module match the game's code" + (f" (not: {bad})" if bad else ""), len(cmps) >= 8 and not bad)
    check("40425: the scheduler's prologue is the one the detour copies",
          rd(at["s"], 16) == arrays["pro"] and len(arrays["pro"]) == 16)
    mm = at["m"]
    vt = mm + 0x7d9 + 7 + struct.unpack("<i", rd(mm + 0x7dc, 4))[0]
    ivt = mm + 0x82a + 7 + struct.unpack("<i", rd(mm + 0x82d, 4))[0]
    d0, d1 = (struct.unpack("<Q", rd(vt + 8 * k, 8))[0] - base for k in range(2))
    call = struct.unpack("<Q", rd(ivt + 16, 8))[0] - base
    tend = text[1] + text[2]
    target = call + 12 + struct.unpack("<i", rd(call + 8, 4))[0]
    check(f"40425: the history's vtable {vt:x} past the code, its _Destroy {d0:x} and _Delete_this {d1:x} in it",
          vt > tend and text[1] <= d0 < tend and text[1] <= d1 < tend)
    check(f"40425: the lambda's std::function ({ivt:x}) calls the scheduler ({target:x})",
          ivt > tend and rd(call, 8) == bytes.fromhex("488B124883C108E9") and target == at["s"])
    check("40425: the setup's hooked instructions (mov [rbp-78h],rax / mov [rbp-70h],rcx) at +0x822",
          rd(mm + 0x822, 8) == bytes.fromhex("48 89 45 88 48 89 4D 90"))


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mpf_inddemand_"))
    try:
        lib = build(tmp)
        if lib is not None:
            unit_cases(lib)
            refusals(lib)
            scenario(lib)
            # (the DLL is unloaded before its folder goes)
            ctypes.windll.kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
            ctypes.windll.kernel32.FreeLibrary(lib._handle)
        exe_layout()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print(f"FAIL {len(fails)} check(s): {', '.join(fails)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
