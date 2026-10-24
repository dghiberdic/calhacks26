# Cal Hacks 13.0 — Prize & Rules Cheat Sheet

Sources: `13.0 Hacker Guide.pdf`, `CalHacks_Hyphenate_Track.pdf`, Devpost (cal-hacks-13-0.devpost.com, fetched 2026-10-23).
Palace of Fine Arts, SF · Oct 23–25, 2026 · Wifi: `Cal Hacks 13.0` / `hackers!`

## Hard deadlines & rules
- **Submit on Devpost by Sun Oct 25, 9:00 AM PT.** This is a hard deadline. Submit a draft Saturday night and keep editing it.
- Be at the venue by 8 AM Sunday. Judging is 10:30–12:30, and **the whole team must be at the table** for the full window.
- Pitch: Devpost says **3 min pitch + 2 min Q&A** (the guide says to prepare a 2-min pitch). A **live demo is required**, and Devpost also wants a **video**, a project image and a **GitHub repo**.
- All work must be started at the event. The MLH Code of Conduct applies.
- Closing ceremony is Sun 2–4 PM.
- ⚠️ **Team size conflict:** the guide says 1–4 people (and there is a "Best Solo" prize), but Devpost says "Team required: 2 to 4." Ask in #0-ask-directors if you're solo.

## General judging (Devpost)
Application (real use, who it helps) · Intentionality (purposeful UX) · Functionality (live demo + video) · Creativity · Technical Complexity.

## Cal Hacks general prizes (per team member)
| Prize | Reward |
|---|---|
| 1st Overall | MacBook Air M5 / Framework (Devpost: $3,600) |
| 2nd Overall | Nintendo Switch 2 |
| 3rd Overall | Google Intelligent Eyewear |
| Most Creative | Instax + film |
| Most Technically Complex | NuPhy Air60 HE |
| People-First (social impact) | Apple Watch SE 3 |
| Planet-First | Parks Pass |
| Hardware | Bambu Lab A1 Mini |
| Beginner | AirPods 4 |
| Solo | AirPods Pro 3 |
| Hacker's Choice | MX Master 4 |

## Sponsor tracks, ranked by cash
| Track | Prize | What wins it |
|---|---|---|
| **Hyphenate: Autonomous Systems for Finance** (presenting sponsor) | **$8k / $5k / $3k** + fast-track interviews for top 5 | See the detailed section below |
| **Creao AI** ×3 (AI-First Disruptor, One-Person Company, Team Empowerment) | $3k cash each for 1st + 1yr Pro Max + mentorship | Brief is in a Google Doc (link in guide) |
| **Visa: Reimagining Shopping** | $5,000 | Innovation 25, UX 25, Tech 20, Commerce impact 15, Trust 15 |
| **Anthropic** (presenting; *not listed on Devpost yet*) | $5k Claude credits + 1yr Max 20x + office hours | A *named* community, a real lived problem, one thing that works and is usable Monday, Claude doing something essential, and knowing where it fails |
| **Mana.space** (*not on Devpost*) | $5,000 | Meaningful use of Mana 30, Useful 25, Original 25, Execution 20, +10 if it lives in Mana. Link public Mana chats |
| **Apify** | $2k/$1k/$800/$400/$400 + $400 Best Actor | Meaningful Apify use |
| **Spacetime** (presenting; *not on Devpost*) | $2,048 / $1,024 / $512 | SpacetimeDB as the core real-time backend (multiplayer, live state, agent coordination, trading sims) |
| **Factory Droid SDK** | $2,000 + credits | Droid does real work at runtime on a trigger you designed, with scoped permissions and visible plans/diffs. Chatbot wrappers score poorly |
| **Coinbase x402** (2 tracks) | $500 USDC per member per track | Brief in a Drive PDF |
| **Microsoft: Built for the Real World** | Surface per member (Devpost: $3,800) + FDE talk/mentorship; 2nd place: talk + mentorship | Production-minded agent (finance/productivity/health): customer understanding, measurable usefulness, path to prod, responsible design, end-to-end |
| **Fetch.ai** | $1.5k / $1k / $500 | fetch.ai/events/calhacks-13-0 |
| **CRS Credit API** | $1k overall, $500 Best Financial AI Agent, plus interviews for Fraud/ID and Most Unexpected | Must run live against the CRS sandbox (calhacks.crscreditapi.com) |
| **Figma** ×5 | Amazon gift cards (~$1k each) + recruiting session | Brief in a Google Doc |
| **Elastic Agent Builder (Serverless)** | Quest 3S / Bose QC | — |
| **Cartesia** (voice) | Meta glasses (TBD) | Voice is core. Problem 25, Cartesia use 25, Execution 25, Responsibility 25 |
| **Capital One Nessie** | $300 per person | Completeness, creativity, complexity |
| **Meta: Bringing People Closer w/ AI** | Trip to Round 2 at Menlo Park + swag | Human connection, essential AI, working demo |
| **Moss** | AirPods Max/Pro | Voice AI, personal agent, social post |
| **Convex** | EP-133 + ESP32 display | — |
| **Armadin Security** | Apple headphones | — |
| **SpaceXAI** | Cursor keyboard | Must be built with Cursor and use the Grok Imagine/Voice API, with space data |
| **Bitdeer** | $500 / $200 credits + mice/LEGO | Use Model Studio |
| **Notability**, **Atlassian**, **Bright Data**, MLH (Gemini, Solana, Tiger Data, Vultr, Snowflake, GoDaddy, Commit Fellowship) | swag / small | — |

