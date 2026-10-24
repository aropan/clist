# Universal Cup

← [Parsers](../parsers.md)

## Season ratings

A season combines results from its individual rounds. Its `Stage` configuration
controls round selection, participation filters, scoring, and how round scores
contribute to the season total. Recalculate ranks after filtering participants.
The season's date range must include all contributing rounds.

The official rating column for each round identifies its counted participants
and their places. The parser stores this ranking as round metadata; the season
can use it to select participants and calculate the field size, including teams
whose detailed results have not been imported. Author credits are separate from
competitive participation. Assigned places remain authoritative even when local
results are incomplete or tied. Unlinked onsite accounts still require a season
team association. Keep original participant and writer keys in round metadata;
resolve account renamings and duplicate links when recalculating the season.
Merging accounts must not change the official field size or assigned places.
Enable this source once the official round rankings are
published; an unavailable table does not mean an empty participant list.

New seasons inherit the latest matching season's configuration through
[`inherit_stage`](../../src/ranking/management/commands/inherit_stage.py).
Review the inherited settings against the new season's rules. Keep concrete
parameters in the season configuration; the calculation lives in
[`ranking.utils`](../../src/ranking/utils.py).

## Special participation

The [UCup parser](../../src/ranking/management/modules/ucup.py) reads author and
tester markers from the official rating table, including teams absent from a
round's standings. Profile IDs identify these teams; linking separate accounts
for the same team is a separate concern.

The season configuration determines how author credits are derived from a
team's other counted round scores. Apply these credits before aggregating the
season total. Unrated rounds retain their results as upsolving and contribute
neither season points nor scores used for author credits.

Behavior is covered by the [parser tests](../../src/ranking/tests/test_ucup.py)
and [season scoring tests](../../src/ranking/tests/test_stage.py).
