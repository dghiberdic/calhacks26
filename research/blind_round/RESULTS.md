# Blind round results (2026-10-23)

The four ideas in `IDEAS_blind.md` were scored by four separate judge agents (Hyphenate CEO, CTO, workshop engineer, accounting consultant). None of them knew which idea was the team's current pick. A red-team agent reviewed the then-current pick (PaidOnce) on its own.

## Estimated chance of finishing top 3 (about 60 entries)

| Idea | CEO | CTO | Workshop eng. | CPA | Avg |
|---|---|---|---|---|---|
| **1 StormCheck (airline)** | 45% | 35% | 35% | 35% | **~37%** |
| 2 PaidOnce (snack brand) | 38% | 22% | 20% | 28% | ~27% |
| 4 Chargeback (spacecraft) | 28% | 25% | 18% | 22% | ~23% |
| 3 Settle Night (concerts) | 12% | 8% | 8% | 10% | ~10% |

All four judges ranked StormCheck #1. The red team called panel estimates inflated: it put PaidOnce at 8–12% as scoped and 18–22% if executed well. Trust the ranking more than the absolute numbers.

## Why StormCheck won
- It has the most real data: BTS, METAR and CJEU law.
- Its moment is the most visual and makes sense in one viewing ("blamed the weather, but the plane was broken first").
- It is the only idea that isn't "Hyphenate's barista slide in a costume". It catches a real cause, not a duplicate.
- It is the hardest to fake live, because a judge can pick any real airport and date.

## StormCheck risks raised by the judges (FINAL_IDEA.md addresses these)
- It could drift into a legal tool. StormCheck decides facts only. Legal rules once per new pattern. The provision and journal entries stay on screen.
- Claim rate: 70% is too high. Use roughly 30–40%. The provision is exposure × claim rate, not the full €127,200.
- Fit: the judges assumed a $2.8B airline is outside Hyphenate's mid-market. **Update (from the team, unverified publicly): Hyphenate also serves companies at around $40B revenue, so this concern mostly goes away.** Keep "any company with event-driven liabilities" as the line for generalizing.
- The cause engine must be general (METAR windows plus log timestamps), not hard-coded for NS31.
- Live edge case: a crew time-out caused by the previous day's storm. It must escalate to Legal at low confidence.

## Why not the others
- **PaidOnce** is the best fit for Hyphenate's market and the most buyable, but it scores low on "New". Deduction vendors already exist, and its moment is just a database join.
- **Chargeback** is novel, but heavy on jargon. A CPA would catch FAR 42.709 being misapplied to direct labor, and the claim that a reclass reaches back into prior months.
- **Settle Night** is a clone of the workshop slides.
