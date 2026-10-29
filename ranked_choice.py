#!/usr/bin/env python3
"""Classroom ranked choice vote calculator.

Reads a CSV of ranked ballots, runs instant-runoff elimination rounds, and
writes a markdown report next to the input file (same name, .md extension)
explaining the result round by round.

Usage:
    python3 ranked_choice.py path/to/ballots.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MIN_OPTIONS = 2
MAX_OPTIONS = 10
MAX_STUDENTS = 100

_ORDINAL_WORDS = (
    "first", "second", "third", "fourth", "fifth",
    "sixth", "seventh", "eighth", "ninth", "tenth",
)

_INT_RE = re.compile(r"-?[0-9]+")


def ordinal_word(rank: int) -> str:
    """1 -> 'first', 2 -> 'second', ... (ranks are at most 10)."""
    return _ORDINAL_WORDS[rank - 1]


def place_label(place: int) -> str:
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th', ..."""
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(place, "th")
    return f"{place}{suffix}"


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def md_cell(text: str) -> str:
    """Escape pipes so option/student names cannot break markdown tables."""
    return text.replace("|", "\\|")


@dataclass
class Ballot:
    name: str
    row_number: int
    choices: list[str]           # options ordered by this student's ranks (best first)
    rank_of: dict[str, int]      # option name -> rank this student gave it


@dataclass
class Move:
    student: str
    from_option: str
    from_rank: int
    to_option: str
    to_rank: int


@dataclass
class Round:
    number: int
    counts: dict[str, int]               # active options (header order) -> votes
    tie_lines: list[str]                 # explanation of a tie-break, if one happened
    eliminated: str | None = None        # None means this is the final round
    eliminated_place: int | None = None  # e.g. 4 -> locked in as 4th place
    moves: list[Move] = field(default_factory=list)
    winner: str | None = None
    runner_up: str | None = None


@dataclass
class VoteResult:
    ranking: list[str]                   # index 0 = 1st place, ..., last = last place
    rounds: list[Round]


def parse_election(csv_path: Path) -> tuple[list[str], list[Ballot], list[str]]:
    """Read and validate the ballots CSV.

    Returns (options, ballots, errors). If errors is non-empty, the other two
    values must not be used.
    """
    errors: list[str] = []
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as handle:
            raw_rows = list(csv.reader(handle))
    except UnicodeDecodeError:
        return [], [], [f"{csv_path.name} is not valid UTF-8 text."]
    except csv.Error as exc:
        return [], [], [f"{csv_path.name} could not be parsed as CSV: {exc}"]
    except OSError as exc:
        return [], [], [f"{csv_path.name} could not be read: {exc}"]

    # Keep original row numbers; ignore rows that are entirely blank.
    rows = [
        (number, cells)
        for number, cells in enumerate(raw_rows, start=1)
        if any(cell.strip() for cell in cells)
    ]
    if not rows:
        return [], [], ["The CSV file is empty."]

    _, header = rows[0]
    first = header[0].strip()
    if first != "Name":
        errors.append(f'Header: the first column must be "Name", found "{first}".')
    options = [cell.strip() for cell in header[1:]]
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        errors.append(
            f"Header: there must be between {MIN_OPTIONS} and {MAX_OPTIONS} "
            f"option columns, found {len(options)}."
        )
    seen: dict[str, int] = {}
    for column, option in enumerate(options, start=2):
        if not option:
            errors.append(f"Header: column {column} has an empty option name.")
        elif option in seen:
            errors.append(
                f'Header: duplicate option name "{option}" '
                f"(columns {seen[option]} and {column})."
            )
        else:
            seen[option] = column

    student_rows = rows[1:]
    if not student_rows:
        errors.append("No student rows found (at least 1 is required).")
    elif len(student_rows) > MAX_STUDENTS:
        errors.append(
            f"Too many student rows: found {len(student_rows)}, "
            f"the maximum is {MAX_STUDENTS}."
        )

    n = len(options)
    ballots: list[Ballot] = []
    for row_number, cells in student_rows:
        name = cells[0].strip()
        label = f"Row {row_number}" + (f' ("{name}")' if name else "")
        if not name:
            errors.append(f"Row {row_number}: missing student name.")
        if len(cells) - 1 != n:
            errors.append(
                f"{label}: expected {n} rank values after the name, "
                f"found {len(cells) - 1}."
            )
            continue
        values: list[int] = []
        row_ok = True
        for cell, option in zip(cells[1:], options):
            text = cell.strip()
            if not text:
                errors.append(f'{label}: empty rank value for option "{option}".')
                row_ok = False
            elif not _INT_RE.fullmatch(text):
                errors.append(
                    f'{label}: value "{text}" for option "{option}" is not a whole number.'
                )
                row_ok = False
            else:
                values.append(int(text))
        if not row_ok:
            continue
        if sorted(values) != list(range(1, n + 1)):
            got = ", ".join(str(value) for value in values)
            errors.append(
                f"{label}: ranks must use each number from 1 to {n} "
                f"exactly once (got {got})."
            )
            continue
        if not name:
            continue
        rank_of = dict(zip(options, values))
        choices = sorted(options, key=lambda option: rank_of[option])
        ballots.append(
            Ballot(name=name, row_number=row_number, choices=choices, rank_of=rank_of)
        )

    return options, ballots, errors


