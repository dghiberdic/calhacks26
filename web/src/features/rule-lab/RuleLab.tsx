import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowDownToLine, ArrowRight, Check, FlaskConical, LockKeyhole, RefreshCw, ShieldCheck } from "lucide-react";
import { count, eur } from "@/lib/format";
import { loadRuleLabReport } from "./client";
import { PRESETS, type Case, type Evidence, type Outcome, type Preset, type RuleLabReport } from "./types";
import "./rule-lab.css";

const STATUS: Record<string, string> = {
  owed: "Owed", needs_ruling: "Needs a ruling", staff_ticket: "Staff fare excluded",
  exempt_notice: "Notice exemption", no_compensation: "No compensation", held: "Held", out_of_scope: "Outside scope",
};

function explanation(report: RuleLabReport) {
  if (!report.simulation_ran) return "The author lacks the authority to rule. The existing gate stops this candidate before any case is simulated.";
  if (report.preset === "broader_scope") return "This draft settles a non-EU departure without a new ruling. The test pack catches the extra authority it would assume.";
  if (report.preset === "missing_guard") return "This draft matches signed vouchers too. The engine still protects the amount, but the proposed rule exceeds the ruling’s intent.";
  return "The right cases resolve. Protected cases keep their treatment. The evidence is ready for a person to review.";
}

