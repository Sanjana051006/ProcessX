#!/usr/bin/env bash
# The whole demo, driven from curl (P5.5 / P8).
#
#   bash backend/scripts/demo_curl.sh
#
# Requires the backend on :8000 and a bootstrapped database:
#   .venv/Scripts/python -m backend.scripts.bootstrap
#   .venv/Scripts/python -m uvicorn backend.main:app --port 8000
#
# No jq dependency -- responses are trimmed with python.

set -euo pipefail
API="${API:-http://localhost:8000/api}"
PY="${PY:-./.venv/Scripts/python.exe}"

pick() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print(eval(sys.argv[1],{'d':d}))" "$1"; }
head() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

head "beat 0 -- health"
curl -s "$API/health" | pick "(d['status'], d['journal_mode'], d['models_loaded'], d['n_runs'])"

head "beat 1a -- reset to the healthy world"
curl -s -X POST "$API/runs/reset" | pick "(d['run_id'], round(d['kpis']['mean_cycle_hours'],2), d['models_loaded'])"

head "beat 1b -- inject bottleneck A"
curl -s -X POST "$API/runs/inject/bottleneck_a" | pick "(d['run_id'], round(d['kpis']['mean_cycle_hours'],2), round(d['kpis']['sla_breach_rate']*100,2))"

head "beat 1c -- stage health: M3 fires"
curl -s "$API/stages/health" | pick "[(s['stage'], s['health'], round(s['mean_wait_hours'],2), s['anomalous']) for s in d['stages']]"

head "beat 1d -- M2 ranking"
curl -s "$API/bottlenecks/ranking" | pick "[(s['rank'], s['stage'], round(s['contribution_pct'],1)) for s in d['stages']]"

head "beat 2 -- the agent investigates"
INV=$(curl -s -X POST "$API/agent/investigate" -H 'content-type: application/json' -d '{}')
echo "$INV" | pick "(d['concluded_stage'], d['concluded_cause'], round(d['confidence'],2), d['probes_used'])"
echo "$INV" | pick "d['explanation']"
INV_ID=$(echo "$INV" | pick "d['inv_id']")

head "beat 2b -- the tree, node by node"
curl -s "$API/agent/$INV_ID/tree" | pick "[('  '*n['depth']+n['target'], round(n['selection_score'],3)) for n in d['nodes']]"

head "beat 3 -- interventions, simulated and priced"
curl -s "$API/agent/$INV_ID/interventions" | pick "[(i['action'], int(i['cost']), round(i['predicted_delta_hours'],2), round(i['roi'],2), i['selected']) for i in d['interventions']]"
INT_ID=$(curl -s "$API/agent/$INV_ID/interventions" | pick "[i['int_id'] for i in d['interventions'] if i['selected']][0]")

head "beat 4a -- apply the whole selected portfolio"
curl -s -X POST "$API/interventions/$INT_ID/apply?apply_selected=true" | pick "(d['child_run_id'], round(d['before']['mean_cycle_hours'],2), round(d['after']['mean_cycle_hours'],2), int(d['total_cost']))"

head "beat 4b -- bottleneck B has surfaced on its own"
curl -s "$API/stages/health" | pick "[(s['stage'], s['health'], round(s['mean_wait_hours'],2)) for s in d['stages']]"

head "beat 4c -- the agent re-plans, same code path"
INV2=$(curl -s -X POST "$API/agent/investigate" -H 'content-type: application/json' -d '{}')
echo "$INV2" | pick "(d['concluded_stage'], d['concluded_cause'], round(d['confidence'],2))"
echo "$INV2" | pick "d['explanation']"

head "beat 5 -- agent vs the fixed rule"
curl -s "$API/baseline/compare?run_id=bottleneck_a" | pick "('agent', d['agent']['chosen_stage'], int(d['agent']['net_benefit']))"
curl -s "$API/baseline/compare?run_id=bottleneck_a" | pick "('baseline strict', d['baseline']['strict']['chosen_stage'], d['baseline']['strict']['chosen_action'])"

head "model metric cards"
curl -s "$API/models/metrics" | pick "[(c['model'], c['display'], c['pass']) for c in d['cards']]"

printf '\n\033[1mdemo complete\033[0m\n'
