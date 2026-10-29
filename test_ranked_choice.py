"""Tests for ranked_choice.py."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import ranked_choice

EXAMPLE = """\
Name,Pizza Party,Movie Day,Extra Recess,Game Hour
Ava,1,2,3,4
Ben,1,3,2,4
Cora,2,1,3,4
Dev,4,3,1,2
Eli,3,4,2,1
Fay,3,2,4,1
Gus,4,1,2,3
Hana,1,3,4,2
"""

# Round 1 eliminates D; round 2 eliminates C on a tie broken at third-choice
# votes, and V5's ballot must skip already-eliminated D to land on A.
DEEP = """\
Name,A,B,C,D
V1,1,2,3,4
V2,1,3,4,2
V3,2,1,3,4
V4,3,1,2,4
V5,3,4,1,2
V6,2,3,1,4
V7,2,3,4,1
"""


class RankedChoiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write_csv(self, text: str, name: str = "vote.csv") -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, path: Path) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = ranked_choice.main([str(path)])
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_invalid(self, csv_text: str, *expected_fragments: str) -> None:
        path = self.write_csv(csv_text)
        code, _, err = self.run_cli(path)
        self.assertEqual(code, 1)
        for fragment in expected_fragments:
            self.assertIn(fragment, err)
        self.assertIn("No output file was written.", err)
        self.assertFalse((self.dir / "vote.md").exists())

    # --- happy path ---------------------------------------------------------

    def test_example_election(self):
        path = self.write_csv(EXAMPLE)
        code, out, err = self.run_cli(path)
        self.assertEqual(code, 0, err)
        self.assertIn("Results written to", out)
        report = (self.dir / "vote.md").read_text(encoding="utf-8")
        self.assertIn("| 1st | Game Hour |", report)
        self.assertIn("| 2nd | Pizza Party |", report)
        self.assertIn("| 3rd | Movie Day |", report)
        self.assertIn("| 4th | Extra Recess |", report)
        self.assertIn(
            "Dev's vote moved from first choice Extra Recess "
            "to second choice Game Hour.",
            report,
        )
        self.assertIn(
            "Comparing second-choice votes: Pizza Party has 1, Game Hour has 2 "
            "— Game Hour wins the tie.",
            report,
        )

    def test_ranking_and_round_structure(self):
        path = self.write_csv(DEEP)
        options, ballots, errors = ranked_choice.parse_election(path)
        self.assertEqual(errors, [])
        result = ranked_choice.run_vote(options, ballots)
        self.assertEqual(result.ranking, ["A", "B", "C", "D"])
        self.assertEqual(len(result.rounds), 3)
        self.assertEqual(result.rounds[0].eliminated, "D")
        self.assertEqual(result.rounds[0].eliminated_place, 4)
        self.assertEqual(result.rounds[1].eliminated, "C")
        self.assertIsNone(result.rounds[2].eliminated)
        self.assertEqual(result.rounds[2].winner, "A")

    def test_moves_skip_eliminated_options_and_deep_tie_break(self):
        path = self.write_csv(DEEP)
        code, _, err = self.run_cli(path)
        self.assertEqual(code, 0, err)
        report = (self.dir / "vote.md").read_text(encoding="utf-8")
        self.assertIn(
            "Comparing second-choice votes: B has 1, C has 1 — still tied.", report
        )
        self.assertIn(
            "Comparing third-choice votes: B has 3, C has 2 — C is eliminated.", report
        )
        self.assertIn("V5's vote moved from first choice C to third choice A.", report)

    def test_column_order_breaks_total_tie(self):
        path = self.write_csv("Name,A,B\nAva,1,2\nBen,2,1\n")
        code, _, err = self.run_cli(path)
        self.assertEqual(code, 0, err)
        report = (self.dir / "vote.md").read_text(encoding="utf-8")
        self.assertIn("| 1st | A |", report)
        self.assertIn("| 2nd | B |", report)
        self.assertIn(
            "A wins the tie because it comes earlier in the ballot column order",
            report,
        )

    def test_duplicate_student_names_allowed(self):
        path = self.write_csv("Name,A,B\nSam,1,2\nSam,1,2\nKim,2,1\n")
        code, _, err = self.run_cli(path)
        self.assertEqual(code, 0, err)
        report = (self.dir / "vote.md").read_text(encoding="utf-8")
        self.assertIn("| 1st | A |", report)

    def test_blank_lines_are_ignored(self):
        path = self.write_csv("Name,A,B\n\nAva,1,2\n\n")
        code, _, err = self.run_cli(path)
        self.assertEqual(code, 0, err)

    def test_deterministic_output(self):
        path = self.write_csv(EXAMPLE)
        self.run_cli(path)
        first = (self.dir / "vote.md").read_bytes()
        self.run_cli(path)
        self.assertEqual(first, (self.dir / "vote.md").read_bytes())

    # --- validation ---------------------------------------------------------

    def test_rejects_bad_header_name(self):
        self.assert_invalid("Student,A,B\nAva,1,2\n", 'first column must be "Name"')

    def test_rejects_duplicate_ranks(self):
        self.assert_invalid(
            "Name,A,B,C\nAva,1,1,3\n",
            "ranks must use each number from 1 to 3 exactly once (got 1, 1, 3)",
        )

    def test_rejects_out_of_range_rank(self):
        self.assert_invalid(
            "Name,A,B,C\nAva,0,1,2\n", "from 1 to 3 exactly once (got 0, 1, 2)"
        )

    def test_rejects_non_integer(self):
        self.assert_invalid(
            "Name,A,B\nAva,one,2\n",
            'value "one" for option "A" is not a whole number',
        )

    def test_rejects_missing_name(self):
        self.assert_invalid("Name,A,B\n,1,2\n", "Row 2: missing student name")

    def test_rejects_wrong_value_count(self):
        self.assert_invalid(
            "Name,A,B,C\nAva,1,2\n", "expected 3 rank values after the name, found 2"
        )

    def test_rejects_single_option(self):
        self.assert_invalid(
            "Name,A\nAva,1\n", "between 2 and 10 option columns, found 1"
        )

    def test_rejects_too_many_options(self):
        header = "Name," + ",".join(f"O{i}" for i in range(1, 12))
        row = "Ava," + ",".join(str(i) for i in range(1, 12))
        self.assert_invalid(
            f"{header}\n{row}\n", "between 2 and 10 option columns, found 11"
        )

    def test_rejects_no_students(self):
        self.assert_invalid("Name,A,B\n", "No student rows found")

    def test_rejects_too_many_students(self):
        rows = "\n".join(f"S{i},1,2" for i in range(101))
        self.assert_invalid(
            f"Name,A,B\n{rows}\n", "found 101, the maximum is 100"
        )

    def test_rejects_duplicate_option_names(self):
        self.assert_invalid("Name,A,A\nAva,1,2\n", 'duplicate option name "A"')

    def test_reports_all_errors_at_once(self):
        self.assert_invalid(
            "Name,A,B\n,1,2\nBen,x,2\n",
            "Row 2: missing student name",
            'value "x" for option "A" is not a whole number',
        )

    # --- CLI edges ----------------------------------------------------------

    def test_rejects_non_csv_extension(self):
        path = self.write_csv("Name,A,B\nAva,1,2\n", name="vote.txt")
        code, _, err = self.run_cli(path)
        self.assertEqual(code, 1)
        self.assertIn("expected a .csv file", err)

    def test_rejects_missing_file(self):
        code, _, err = self.run_cli(self.dir / "nope.csv")
        self.assertEqual(code, 1)
        self.assertIn("file not found", err)


if __name__ == "__main__":
    unittest.main()
