"""Checks the translations in launcher/lang.json against the texts of the code.

Every text of the launcher (C#: T("français", "English") and F(...)) and of the mod (Lua: T(...), C.T(...), C.Tf(...))
is looked up by its English version. The 0.6 feature modules (mod/.../mpfever_feat*.lua) also write their texts as
{ "French", "English" } tables (OPTIONS titles, descriptions and labels, M.TEXTS, M.TAB...), which the options host puts
through the same T(fr, en) at run time, and call T through their env (u.T(...), env.T(...), M.T(...)): those count too. lang.json lists each English text with its translations:
    { "texts": { "Host a game": { "de": "Spiel hosten", "es": "Crear partida", ... }, ... } }
This script reports, per language:
  - missing   texts of the code without a translation in that language (they show in English)
  - broken    translations whose placeholders ({0}, {1:0.0}, %s) differ from the English text
and the texts of lang.json that are no longer in the code (unused).

    python tests/test_lang.py            report (exit code 1 when something is missing or broken)
    python tests/test_lang.py --add      adds the code's new texts to lang.json, with empty translations to fill in
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LANG_FILE = ROOT / "launcher" / "lang.json"
LANGUAGES = ["de", "es", "it", "nl", "pl", "pt-BR", "ru", "ja", "ko", "zh-CN", "zh-TW"]   # French and English: in the code


def cs_literal(s, i):
    """C# regular string literal starting at s[i] == '"' -> (text, end index)."""
    assert s[i] == '"'
    i += 1
    out = []
    while s[i] != '"':
        if s[i] == "\\":
            n = s[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(n, n))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out), i + 1


def lua_literal(s, i):
    """Lua short string literal starting at s[i] (' or ") -> (text, end index)."""
    q = s[i]
    i += 1
    out = []
    while s[i] != q:
        if s[i] == "\\":
            n = s[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(n, n))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out), i + 1


def two_literals(s, i, literal, quotes):
    """After 'T(' at s[i]: the second of two string literals, or None."""
    while s[i] in " \t\r\n":
        i += 1
    if s[i] not in quotes:
        return None
    _, i = literal(s, i)
    while s[i] in " \t\r\n":
        i += 1
    if s[i] != ",":
        return None
    i += 1
    while s[i] in " \t\r\n":
        i += 1
    if s[i] not in quotes:
        return None
    en, _ = literal(s, i)
    return en


def code_keys():
    keys = {}
    for f in sorted((ROOT / "launcher").glob("*.cs")):
        s = re.sub(r"(?m)^\s*//.*$", "", f.read_text(encoding="utf-8"))   # comments
        for m in re.finditer(r"(?<![\w.])(?:L\.)?[TF]\(", s):
            en = two_literals(s, m.end(), cs_literal, '"')
            if en is not None:
                keys.setdefault(en, f.name)
    for f in sorted((ROOT / "mod").rglob("*.lua")):
        s = re.sub(r"(?m)^\s*--.*$", "", f.read_text(encoding="utf-8"))   # comments
        for m in re.finditer(r"(?<![\w.])(?:C\.)?(?:T|Tf)\(", s):
            en = two_literals(s, m.end(), lua_literal, "\"'")
            if en is not None:
                keys.setdefault(en, f.name)
    for f in sorted((ROOT / "mod").rglob("mpfever_feat*.lua")):
        for en in feat_texts(f.read_text(encoding="utf-8")):
            keys.setdefault(en, f.name)
    return keys


# two-string tables of the feature modules that are not texts
NOT_TEXTS = {
    "en",    # mpfever_feat_perms.lua LANG_PROBE = { "fr", "en" }: which language T speaks
    "got",   # mpfever_feat_stock.lua ipairs({ "paid", "got" }): two field names
}