def current_choice(ballot: Ballot, eliminated: set[str]) -> str:
    """The ballot's highest-ranked option that is still in the running."""
    for option in ballot.choices:
        if option not in eliminated:
            return option
    raise AssertionError("A ballot ran out of options; impossible with full rankings.")


def rank_count(option: str, rank: int, ballots: list[Ballot]) -> int:
    """How many students gave this option this rank on their original ballot."""
    return sum(1 for ballot in ballots if ballot.rank_of[option] == rank)


def break_tie(
    tied: list[str],
    votes: int,
    ballots: list[Ballot],
    total_ranks: int,
    find_winner: bool,
) -> tuple[str, list[str]]:
    """Resolve a tie deterministically; returns (chosen option, explanation lines).

    Tied options are compared on how many students ranked them second on their
    original ballots; if still tied, third, and so on. If identical at every
    rank, ballot column order decides (the earlier column survives or wins).
    """
    lines = [f"{join_names(tied)} are tied with {plural(votes, 'vote')} each."]
    candidates = list(tied)
    for rank in range(2, total_ranks + 1):
        at_rank = {option: rank_count(option, rank, ballots) for option in candidates}
        best = max(at_rank.values()) if find_winner else min(at_rank.values())
        narrowed = [option for option in candidates if at_rank[option] == best]
        detail = ", ".join(f"{option} has {at_rank[option]}" for option in candidates)
        prefix = f"Comparing {ordinal_word(rank)}-choice votes: {detail}"
        if len(narrowed) == 1:
            pick = narrowed[0]
            verdict = f"{pick} wins the tie." if find_winner else f"{pick} is eliminated."
            lines.append(f"{prefix} — {verdict}")
            return pick, lines
        if narrowed != candidates:
            lines.append(f"{prefix} — still tied between {join_names(narrowed)}.")
        else:
            lines.append(f"{prefix} — still tied.")
        candidates = narrowed
    if find_winner:
        pick = candidates[0]
        lines.append(
            f"Still tied after comparing every rank; {pick} wins the tie "
            f"because it comes earlier in the ballot column order."
        )
    else:
        pick = candidates[-1]
        lines.append(
            f"Still tied after comparing every rank; {pick} is eliminated "
            f"because it comes later in the ballot column order."
        )
    return pick, lines


def run_vote(options: list[str], ballots: list[Ballot]) -> VoteResult:
    eliminated: set[str] = set()
    bottom_up: list[str] = []  # options locked in so far, last place first
    rounds: list[Round] = []
    number = 0
    while True:
        number += 1
        active = [option for option in options if option not in eliminated]
        counts = {option: 0 for option in active}
        for ballot in ballots:
            counts[current_choice(ballot, eliminated)] += 1

        if len(active) == 2:
            top = max(counts.values())
            leaders = [option for option in active if counts[option] == top]
            if len(leaders) == 1:
                winner, tie_lines = leaders[0], []
            else:
                winner, tie_lines = break_tie(
                    leaders, top, ballots, len(options), find_winner=True
                )
            runner_up = next(option for option in active if option != winner)
            rounds.append(
                Round(
                    number=number,
                    counts=counts,
                    tie_lines=tie_lines,
                    winner=winner,
                    runner_up=runner_up,
                )
            )
            ranking = [winner, runner_up] + list(reversed(bottom_up))
            return VoteResult(ranking=ranking, rounds=rounds)

        fewest = min(counts.values())
        trailing = [option for option in active if counts[option] == fewest]
        if len(trailing) == 1:
            loser, tie_lines = trailing[0], []
        else:
            loser, tie_lines = break_tie(
                trailing, fewest, ballots, len(options), find_winner=False
            )
        after = eliminated | {loser}
        moves: list[Move] = []
        for ballot in ballots:  # CSV row order keeps this deterministic
            if current_choice(ballot, eliminated) == loser:
                to_option = current_choice(ballot, after)
                moves.append(
                    Move(
                        student=ballot.name,
                        from_option=loser,
                        from_rank=ballot.rank_of[loser],
                        to_option=to_option,
                        to_rank=ballot.rank_of[to_option],
                    )
                )
        rounds.append(
            Round(
                number=number,
                counts=counts,
                tie_lines=tie_lines,
                eliminated=loser,
                eliminated_place=len(active),
                moves=moves,
            )
        )
        eliminated = after
        bottom_up.append(loser)


