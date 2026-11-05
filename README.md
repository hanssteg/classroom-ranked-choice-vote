# Classroom Ranked Choice Vote

A small, dependency-free command line tool that tallies a classroom ranked choice
vote (instant-runoff style) from a CSV of ballots and writes a markdown report
explaining the result round by round — so students can follow exactly why an
option won.

## Web page (no install)

[`ranked_choice.html`](ranked_choice.html) is a single, self-contained web page
that does the same thing in the browser. Copy it to any computer (Windows, Mac,
Chromebook), double-click it, and choose or drag in a ballots CSV. It works
offline, nothing is uploaded anywhere, and it shows the report on screen with
buttons to download it as `.md` or print it.

The page contains a JavaScript port of `ranked_choice.py` that produces exactly
the same report and error messages. After changing either file, check that
they still agree (requires [Node.js](https://nodejs.org)):

```bash
python3 check_html_parity.py
```

This compares both on every CSV in `examples/` plus thousands of randomly
generated valid and invalid ballot files.

## Requirements (command line tool)

- Python 3.8 or newer (standard library only — nothing to install)

## Usage

```bash
python3 ranked_choice.py path/to/ballots.csv
```

The results are written to a markdown file next to the input, with the same name:
`path/to/ballots.csv` → `path/to/ballots.md` (overwritten if it already exists).
If the CSV is invalid, every problem found is printed to the terminal and no
output file is written.

Try the included example:

```bash
python3 ranked_choice.py examples/class_vote.csv
```

Sample output: [examples/class_vote.md](examples/class_vote.md)

## Ballot CSV format

| Name | Pizza Party | Movie Day | Extra Recess | Game Hour |
| ---- | ----------- | --------- | ------------ | --------- |
| Ava  | 1           | 2         | 3            | 4         |
| Ben  | 1           | 3         | 2            | 4         |

- The header row starts with `Name`, followed by 2–10 columns, one per option.
- Each other row is one student's ballot: the student's name, then a rank for
  every option. `1` is that student's top choice.
- Each ballot must use each number from 1 to the number of options exactly once.
- 1–100 student rows; two students may share the same name.

## How the winner is decided

1. Every ballot counts toward its first-choice option.
2. The option with the fewest votes is eliminated and locked into the lowest
   open place (last place first). Each ballot counting toward it moves to that
   voter's highest-ranked option still in the running.
3. Repeat until two options remain; the one with more votes is the winner and
   the other is second place.

**Ties** are broken deterministically: tied options are compared on how many
students ranked them second, then third, and so on; if they are identical at
every rank, the option listed earlier in the CSV header survives (or wins).
Every tie-break is explained in the report.

The output is fully deterministic: the same CSV always produces byte-identical
results.

## Running the tests

```bash
python3 -m unittest
```
