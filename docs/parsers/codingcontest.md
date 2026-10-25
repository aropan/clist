# Coding Contest

← [Parsers](../parsers.md)

The [standings parser](../../src/ranking/management/modules/codingcontest.py)
imports archived public results from [Hall of Fame](https://codingcontest.org/hall-of-fame).
The source publishes aggregate standings without per-problem results or team
rosters.

Public results do not provide reliable identities across contests. Entries are
therefore kept separate for each contest, even within the same edition; matching
names are not sufficient to join participant histories.
