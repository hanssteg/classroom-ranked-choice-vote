#!/usr/bin/env python3
"""Check that ranked_choice.html produces exactly the same results as ranked_choice.py.

The web page contains a JavaScript port of the tally logic. This script runs
both implementations on every CSV in examples/ plus a few thousand randomly
generated ballot files (valid and invalid, with lots of ties) and fails if the
markdown report or the list of errors differs in any way.

Requires Node.js (https://nodejs.org) to run the JavaScript.

Usage:
    python3 check_html_parity.py [--cases N] [--seed S]
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import ranked_choice

ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "ranked_choice.html"

NODE_HARNESS = r"""
const fs = require("fs");
const core = fs.readFileSync(process.argv[2], "utf8");
const RCV = new Function(core + "\nreturn RCV;")();
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const results = cases.map(({ name, data }) => RCV.tally(name, new Uint8Array(Buffer.from(data, "base64"))));
process.stdout.write(JSON.stringify(results));
"""

OPTION_POOL = [
    "Pizza Party", "Movie Day", "Extra Recess", "Game Hour", "Art", "Music",
    "A | B", 'Say "hi"', "Comma, Option", "Café", "日本", "1", "2", "constructor",
    "__proto__", "x*y", "Back\\slash", "😀 Emoji",
]
NAME_POOL = [
    "Ava", "Ben", "Cora", "Dev", "Eli", "Fay", "Gus", "Hana", "Ava", "Zoë",
    "O'Neil", "Pipe|Name", 'Quote "Q"', "Comma, Kid", "李", "  Spaced  ",
]
BAD_RANKS = ["", " ", "1.0", "x", "-1", "0", "-0", "007", "11", "+1", "١", "99999999999999999999"]


def extract_core() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    match = re.search(r'<script id="rcv-core">(.*?)</script>', html, re.S)
    if not match:
        sys.exit('Could not find <script id="rcv-core"> in ranked_choice.html')
    return match.group(1)


def python_result(name: str, data: bytes, tmp_dir: Path) -> dict:
    path = tmp_dir / name
    path.write_bytes(data)
    options, ballots, errors = ranked_choice.parse_election(path)
    if errors:
        return {"errors": errors}
    result = ranked_choice.run_vote(options, ballots)
    return {"markdown": ranked_choice.render_markdown(name, options, ballots, result)}


def random_csv(rng: random.Random) -> bytes:
    n_options = rng.choice([2, 2, 3, 3, 4, 4, 5, 6, 10])
    if rng.random() < 0.03:
        n_options = rng.choice([0, 1, 11])
    options = rng.sample(OPTION_POOL, min(n_options, len(OPTION_POOL)))
    if rng.random() < 0.03 and options:
        options[-1] = rng.choice(["", options[0]])  # empty or duplicate option
    header = ["Name"] + options
    if rng.random() < 0.02:
        header[0] = rng.choice(["name", "Student", ""])

    n_students = rng.choice([1, 2, 3, 4, 5, 6, 8, 12, 30])
    if rng.random() < 0.02:
        n_students = rng.choice([0, 101])
    # A few "styles" of ballot make ties far more likely than uniform random.
    styles = [rng.sample(range(1, n_options + 1), n_options) for _ in range(rng.randint(1, 3))]
    rows: list[list[str]] = [header]
    for _ in range(n_students):
        ranks = list(rng.choice(styles)) if styles and rng.random() < 0.6 else rng.sample(
            range(1, n_options + 1), n_options
        )
        row = [rng.choice(NAME_POOL)] + [str(r) for r in ranks]
        roll = rng.random()
        if roll < 0.02:
            row[0] = ""
        elif roll < 0.04 and len(row) > 1:
            row[rng.randrange(1, len(row))] = rng.choice(BAD_RANKS)
        elif roll < 0.05:
            row = row[:-1] if rng.random() < 0.5 else row + ["1"]
        elif roll < 0.07:
            row = [f" {cell} " for cell in row]
        rows.append(row)
        if rng.random() < 0.03:
            rows.append(rng.choice([[], [""], ["", ""], [" "]]))

    buffer = io.StringIO()
    writer = csv.writer(
        buffer,
        lineterminator=rng.choice(["\n", "\r\n", "\r"]),
        quoting=rng.choice([csv.QUOTE_MINIMAL, csv.QUOTE_MINIMAL, csv.QUOTE_ALL]),
    )
    writer.writerows(rows)
    text = buffer.getvalue()
    if rng.random() < 0.3:
        text = text.rstrip("\r\n")
    data = text.encode("utf-8")
    if rng.random() < 0.1:
        data = b"\xef\xbb\xbf" + data
    return data


HANDMADE = {
    "empty.csv": b"",
    "blank_lines.csv": b"\n\n  \n,,\n",
    "bad_utf8.csv": b"Name,A,B\nAva,1,\xff2\n",
    "latin1.csv": "Name,Café,B\nAva,1,2\n".encode("latin-1"),
    "quote_mid_field.csv": b'Name,A"x,B\nAva,1,2\n',
    "text_after_quote.csv": b'Name,"A"x,B\nAva,1,2\n',
    "unterminated_quote.csv": b'Name,A,B\nAva,1,"2\n',
    "newline_in_quotes.csv": b'Name,"Line\nBreak",B\nAva,1,2\nBen,2,1\n',
    "cr_in_quotes.csv": b'Name,"Line\r\nBreak",B\r\nAva,1,2\r\n',
    "huge_field.csv": b"Name,A,B\nAva," + b"1" * 131073 + b",2\n",
    "field_at_limit.csv": b"Name,A,B\n" + b"x" * 131072 + b",1,2\n",
    "odd_whitespace.csv": "Name,\x1cA\x85,﻿B\nAva,1,2\n".encode("utf-8"),
    "nul.csv": b"Name,A,B\nAva\x00,1,2\n",
    "spaces_after_comma.csv": b'Name, "A", B\nAva, 1, 2\n',
    "bom_twice.csv": b"\xef\xbb\xbf\xef\xbb\xbfName,A,B\nAva,1,2\n",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=int, default=3000, help="random cases (default 3000)")
    parser.add_argument("--seed", type=int, default=12345, help="random seed (default 12345)")
    args = parser.parse_args()

    node = shutil.which("node")
    if not node:
        print("Node.js is required: install it from https://nodejs.org", file=sys.stderr)
        return 2

    cases: list[tuple[str, bytes]] = []
    for path in sorted((ROOT / "examples").glob("*.csv")):
        cases.append((path.name, path.read_bytes()))
    cases.extend(HANDMADE.items())
    rng = random.Random(args.seed)
    for index in range(args.cases):
        cases.append((f"random_{index}.csv", random_csv(rng)))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        core_path = tmp_dir / "core.js"
        core_path.write_text(extract_core(), encoding="utf-8")
        harness_path = tmp_dir / "harness.js"
        harness_path.write_text(NODE_HARNESS, encoding="utf-8")
        payload = json.dumps(
            [{"name": name, "data": base64.b64encode(data).decode()} for name, data in cases]
        )
        proc = subprocess.run(
            [node, str(harness_path), str(core_path)],
            input=payload, capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            print(proc.stderr, file=sys.stderr)
            return 1
        js_results = json.loads(proc.stdout)

        case_dir = tmp_dir / "cases"
        case_dir.mkdir()
        failures = 0
        valid = 0
        for (name, data), js in zip(cases, js_results):
            py = python_result(name, data, case_dir)
            valid += "markdown" in py
            if py != js:
                failures += 1
                if failures <= 5:
                    print(f"MISMATCH: {name}")
                    print(f"  bytes:  {data[:300]!r}")
                    print(f"  python: {json.dumps(py)[:1500]}")
                    print(f"  js:     {json.dumps(js)[:1500]}")

    total = len(cases)
    if failures:
        print(f"FAILED: {failures} of {total} cases differ.")
        return 1
    print(f"OK: all {total} cases match ({valid} valid ballot files, {total - valid} invalid).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