## Hyphenate track in detail (the biggest pot)
**Brief:** Pick a company (can be fictional: an F1 team, a festival, a Mars colony) and *one corner* of its finance team (2–3 seats that work together). Build the autonomous system you'd hire for those seats **plus the company it works in**: its software, its people, and planted mistakes in its data.

**What makes it hard (do these on purpose):** sources that disagree (bank vs. ledger vs. contract) · time (what happened in March changes June) · human handoffs and approvals, including the controller saying no · least-privilege access and segregation of duties · every decision traceable to the data, rule or person behind it.

**Judging questions:**
1. **Real enough?** Realistic data, a messy problem, proof it works.
2. **Would you hire it?** Which seats? Limited access, a clean record of its work, knowing when to ask.
3. **Something new?** A company, problem or approach they haven't seen made autonomous.
4. **The moment.** It catches what others missed, recovers from failure, or defends a decision when questioned.

**Submit:** a video that *opens with the moment* · a live demo (they may throw their own scenario at it) · one line on the seats it fills · proof: what's real vs. simulated, plus an answer key, test set or benchmark score.

**Workflows they list:** Revenue accounting, AR, Cash/Treasury, AP, Accruals, Expenses/fixed assets, Payroll, Close & consolidation, FP&A, Reporting.
**Starter kit:** Stripe, Increase, Lago, Odoo, ERPNext sandboxes · Formance/Blnk/TigerBeetle/Beancount ledgers · stripe-mock/Prism · SEC EDGAR · AccountingBench, APEX-Accounting, Finance Agent Benchmark, DABstep, BenchRec · LLMs playing approvers and auditors.
**Workshop:** Fri Oct 23, 7 PM in person ("Beyond Agentic Harnesses"). The Hyphenate team at their booth will share exceptions and edge cases.

## Natural stacks (one project, several tracks)
- **Finance agent:** Hyphenate + Microsoft Built for Real World + CRS Best Financial AI Agent + Anthropic (if Claude is core) + Factory Droid (if Droid runs the agents with scoped permissions).
- **Real-time multi-agent:** Spacetime + Hyphenate (agents coordinating in a shared ledger/world state).
- **Voice:** Cartesia + Moss + Anthropic.
- Check whether Devpost limits how many sponsor prizes one project can opt into.

