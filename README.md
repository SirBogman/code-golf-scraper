# Code Golf Scraper

Downloads all of the scores from [code-golf.io](https://code-golf.io) and create a spreadsheet showing how @primo-ppcg’s proposed
[Bayesian scoring method for total rank](https://github.com/JRaspass/code-golf/issues/112) will affect the leaderboards.

## Spreadsheets

A couple of spreadsheets created with different snapshots of the scores. See bayesian-2019-10-24.xlsx and bayesian-2019-10-26.xlsx.

- The spreadsheets contain one sheet for the overall leaderboard (all-holes) and one sheet per hole.
- The hole sheets are written using formulas so that you can see how changes to things like _m_ would affect the results.
- The hole sheets include a "To Rank Up" column, which shows the number of characters required to match or exceed the score at the next highest rank. This is interesting, even though it’s no longer necessary to increase your rank to increase your score. If this scoring method were adopted, this column should be included on hole leaderboards.

Observations:

For the diamond hole, the top Brainfuck answer is ranked highly.

For the divisors hole, the 54 character Python answers are higher than the 23 character Perl 6 answers. The haskell answers are pretty high too. The "To Rank Up" column shows that, if the Perl 6 solutions were reduced to 22 characters, their score would surpass the 54 character Python scores.

The new system has some properties that the current system does not.
- The score on the overall leaderboard is now simply the sum of a user’s best scores for each hole.
- When filtering by language, the scores shown on a leaderboard will not change.
- Users can improve their score for a hole without passing another solution in rank.
- If the top solution for a hole is improved, the scores of others can be reduced. See the Ten-Pin Bowling hole in the example spreadsheets.

## Bayesian Scoring Method

_The following is @primo-ppcg’s proposal showing the details of the calculations. See the original thread [here](https://github.com/JRaspass/code-golf/issues/112)._

With the way the total score is currently calculated, a decent solution in a 'short' language will out-rank a _**phenomenal**_ solution in a 'verbose' language. I think this may be causing some users to lose interest. We've seen evidence of this already; after J was introduced, interest in Perl 6 stagnated quickly (there are currently ~3 active Perl 6 golfers, where there used to be a dozen or so). It also fails to adequately reward great golfers on the site, if they prefer to use the 'wrong' language(s).

I propose an alternate ranking system:
- Begin by computing a Bayesian estimator for the minimum solution length per language per hole. Call this _S<sub>b</sub>_, details below.
- Assign a score for each solution directly, as _Score_ = ⌊ _S<sub>b</sub>_ ÷ _S<sub>u</sub>_ × 1000 ⌉, where _S<sub>u</sub>_ is the length of the user's solution. For single language leaderboards, the score can be compute against the shortest solution, without need for an estimator.
- Order by score (affects rank), then by time of submission (does not affect rank).

---

Advantages of this system over the current system:
- It's possible to reach a near-perfect score using any language, without needing to learn J and Perl (ugh! 😜).
- It encourages users to improve the top solution for _every_ language, and not just the shortest language.
- Improving a solution will improve your score, even if you don't pass another solution in rank.
- It properly rewards the top golfers of all languages (e.g. @romancortes)

Disadvantages of this system over the current system:
- It would become more difficult to predict the ranking of a solution, however, because scores are assigned directly this would no longer be as important.

---

The Bayesian estimators can be computed as follows:

_S<sub>b</sub>_ = (_n_ ÷ (_n_ + _m_)) × _S_ + (_m_ ÷ (_n_ + _m_)) × _S<sub>a</sub>_

where:

- _n_: the number of submissions in this hole for this language.
- _m_: a small uncertainty factor (1 to 3).
- _S_: the length of the shortest solution for this language.
- _S<sub>a</sub>_: the shortest solution among all languages for this hole.

For example, taking _m_ as 1, if a language had three submissions, with the shortest being 80 in length, and the shortest solution overall were 60, the estimated shortest length for this language would be:

0.75 × 80 + 0.25 × 60 = 75

The assigned overall score would then be ⌊ 75 ÷ 80 × 1000 ⌉ = 938. If after 9 submissions the shortest solution were still 80, the estimated shortest length would be at 78, for a score of 975.

It should be noted that if all languages used the same _m_ value (e.g. 1), more popular languages would have a more favorable Bayesian weighting due to their popularity alone, and therefore higher scores. To avoid this, the most popular language can be assigned a fixed _m_ of 3, and the rest scaled against that on the range 1 .. 3:

_m_ = 2 × _n_ ÷ _n<sub>max</sub>_ + 1

where:

- _n_: the total number of submissions for this language.
- _n<sub>max</sub>_: the maximum number of submissions for any language.

In this way, the most popular language (currently Python), would need approximately 3 times as many submissions in a given hole to reach the same Bayesian weighting as the least popular language (currently Nim).
