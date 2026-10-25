'use strict';
const $ = id => document.getElementById(id);
const euro = cents => new Intl.NumberFormat('en-IE', {style:'currency', currency:'EUR', maximumFractionDigits:0}).format(cents / 100);
let selected = 'scoped', report = null, filter = 'highlights', busy = false;
const labels = {owed:'Owed', needs_ruling:'Needs a ruling', staff_ticket:'Staff fare excluded', exempt_notice:'Notice exemption', no_compensation:'No compensation', held:'Held', out_of_scope:'Outside scope'};
function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}
function refreshButtons() {
  document.querySelectorAll('.scenario').forEach(b => {
    b.classList.toggle('selected', b.dataset.preset === selected);
    b.setAttribute('aria-pressed', b.dataset.preset === selected ? 'true' : 'false');
    b.disabled = busy;
  });
  $('run').disabled = busy;
  $('download').disabled = busy || !report;
  document.body.classList.toggle('busy', busy);
}
async function run() {
  if (busy) return;
  busy = true; report = null; refreshButtons();
  $('run-state').textContent = 'Checking real Engine & Books…';
  $('verdict').className = 'verdict neutral';
  $('verdict-title').textContent = 'Checking this candidate…';
  $('verdict-description').textContent = 'Replaying fixed cases in a temporary ledger.';
  $('verdict-symbol').textContent = '↗';
  $('case-list').replaceChildren(node('p', 'placeholder', 'Running the independent case pack…'));
  $('control-list').replaceChildren(); $('fingerprints').replaceChildren();
  $('scope-note').textContent = '';
  for (const id of ['intended-count','protected-count','check-count','liability']) $(id).textContent = '—';
  try {
    const response = await fetch(`/api/report?preset=${encodeURIComponent(selected)}`, {cache:'no-store'});
    if (!response.ok) throw new Error('The local test run could not complete. Try again.');
    report = await response.json();
    render();
    $('run-state').textContent = 'Complete · evidence ready to inspect';
  } catch (error) {
    $('run-state').textContent = error.message;
    $('verdict-title').textContent = 'Run did not complete';
    $('verdict-description').textContent = 'No verdict was produced. Retry the checks.';
    $('case-list').replaceChildren(node('p','placeholder','No completed evidence to display.'));
  } finally { busy = false; refreshButtons(); }
}
function renderCases() {
  if (!report) return;
  const list = $('case-list'); list.replaceChildren();
  let cases = report.cases;
  if (filter === 'highlights') cases = cases.filter(c => c.id === 'original-ruling' || c.id === 'future-01' || c.group === 'protected');
  if (filter === 'failed') cases = cases.filter(c => !c.passed);
  if (!cases.length) {
    list.append(node('p','placeholder', report.simulation_ran ? 'No failed cases in this run.' : 'The existing authority gate stopped this candidate before simulation.'));
    return;
  }
  for (const c of cases) {
    const details = node('details','case');
    details.open = !c.passed;
    const summary = node('summary');
    const name = node('div','case-name'); name.append(node('strong','',c.label),node('small','',c.coupon_id));
    summary.append(node('span','',c.passed ? '·' : '×'), name, node('span','case-kind',c.group === 'intended' ? 'Should resolve' : 'Must protect'),node('span',`status ${c.passed ? '' : 'fail'}`,c.passed ? 'Pass' : 'Blocked'));
    const body = node('div','case-body'); body.append(node('p','',c.expected));
    const comparison = node('div','comparison');
    for (const [title, data] of [['BEFORE CANDIDATE',c.before],['WITH CANDIDATE',c.after]]) {
      const side = node('div'); side.append(node('h3','',title),node('p','',labels[data.status] || data.status),node('p','cash',`${euro(data.cash_cents)} cash`),node('p','',`${euro(data.voucher_offset_cents)} voucher offset`),node('p','code',data.rules_applied.length ? data.rules_applied.join(' · ') : 'No ruling cited'));
      comparison.append(side);
    }
    body.append(comparison);
    if (c.expected_match !== null) body.append(node('p','small',`Candidate matches this case: ${c.candidate_matches ? 'yes' : 'no'} · expected: ${c.expected_match ? 'yes' : 'no'}`));
    body.append(node('p','small',c.source));
    details.append(summary,body); list.append(details);
  }
}
function render() {
  const blocked = report.verdict === 'blocked', s = report.summary;
  $('verdict').className = `verdict ${blocked ? 'blocked' : ''}`;
  $('verdict-symbol').textContent = blocked ? '×' : '✓';
  $('verdict-title').textContent = blocked ? 'Candidate blocked' : 'Ready for human review';
  $('verdict-description').textContent = !report.simulation_ran
    ? 'The existing author-authority gate failed. No candidate simulation ran.'
    : selected === 'broader_scope'
      ? 'This draft settles a non-EU departure without a new authorizing ruling. The regression pack catches the overreach.'
      : selected === 'missing_guard'
        ? 'This draft matches signed vouchers too. The engine protects the offset, but the proposed scope fails the ruling’s test pack.'
        : `${s.intended_cases} intended cases resolved; ${s.protected_cases} protected cases unchanged. Passing provides evidence for a person to review.`;
  $('intended-count').textContent = report.simulation_ran ? s.intended_cases : '—';
  $('protected-count').textContent = report.simulation_ran ? s.protected_cases : '—';
  $('check-count').textContent = `${s.passed_checks}/${s.total_checks}`;
  $('liability').textContent = report.accounting ? euro(report.accounting.liability_after_cents) : 'Not run';
  $('scope-note').textContent = report.simulation_ran
    ? `${report.cases.length} cases · expected results stay fixed across candidates · ${s.failed_checks} failed check${s.failed_checks === 1 ? '' : 's'}`
    : 'Hard gates run first. A rejected author gets no simulated rule application.';
  renderCases();
  const controls = $('control-list'); controls.replaceChildren();
  for (const check of report.checks.filter(c => ['existing_engine','accounting','isolation'].includes(c.group))) {
    const item = node('div',`control ${check.passed ? '' : 'fail'}`);
    const desc = node('div'); desc.append(node('strong','',check.label),node('p','',check.detail));
    item.append(node('span','',check.passed ? '✓' : '×'),desc); controls.append(item);
  }
  const fingerprints = $('fingerprints'); fingerprints.replaceChildren();
  for (const [key,value] of Object.entries(report.fingerprints)) {
    const row = node('div','fingerprint'); row.append(node('span','',key.replace('_sha256','').replaceAll('_',' ')),node('code','',value)); fingerprints.append(row);
  }
}
$('run').addEventListener('click',run);
$('download').addEventListener('click',() => {
  if (!report || busy) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = `stormcheck-rule-lab-${report.preset}.json`;
  a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
});
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click',() => {
  filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach(b => {b.classList.toggle('selected',b === button);b.setAttribute('aria-pressed',b === button ? 'true' : 'false');});
  renderCases();
}));
async function init() {
  try {
    const response = await fetch('/api/scenarios');
    if (!response.ok) throw new Error('Unable to load the local scenarios. Reload to try again.');
    const {scenarios} = await response.json();
    for (const scenario of scenarios) {
      const button = node('button','scenario'); button.type = 'button'; button.dataset.preset = scenario.id;
      button.append(node('strong','',scenario.title),node('span','',scenario.description));
      button.addEventListener('click',() => {if (!busy) {selected = scenario.id; run();}});
      $('scenarios').append(button);
    }
    await run();
  } catch (error) { $('run-state').textContent = error.message; $('verdict-title').textContent = 'Viewer unavailable'; }
}
init();
