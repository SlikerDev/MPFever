"""Packs a folder into a release zip, the folder itself at the top (MPFever/..., as the updater expects).
usage: python makezip.py <folder> <zip>

ZipFile.CreateFromDirectory of Windows PowerShell 5 (.NET Framework) wrote "/" in the zip's central directory but "\" in each
file's local header: the extractors that read the local headers (some archive managers of Linux) made flat files named
"MPFever-Server\\mod\\mpfever_1\\..." instead of folders (issue #93). Here every name uses "/" in both places, and the zip is
read back to check it."""
import os
import struct
import sys
import zipfile


def pack(folder, out):
    folder = os.path.abspath(folder)
    top = os.path.basename(folder)
    entries = []
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        rel = os.path.relpath(root, folder)
        base = top if rel == "." else top + "/" + rel.replace(os.sep, "/")
        if not dirs and not files:
            entries.append((base + "/", None))
        for f in sorted(files):
            entries.append((base + "/" + f, os.path.join(root, f)))
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, path in entries:
            if path is None:
                z.writestr(zipfile.ZipInfo(name), b"")
            else:
                z.write(path, name)
    check(out)
    return len(entries)


def check(out):
    """Every name, in the central directory and in each local header, with "/" only."""
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        bad = [i.filename for i in infos if "\\" in i.filename]
        with open(out, "rb") as f:
            for i in infos:
                f.seek(i.header_offset)
                head = f.read(30)
                if head[:4] != b"PK\x03\x04":
                    raise SystemExit("makezip: no local header for " + i.filename)
                n = struct.unpack("<H", head[26:28])[0]
                if b"\\" in f.read(n):
                    bad.append(i.filename)
    if bad:
        raise SystemExit("makezip: names with a backslash: " + ", ".join(bad[:5]))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    n = pack(sys.argv[1], sys.argv[2])
    print("makezip: %s, %d entries" % (sys.argv[2], n))
