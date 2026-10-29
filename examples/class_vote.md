# Ranked Choice Vote Results

Source ballots: `class_vote.csv` — 8 students ranking 4 options.

## Final Standings

| Place | Option |
| --- | --- |
| 1st | Game Hour |
| 2nd | Pizza Party |
| 3rd | Movie Day |
| 4th | Extra Recess |

## Round-by-Round Explanation

Each round, every ballot counts toward the voter's highest-ranked option still in the running. The option with the fewest votes is eliminated and locked into the lowest open place, and each ballot counting toward it moves to that voter's next choice still in the running. When only two options remain, the one with more votes wins.

### Round 1

Vote totals this round (8 ballots):

| Option | Votes |
| --- | --- |
| Pizza Party | 3 |
| Movie Day | 2 |
| Game Hour | 2 |
| Extra Recess | 1 |

**Last place:** Extra Recess (1 vote) — eliminated and locked in as **4th place**.

Votes moved from Extra Recess to each remaining option:

| Moved to | Votes |
| --- | --- |
| Pizza Party | 0 |
| Movie Day | 0 |
| Game Hour | 1 |

- Dev's vote moved from first choice Extra Recess to second choice Game Hour.

### Round 2

Vote totals this round (8 ballots):

| Option | Votes |
| --- | --- |
| Pizza Party | 3 |
| Game Hour | 3 |
| Movie Day | 2 |

**Last place:** Movie Day (2 votes) — eliminated and locked in as **3rd place**.

Votes moved from Movie Day to each remaining option:

| Moved to | Votes |
| --- | --- |
| Pizza Party | 1 |
| Game Hour | 1 |

- Cora's vote moved from first choice Movie Day to second choice Pizza Party.
- Gus's vote moved from first choice Movie Day to third choice Game Hour.

### Round 3 (Final)

Vote totals this round (8 ballots):

| Option | Votes |
| --- | --- |
| Pizza Party | 4 |
| Game Hour | 4 |

**Tie for first place**, broken deterministically:

- Pizza Party and Game Hour are tied with 4 votes each.
- Comparing second-choice votes: Pizza Party has 1, Game Hour has 2 — Game Hour wins the tie.

**Winner:** Game Hour (4 votes) — **1st place**.

**Second place:** Pizza Party (4 votes).
