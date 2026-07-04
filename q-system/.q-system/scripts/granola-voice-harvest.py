#!/usr/bin/env python3
"""granola-voice-harvest.py — Stage 1 deterministic harvest for founder-voice enrichment.

Pairs with plan: q-system/output/plans/voice-from-granola-2026-07-04.md

Reads Granola meeting transcripts, isolates ONLY Assaf's utterances (the literal
`Me:` speaker marker that Granola's solo-recording format uses), and emits a clean
corpus + a per-meeting talk-volume ranking for curating high-talk meetings.

Determinism: speaker isolation is a regex split on the literal `Me:` / `Them:`
markers. No LLM judgment about who spoke. Transcripts that instead use
un-attributable `Speaker A/B/C` diarization (panels, multi-party) are SKIPPED and
logged — there is no deterministic way to know which speaker is Assaf, so they do
not enter the voice corpus.

Cleaning of disfluency (like/you know/false starts) is deliberately NOT done here.
That is Stage 2's job (LLM pattern synthesis + durable-vs-spoken classification).
Stage 1 stays a pure, auditable extraction.

Input:  a directory of transcript files (.txt = raw transcript string, filename is
        the title; or .json = Granola MCP result, either the raw dict with a
        `transcript` key or the [{"type":"text","text":"<json>"}] MCP wrapper).
Output: <out_dir>/me-corpus.txt      Assaf-only utterances, one section per meeting
        <out_dir>/talk-ranking.json  {ranking:[...], skipped:[...]}

Reproducer (defines done): grep -c 'Them:' me-corpus.txt == 0
Usage:  python3 granola-voice-harvest.py <in_dir> <out_dir>
"""
import json
import re
import sys
import os
import glob


def load_transcript(path):
    """Return (title, transcript_text) for a .txt or .json transcript file."""
    raw = open(path, encoding="utf-8").read()
    if path.endswith(".txt"):
        title = os.path.splitext(os.path.basename(path))[0]
        return title, raw
    data = json.loads(raw)
    # MCP wrapper: [{"type":"text","text":"<json string>"}]
    if isinstance(data, list) and data and isinstance(data[0], dict) and "text" in data[0]:
        data = json.loads(data[0]["text"])
    return data.get("title", "(untitled)"), data.get("transcript", "")


def is_me_them_format(t):
    """True only when the transcript uses the attributable Me:/Them: convention."""
    return bool(re.search(r"\bMe:\s", t)) and bool(re.search(r"\bThem:\s", t))


def extract_me(t):
    """Return the list of Assaf ('Me:') utterance chunks, in order."""
    parts = re.split(r"\b(Me|Them):\s", t)  # [pre, spk, chunk, spk, chunk, ...]
    out = []
    i = 1
    while i < len(parts) - 1:
        spk, chunk = parts[i], parts[i + 1]
        if spk == "Me":
            seg = chunk.strip()
            if seg:
                out.append(seg)
        i += 2
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: granola-voice-harvest.py <in_dir> <out_dir>")
    in_dir, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    corpus, ranking, skipped = [], [], []
    files = sorted(glob.glob(os.path.join(in_dir, "*.txt")) +
                   glob.glob(os.path.join(in_dir, "*.json")))
    for path in files:
        title, t = load_transcript(path)
        if not is_me_them_format(t):
            skipped.append({"file": os.path.basename(path), "title": title,
                            "reason": "no Me:/Them: markers (un-attributable diarization)"})
            continue
        segs = extract_me(t)
        words = sum(len(s.split()) for s in segs)
        ranking.append({"title": title, "utterances": len(segs), "words": words})
        corpus.append(f"\n\n===== {title} ({len(segs)} utterances, {words} words) =====\n")
        corpus.extend(s + "\n" for s in segs)

    ranking.sort(key=lambda r: -r["words"])
    open(os.path.join(out_dir, "me-corpus.txt"), "w", encoding="utf-8").write("".join(corpus))
    json.dump({"ranking": ranking, "skipped": skipped},
              open(os.path.join(out_dir, "talk-ranking.json"), "w"), indent=2)
    print(json.dumps({
        "meetings_used": len(ranking),
        "skipped": len(skipped),
        "total_words": sum(r["words"] for r in ranking),
        "ranking": ranking,
        "skipped_detail": skipped,
    }, indent=2))


if __name__ == "__main__":
    main()