def lua_tokens(s):
    """The tokens of a Lua source that matter here: ("str", text), ("name", text), ("num", text), ("op", text); no comments."""
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
        elif s.startswith("--", i):
            m = re.match(r"--\[(=*)\[", s[i:i + 64])
            end = s.find("]" + m.group(1) + "]", i) if m else s.find("\n", i)
            i = n if end < 0 else (end + len(m.group(1)) + 2 if m else end)
        elif c in "\"'":
            text, i = lua_literal(s, i)
            yield "str", text
        elif c == "[" and re.match(r"\[=*\[", s[i:i + 64]):
            m = re.match(r"\[(=*)\[", s[i:i + 64])
            end = s.find("]" + m.group(1) + "]", i)
            text = s[i + len(m.group(0)):end]
            i = end + len(m.group(1)) + 2
            yield "str", text[1:] if text.startswith("\n") else text
        elif c.isalpha() or c == "_":
            m = re.match(r"\w+", s[i:i + 256])
            yield "name", m.group(0)
            i += len(m.group(0))
        elif c.isdigit():
            m = re.match(r"[\w.]+", s[i:i + 256])
            yield "num", m.group(0)
            i += len(m.group(0))
        elif s.startswith("...", i):
            yield "op", "..."
            i += 3
        elif s.startswith("..", i):
            yield "op", ".."
            i += 2
        else:
            yield "op", c
            i += 1


def feat_texts(src):
    """The English texts of a feature module: the second string of every { "French", "English" } table and of every
    T("French", "English") / Tf(...) call, through any env (u.T, env.T, M.T...). A string may be a concatenation of literals."""
    toks = list(lua_tokens(src))

    def string_at(j):   # "a" .. "b" .. "c" from toks[j] -> (text, next index), or None
        if j >= len(toks) or toks[j][0] != "str":
            return None
        out = [toks[j][1]]
        j += 1
        while j + 1 < len(toks) and toks[j] == ("op", "..") and toks[j + 1][0] == "str":
            out.append(toks[j + 1][1])
            j += 2
        if j < len(toks) and toks[j] == ("op", ".."):
            return None   # not a constant
        return "".join(out), j

    out = []
    for j, t in enumerate(toks):
        if t == ("op", "{"):
            table = True
        elif t == ("op", "(") and j > 0 and toks[j - 1][0] == "name" and toks[j - 1][1] in ("T", "Tf"):
            table = False
        else:
            continue
        a = string_at(j + 1)
        if not a or a[1] >= len(toks) or toks[a[1]] != ("op", ","):
            continue
        b = string_at(a[1] + 1)
        if not b or b[1] >= len(toks):
            continue
        k = b[1]
        if table:
            if toks[k] == ("op", ",") and k + 1 < len(toks):
                k += 1
            if toks[k] != ("op", "}"):
                continue
        if b[0] not in NOT_TEXTS and b[0] not in out:
            out.append(b[0])
    return out


def placeholders(t):
    return sorted(re.findall(r"\{\d+(?::[^}]*)?\}|%s", t))


def short(t):
    return t.replace("\n", "\\n")


def main():
    keys = code_keys()
    doc = json.loads(LANG_FILE.read_text(encoding="utf-8-sig"))
    texts = doc.setdefault("texts", {})
    if "--add" in sys.argv:
        new = [k for k in keys if k not in texts]
        for k in new:
            texts[k] = {code: "" for code in LANGUAGES}
        LANG_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{len(new)} new text(s) added to {LANG_FILE.name}")
        return 0
    bad = False
    print(f"{len(keys)} texts in the code, {len(texts)} in {LANG_FILE.name}")
    for code in LANGUAGES:
        missing = [k for k in keys if not (texts.get(k) or {}).get(code)]
        broken = [k for k in keys if (texts.get(k) or {}).get(code) and placeholders(k) != placeholders(texts[k][code])]
        print(f"{code:6} {len(keys) - len(missing):4}/{len(keys)} {'OK' if not (missing or broken) else 'INCOMPLETE'}")
        for k in missing:
            print(f"    missing: {short(k)}   [{keys[k]}]")
        for k in broken:
            print(f"    broken:  {short(k)}  ->  {short(texts[k][code])}")
        bad = bad or bool(missing or broken)
    for k in texts:
        if k not in keys:
            print(f"unused (no longer in the code): {short(k)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