function download(report: RuleLabReport) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url; link.download = `stormcheck-rule-lab-${report.preset}.json`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Shared native React workbench, embedded in the animated story and in the app shell. */
export function RuleLab({ renderFigure }: { renderFigure?: (value: string) => ReactNode }) {
  const [preset, setPreset] = useState<Preset>("scoped");
  const [selected, setSelected] = useState<string | null>(null);
  const reduced = useReducedMotion();
  const query = useQuery({
    queryKey: ["rule-lab", preset], queryFn: ({signal}) => loadRuleLabReport(preset, signal),
    staleTime: Infinity, retry: false, refetchOnWindowFocus: false,
  });
  const evidence = query.data;
  const report = evidence?.report;
  const busy = query.isFetching;
  const focus = report?.cases.find(c => c.id === selected) ?? report?.cases.find(c => !c.passed) ?? report?.cases[0];

  return (
    <div className="rl-workbench" data-testid="rule-lab" aria-busy={busy}>
      <div className="rl-toolbar">
        <span className="rl-kicker"><FlaskConical size={14} aria-hidden="true" /> Q1 / RULE LAB</span>
        <span className="rl-source" role="status">
          <i data-live={evidence?.source === "live" && !busy} />
          {busy ? "Checking the candidate…" : evidence?.source === "live" ? "Live checks · simulated cases" : evidence ? "Saved evidence · simulated cases" : "Waiting for evidence"}
        </span>
      </div>
      <div className="rl-scenarios" role="group" aria-label="Rule candidates">
        {PRESETS.map((p, i) => (
          <button key={p.id} type="button" aria-label={p.label} aria-pressed={preset === p.id}
            onClick={() => { setPreset(p.id); setSelected(null); }} className="rl-scenario">
            <span className="rl-scenario-number">0{i + 1}</span><span><strong>{p.label}</strong><small>{p.note}</small></span>
          </button>
        ))}
      </div>
      <div className="rl-body">
        {query.isError ? (
          <div role="alert" className="rl-error"><h3>The evidence did not load.</h3><p>Try again to check this candidate.</p><button type="button" onClick={() => void query.refetch()}>Try again</button></div>
        ) : !report || busy ? (
          <div className="rl-loading" role="status"><div className="rl-scan" aria-hidden="true" /><ShieldCheck size={32} aria-hidden="true" /><p>Checking the ruling’s boundaries</p><span>Intended cases · protected cases · accounting controls</span></div>
        ) : (
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={report.preset} initial={reduced ? false : {opacity: 0, y: 12}} animate={{opacity: 1, y: 0}}
              transition={{duration: reduced ? 0 : 0.4}}>
              <div className="rl-result-top">
                <div className="rl-ruling"><p className="rl-kicker">THE HUMAN RULING</p><blockquote>“{report.ruling.explanation}”</blockquote><p className="rl-muted">Claims Lead · original voucher case · EU departure</p></div>
                <div className="rl-verdict" data-blocked={report.verdict === "blocked"} aria-live="polite">
                  <span className="rl-kicker"><ShieldCheck size={15} aria-hidden="true" /> {report.verdict === "blocked" ? "BOUNDARY HELD" : "REGRESSION CHECKS PASSED"}</span>
                  <h3>{report.verdict === "blocked" ? "Candidate blocked" : "Ready for human review"}</h3>
                  <p>{explanation(report)}</p>
                </div>
              </div>
              <div className="rl-stats" aria-label="Rule Lab results">
                <Stat value={report.simulation_ran ? count(report.summary.intended_cases) : "—"} label="cases to resolve" renderFigure={renderFigure} />
                <Stat value={report.simulation_ran ? count(report.summary.protected_cases) : "—"} label="cases to protect" renderFigure={renderFigure} />
                <Stat value={`${report.summary.passed_checks}/${report.summary.total_checks}`} label="checks passed" renderFigure={renderFigure} />
                <Stat value={report.accounting ? eur(report.accounting.liability_after_cents) : "Not run"} label="EU261 compensation liability · whole storm" renderFigure={renderFigure} />
              </div>
              {report.simulation_ran ? (
                <div className="rl-evidence-grid">
                  <div className="rl-map">
                    <div className="rl-map-heading"><p className="rl-kicker">A TEST FOR EVERY BOUNDARY</p><span>Choose a case to inspect <ArrowRight size={12} aria-hidden="true" /></span></div>
                    <CaseLane title="Should resolve" cases={report.cases.filter(c => c.group === "intended")} selected={focus?.id} onSelect={setSelected} />
                    <div className="rl-boundary"><span /><LockKeyhole size={13} aria-hidden="true" /> Ruling’s boundary <span /></div>
                    <CaseLane title="Must preserve" cases={report.cases.filter(c => c.group === "protected")} selected={focus?.id} onSelect={setSelected} />
                    <p className="rl-map-note">Each mark is a real result from this test pack. Amber marks a failed check.</p>
                  </div>
                  {focus ? <CaseEvidence item={focus} /> : null}
                </div>
              ) : <div className="rl-stopped"><LockKeyhole size={24} aria-hidden="true" /><div><strong>No candidate simulation ran.</strong><p>An agent can prepare the draft. It cannot inherit a person’s authority to make the ruling.</p></div></div>}
              <Controls evidence={evidence!} />
              <div className="rl-actions">
                <div><span className="rl-kicker">{evidence?.source === "recorded" ? "RECORDED ENGINE OUTPUT" : "CHECKED BY ENGINE & BOOKS"}</span><p>{evidence?.source === "recorded" ? "Saved from the real lab runner. A fresh run has not been performed here." : "Checks ran in a temporary ledger. The rule remains a proposal."}</p></div>
                <div className="rl-action-buttons"><button type="button" onClick={() => void query.refetch()}><RefreshCw size={14} aria-hidden="true" />{evidence?.source === "recorded" ? "Refresh evidence" : "Run checks again"}</button><button type="button" className="rl-export" onClick={() => download(report)}><ArrowDownToLine size={14} aria-hidden="true" />Export evidence</button></div>
              </div>
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

function Stat({value, label, renderFigure}: {value: string; label: string; renderFigure?: (value: string) => ReactNode}) {
  return <div className="rl-stat">{renderFigure && /\d/.test(value) ? renderFigure(value) : <span className="rl-figure figure">{value}</span>}<span>{label}</span></div>;
}

function CaseLane({title, cases, selected, onSelect}: {title: string; cases: Case[]; selected?: string; onSelect: (id: string) => void}) {
  return <div className="rl-lane"><div className="rl-lane-title"><span>{title}</span><span className="figure">{count(cases.length)}</span></div>
    <div className="rl-marks" role="group" aria-label={title}>{cases.map((c, i) => <button key={c.id} type="button" className="rl-mark" data-passed={c.passed} data-protected={c.group === "protected"} aria-pressed={selected === c.id} aria-label={`${c.label}: ${c.passed ? "passed" : "failed"}`} title={`${c.label} · ${c.passed ? "passed" : "failed"}`} style={{animationDelay: `${i * 18}ms`}} onClick={() => onSelect(c.id)}>{c.passed ? <Check size={13} aria-hidden="true" /> : <LockKeyhole size={13} aria-hidden="true" />}</button>)}</div>
  </div>;
}

function CaseEvidence({item: c}: {item: Case}) {
  return <section className="rl-case" aria-label="Case evidence" data-failed={!c.passed}>
    <div className="rl-case-head"><span className="rl-kicker">{c.group === "intended" ? "INTENDED CASE" : "PROTECTED CASE"}</span><span className="rl-case-state">{c.passed ? "passed" : "held by test pack"}</span></div>
    <h4>{c.label}</h4><p className="rl-case-id">{c.coupon_id}</p>
    <div className="rl-before-after"><OutcomeView title="Before the draft" outcome={c.before} /><ArrowRight size={16} aria-hidden="true" /><OutcomeView title="With the draft" outcome={c.after} /></div>
    <p className="rl-expectation">{c.expected}</p>
    {c.expected_match !== null ? <p className="rl-match">Candidate matches: <strong>{c.candidate_matches ? "yes" : "no"}</strong> · expected: <strong>{c.expected_match ? "yes" : "no"}</strong></p> : null}
    <p className="rl-case-origin">{c.source}</p>
  </section>;
}

function OutcomeView({title, outcome}: {title: string; outcome: Outcome}) {
  return <div><p className="rl-outcome-title">{title}</p><strong>{STATUS[outcome.status] ?? outcome.status}</strong><p className="rl-outcome-amount figure">{eur(outcome.cash_cents)}</p><small>compensation balance</small><p className="rl-offset">{eur(outcome.voucher_offset_cents)} voucher offset</p></div>;
}

function Controls({evidence}: {evidence: Evidence}) {
  const {report} = evidence;
  return <details className="rl-controls"><summary><span><ShieldCheck size={15} aria-hidden="true" />Accounting controls & evidence</span><span className="rl-details-plus">+</span></summary>
    <div className="rl-control-grid">{report.checks.filter(c => ["existing_engine", "accounting", "isolation"].includes(c.group)).map(c => <div key={c.id} data-passed={c.passed}><span aria-hidden="true">{c.passed ? "✓" : "!"}</span><div><strong>{c.label}</strong><p>{c.detail}</p></div></div>)}</div>
    <dl className="rl-fingerprints">{Object.entries(report.fingerprints).map(([name, hash]) => <div key={name}><dt>{name.replace("_sha256", "").replaceAll("_", " ")}</dt><dd>{hash}</dd></div>)}</dl>
    <p className="rl-limit">This pack covers Q1 voucher rules. Passing supports human review; it is not approval or certification. Fingerprints identify the tested code and inputs.</p>
  </details>;
}