def render_markdown(
    source_name: str,
    options: list[str],
    ballots: list[Ballot],
    result: VoteResult,
) -> str:
    column_order = {option: index for index, option in enumerate(options)}
    total = len(ballots)
    lines: list[str] = []
    out = lines.append

    out("# Ranked Choice Vote Results")
    out("")
    out(
        f"Source ballots: `{source_name}` — {plural(total, 'student')} "
        f"ranking {plural(len(options), 'option')}."
    )
    out("")
    out("## Final Standings")
    out("")
    out("| Place | Option |")
    out("| --- | --- |")
    for place, option in enumerate(result.ranking, start=1):
        out(f"| {place_label(place)} | {md_cell(option)} |")
    out("")
    out("## Round-by-Round Explanation")
    out("")
    out(
        "Each round, every ballot counts toward the voter's highest-ranked option "
        "still in the running. The option with the fewest votes is eliminated and "
        "locked into the lowest open place, and each ballot counting toward it moves "
        "to that voter's next choice still in the running. When only two options "
        "remain, the one with more votes wins."
    )
    out("")
    for round_ in result.rounds:
        is_final = round_.eliminated is None
        out(f"### Round {round_.number}" + (" (Final)" if is_final else ""))
        out("")
        out(f"Vote totals this round ({plural(total, 'ballot')}):")
        out("")
        out("| Option | Votes |")
        out("| --- | --- |")
        active = list(round_.counts)
        ordered = sorted(active, key=lambda o: (-round_.counts[o], column_order[o]))
        for option in ordered:
            out(f"| {md_cell(option)} | {round_.counts[option]} |")
        out("")
        if round_.tie_lines:
            tie_title = "Tie for first place" if is_final else "Tie for last place"
            out(f"**{tie_title}**, broken deterministically:")
            out("")
            for line in round_.tie_lines:
                out(f"- {line}")
            out("")
        if is_final:
            out(
                f"**Winner:** {round_.winner} "
                f"({plural(round_.counts[round_.winner], 'vote')}) — **1st place**."
            )
            out("")
            out(
                f"**Second place:** {round_.runner_up} "
                f"({plural(round_.counts[round_.runner_up], 'vote')})."
            )
            out("")
        else:
            loser = round_.eliminated
            out(
                f"**Last place:** {loser} ({plural(round_.counts[loser], 'vote')}) — "
                f"eliminated and locked in as **{place_label(round_.eliminated_place)} place**."
            )
            out("")
            remaining = [option for option in active if option != loser]
            moved_to = {option: 0 for option in remaining}
            for move in round_.moves:
                moved_to[move.to_option] += 1
            out(f"Votes moved from {loser} to each remaining option:")
            out("")
            out("| Moved to | Votes |")
            out("| --- | --- |")
            for option in remaining:
                out(f"| {md_cell(option)} | {moved_to[option]} |")
            out("")
            if round_.moves:
                for move in round_.moves:
                    out(
                        f"- {move.student}'s vote moved from "
                        f"{ordinal_word(move.from_rank)} choice {move.from_option} to "
                        f"{ordinal_word(move.to_rank)} choice {move.to_option}."
                    )
                out("")
            else:
                out(f"No ballots had {loser} as their current choice, so no votes moved.")
                out("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tally a classroom ranked choice vote from a CSV of ballots and write "
            "a markdown report (same name, .md extension) explaining the result."
        ),
    )
    parser.add_argument("csv_path", help="path to the ballots CSV file")
    args = parser.parse_args(argv)
    csv_path = Path(args.csv_path)

    if csv_path.suffix.lower() != ".csv":
        print(f"Error: expected a .csv file, got: {csv_path}", file=sys.stderr)
        return 1
    if not csv_path.is_file():
        print(f"Error: file not found: {csv_path}", file=sys.stderr)
        return 1

    options, ballots, errors = parse_election(csv_path)
    if errors:
        print(f"Invalid ballot CSV — {plural(len(errors), 'problem')} found:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print("No output file was written.", file=sys.stderr)
        return 1

    result = run_vote(options, ballots)
    markdown = render_markdown(csv_path.name, options, ballots, result)
    output_path = csv_path.with_suffix(".md")
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Results written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
