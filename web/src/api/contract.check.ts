/**
 * Compile-time contract check: every shape the server sends (generated from contracts/openapi.json by
 * `pnpm gen:api`) must fit the hand-written types the screens use. `pnpm typecheck` fails on drift, naming
 * the model; regenerate with `pnpm gen:api` whenever CONTRACTS changes.
 */
import type { components } from "./schema";
import type * as T from "./types";

type S = components["schemas"];
/** Resolves to `true` only when A is assignable to B; otherwise the error names both. */
type Fits<A, B> = [A] extends [B] ? true : { server: A; ui: B };
const fits = <X extends true>(_: X) => _;

// Responses: what the server sends must fit what the UI reads.
fits<Fits<S["AccessDecision"], T.AccessDecision>>(true);
fits<Fits<S["AccessMatrix"], T.AccessMatrix>>(true);
fits<Fits<S["Airport"], T.Airport>>(true);
fits<Fits<S["AnswerRequest"], T.AnswerRequest>>(true);
fits<Fits<S["AnswerResponse"], T.AnswerResponse>>(true);
fits<Fits<S["Blame"], T.Blame>>(true);
fits<Fits<S["BlameStep"], T.BlameStep>>(true);
fits<Fits<S["CfoMetrics"], T.CfoMetrics>>(true);
fits<Fits<S["ChallengeRequest"], T.ChallengeRequest>>(true);
fits<Fits<S["ChallengeResponse"], T.ChallengeResponse>>(true);
fits<Fits<S["ClaimCurve"], T.ClaimCurve>>(true);
fits<Fits<S["Commit"], T.Commit>>(true);
fits<Fits<S["Confidence"], T.Confidence>>(true);
fits<Fits<S["ConfirmResponse"], T.ConfirmResponse>>(true);
fits<Fits<S["ControlMapping"], T.ControlMapping>>(true);
fits<Fits<S["DeskRequest"], T.DeskRequest>>(true);
fits<Fits<S["Draft"], T.Draft>>(true);
fits<Fits<S["Entitlement"], T.Entitlement>>(true);
fits<Fits<S["EstimateCard"], T.EstimateCard>>(true);
// The model types calibration bins as dict[str, float]; the UI names the documented keys (lo, hi, n, accuracy,
// wilson_lo, wilson_hi). Same JSON, so that one field is checked by the eval tests, not here.
fits<Fits<Omit<S["EvalReport"], "calibration">, Omit<T.EvalReport, "calibration">>>(true);
fits<Fits<S["Evidence"], T.Evidence>>(true);
fits<Fits<S["Fact"], T.Fact>>(true);
fits<Fits<S["Flight"], T.Flight>>(true);
fits<Fits<S["FlightDecision"], T.FlightDecision>>(true);
fits<Fits<S["FlightFile"], T.FlightFile>>(true);
fits<Fits<S["FlightRow"], T.FlightRow>>(true);
fits<Fits<S["Health"], T.Health>>(true);
fits<Fits<S["InjectRequest"], T.InjectRequest>>(true);
fits<Fits<S["InjectResponse"], T.InjectResponse>>(true);
fits<Fits<S["Injection"], T.Injection>>(true);
fits<Fits<S["InvariantResult"], T.InvariantResult>>(true);
fits<Fits<S["JournalEntry"], T.JournalEntry>>(true);
fits<Fits<S["JournalLine"], T.JournalLine>>(true);
fits<Fits<S["LearnedItem"], T.LearnedItem>>(true);
fits<Fits<S["MetarObs"], T.MetarObs>>(true);
fits<Fits<S["MonthEndResponse"], T.MonthEndResponse>>(true);
fits<Fits<S["Question"], T.Question>>(true);
fits<Fits<S["ReplayDiff"], T.ReplayDiff>>(true);
fits<Fits<S["ReplayFlip"], T.ReplayFlip>>(true);
fits<Fits<S["Rollforward"], T.Rollforward>>(true);
fits<Fits<S["RollforwardRow"], T.RollforwardRow>>(true);
fits<Fits<S["Rule"], T.Rule>>(true);
fits<Fits<S["RuleProposal"], T.RuleProposal>>(true);
fits<Fits<S["Ruling"], T.Ruling>>(true);
fits<Fits<S["Session"], T.Session>>(true);
fits<Fits<S["SessionResponse"], T.SessionResponse>>(true);
fits<Fits<S["Source"], T.Source>>(true);
fits<Fits<S["StormRun"], T.StormRun>>(true);
fits<Fits<S["StormSummary"], T.StormSummary>>(true);
fits<Fits<S["StormWindow"], T.StormWindow>>(true);
fits<Fits<S["TraceEvent"], T.TraceEvent>>(true);

// Requests: what the UI sends must fit what the server accepts.
fits<Fits<T.AnswerRequest, S["AnswerRequest"]>>(true);
fits<Fits<T.ChallengeRequest, S["ChallengeRequest"]>>(true);
fits<Fits<T.DeskRequest, S["DeskRequest"]>>(true);
fits<Fits<T.InjectRequest, S["InjectRequest"]>>(true);
