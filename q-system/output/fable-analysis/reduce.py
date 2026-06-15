#!/usr/bin/env python3
import json, sys, statistics as st

d = json.load(open(sys.argv[1]))
print(f"\n=== {d['project']} :: Fable vs Opus-4.8 (same repo) ===\n")

def g(m, sect, k): return d[sect].get(m, {}).get(k, 0)

def pct(n, dn): return (100.0 * n / dn) if dn else 0.0

rows = []
for m in ["fable", "opus48"]:
    msgs = g(m, "behavioral", "msgs")
    tc = g(m, "behavioral", "tool_calls")
    txt = g(m, "behavioral", "text_chars")
    txtb = g(m, "behavioral", "text_blocks")
    thb = g(m, "behavioral", "think_blocks")
    thc = g(m, "behavioral", "think_chars")
    edits = g(m, "code_sums", "edits")
    lines = g(m, "code_sums", "lines")
    nonblank = g(m, "code_sums", "nonblank")
    blank = g(m, "code_sums", "blank")
    comments = g(m, "code_sums", "comment_lines")
    sll = g(m, "code_sums", "sum_line_len")
    pdef = g(m, "code_sums", "py_defs")
    phint = g(m, "code_sums", "py_hinted_defs")
    pdoc = g(m, "code_sums", "py_docstrings")
    ptry = g(m, "code_sums", "py_try")
    pfs = g(m, "code_sums", "py_fstring")
    pfmt = g(m, "code_sums", "py_format")
    sizes = d["edit_size_lists"].get(m, [])
    tcnt = d["tool_counts"].get(m, {})
    nw = tcnt.get("Write", 0); ne = tcnt.get("Edit", 0); nme = tcnt.get("MultiEdit", 0)

    rows.append((m, {
        "assistant msgs": msgs,
        "tool calls / msg": round(tc / msgs, 2) if msgs else 0,
        "prose chars / text-block": round(txt / txtb) if txtb else 0,
        "thinking-block rate (% msgs)": round(pct(thb, msgs), 1),
        "thinking chars / block": round(thc / thb) if thb else 0,
        "--- code ---": "",
        "code edits": edits,
        "lines / edit (mean)": round(lines / edits, 1) if edits else 0,
        "lines / edit (median)": st.median(sizes) if sizes else 0,
        "lines / edit (p90)": (sorted(sizes)[int(len(sizes)*0.9)] if sizes else 0),
        "comment lines (% nonblank)": round(pct(comments, nonblank), 1),
        "blank lines (% total)": round(pct(blank, lines), 1),
        "avg line length (chars)": round(sll / lines, 1) if lines else 0,
        "Write : Edit : MultiEdit": f"{nw} : {ne} : {nme}",
        "Write share of code-tools (%)": round(pct(nw, nw+ne+nme), 1),
        "--- python ---": "",
        "py defs written": pdef,
        "docstrings / def": round(pdoc / pdef, 2) if pdef else 0,
        "type-hinted def signal / def": round(phint / pdef, 2) if pdef else 0,
        "try-blocks / 100 edits": round(pct(ptry, edits), 1),
        "f-string : .format()": f"{pfs} : {pfmt}",
    }))

keys = list(rows[0][1].keys())
w = max(len(k) for k in keys)
print(f"{'metric'.ljust(w)} | {'FABLE'.rjust(14)} | {'OPUS-4.8'.rjust(14)}")
print("-" * (w + 36))
for k in keys:
    fv = rows[0][1][k]; ov = rows[1][1][k]
    if k.startswith("---"):
        print(k)
        continue
    print(f"{k.ljust(w)} | {str(fv).rjust(14)} | {str(ov).rjust(14)}")
