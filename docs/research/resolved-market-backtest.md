# First backtest: rank wallets, then predict later events

The first evaluation uses **resolved finance markets**. Final YES/NO outcomes make historical evaluation possible immediately. Closed trading alone is insufficient: require a final resolution record, binary payout, and a timestamp for when the label could become available.

```text
100 resolved markets → collect observed maker + taker wallets
                                  │
                    history before each cutoff only
                                  │
                       eligible wallet rankings
                                  │
                  ┌───────────────┼───────────────┐
                top 10%       middle 80%       bottom 10%
                  └───────────────┼───────────────┘
                         freeze these cohorts
                                  │
                      forecasts on later events
                                  │
                  compare with quoted market odds
```

**Deciles are relative performance groups.** The top 10% are not automatically statistically skilled, and the bottom 10% are not automatically negatively skilled. Ineligible and new wallets stay unknown.

## Dataset

The [resolved-market snapshot](../../datasets/finance/resolved-100-2025/v1/README.md) selects 100 markets with binary final resolution labels available in the original August–December 2025 window. Candidates must have at least seven days between reported trading opening and closure, leaving room for daily and longer-horizon experiments. That eligibility rule narrows the population; it is not a random sample of all finance trading.

Select one market per Gamma parent event and per conservative economic-family rule. In particular, different above/below and range ladders for the same stock/week must not be counted as independent events. The rules also group detected IPO/acquisition families and same-day Fed decision families. Unrecognized company aliases and common economic news can still create dependencies; market/event blocks remain necessary in evaluation.

Each selected market contains separate taker execution records, all-wallet trade legs, price history and wallet summaries. The all-wallet table includes both sides and overlaps the taker table; never add their notionals to estimate market volume. Wallet coverage means addresses exposed by the API, not complete lifetime wallet histories.

## Proposed experiment, before choosing a winning method

1. **Discover wallets from the historical data.** Include losing and inactive wallets returned by the feeds. A wallet first observed in the later evaluation period has no earlier ranking and remains unknown.
2. **Separate ranking data from prediction data.** Begin with earlier resolved markets for scoring, later dates for development, and the latest dates for a final test. A practical candidate schedule is ranking before December 1, validation December 1–14, and test December 15–31, 2025; confirm usable market and wallet counts before locking it. If sparse overlap makes it unusable, disclose that and redesign without inspecting held-out forecast results.
3. **Enforce label availability at every prediction cutoff.** A ranking can use only outcomes whose conservative `label_available_at` is earlier than that cutoff. Sorting markets by resolution date does not alone prevent leakage: a later market may already have been trading while an earlier one was unresolved. Keep correlated economic families together.
4. **Set a pilot eligibility floor.** Try at least five earlier event clusters for an exploratory ranking, with 10/20-event variants on development data. Five is deliberately a pilot setting, not a scientific guarantee. Keep evidence counts and uncertainty, and report how many wallets qualify. Never use a lifetime threshold computed from evaluation events.
5. **Compare transparent ranking methods.** The original count/positive-profit rule remains a reference where reconciled P&L is available. A score feasible from trade/outcome data is event-averaged, price-adjusted directional payoff. For one token trade, `side_sign × (settlement_payout − execution_price)` is the per-share settlement-marked edge; aggregate fills within an event before averaging across events. This is a proxy that mixes information and execution, not full wallet P&L. Transfers, split/merge operations, fees, inventory and complete positions require further reconstruction. Do not silently call it net profit.
6. **Freeze the relative cohorts.** Rank only eligible wallets using earlier data. Choose equal-sized top and bottom deciles, with an explicit deterministic tie rule and at least one member when a decile is meaningful. Preserve middle and unknown groups. If too few eligible wallets remain, report that deciles are unstable rather than forcing the experiment.
7. **Observe later trading to predict later results.** At regular calendar cutoffs, form cohort flow features from already-observed trades. The outcome being forecast must still be unknown. Where public announcement times are known, stop forecasts before those times, not merely before slow oracle settlement. Never use a settlement price as an input.
8. **Evaluate the forecast, not the ranking story.** Fit any mapping from group flow to a probability using training data only. Compare final-outcome Brier score and log loss with market odds at the same forecast times, plus an otherwise identical all-wallet model. Report coverage and event-level uncertainty. A top-decile win rate by itself is insufficient. Do not automatically reverse the bottom decile's trades; test that separately.

Do not score a wallet on its performance across all 100 markets and then replay its earlier trades with that future-informed label. That would be a retrospective description, not an out-of-sample prediction test.

## Which target first?

| Target | Label | Evaluation |
| --- | --- | --- |
| Final event outcome — first experiment | Verified YES/NO payout | Brier score, log loss, calibration |
| Market odds 24 hours / 7 days later — separate experiment | Later fully available price | Price MAE against current-price persistence |

An ended-market dataset supports both, but their targets and scores must stay separate. Closed-only selection also omits still-open, delayed or unresolved events; this first historical test cannot by itself establish performance on the full live market population.

The immediate milestone is the verified 100-market dataset and its coverage report. Wallet ranking and prediction results should be published only after their score, cutoff protocol, eligibility and held-out evaluation are implemented.

The completed sample has 51 labels before December 1, 26 during December 1–14 and 23 during December 15–31. At December 1, 93 wallets have activity in at least five earlier markets; only 43 meet that floor using taker records, giving four wallets per decile with `floor(10%)`. This supports a small pilot, not a strong population-wide claim. More prior history for recurring wallets may help more than merely increasing the number of thinly traded markets.

References: [Polymarket resolution rules](https://docs.polymarket.com/concepts/resolution), [wallet-skill research review](wallet-skill.md), and [Data API v2 schema](https://data-api.polymarket.com/v2/openapi.json).
