"""Bulk writes for simulation output.

Writer discipline: every run is written by ONE explicit BEGIN/COMMIT
using executemany. Never row-by-row, and never from a read endpoint.
"""

import json
import time

import pandas as pd

from backend import db
from backend.sim import costs

_EVENT_COLS = (
    "run_id", "case_id", "macro_stage", "stage", "arrival_ts", "start_ts", "end_ts",
    "resource_id", "queue_len_at_arrival", "servers_busy",
)
_CASE_COLS = (
    "run_id", "case_id", "order_value", "customer_tier", "customer_segment",
    "priority", "is_new_customer", "fraud_risk", "region", "item_category",
    "claim_type", "claim_severity", "support_channel", "invoice_value",
    "invoice_exception", "invoice_exception_reason", "created_ts", "weekday",
    "hour", "needs_review",
)


def _event_rows(run_id, events):
    n = len(events)
    return list(zip(
        [run_id] * n,
        events["case_id"].astype("int64").tolist(),
        events["macro_stage"].tolist(),
        events["stage"].tolist(),
        events["arrival_ts"].astype("float64").tolist(),
        events["start_ts"].astype("float64").tolist(),
        events["end_ts"].astype("float64").tolist(),
        events["resource_id"].tolist(),
        events["queue_len_at_arrival"].astype("int64").tolist(),
        events["servers_busy"].astype("int64").tolist(),
    ))


def _case_rows(run_id, cases):
    n = len(cases)
    return list(zip(
        [run_id] * n,
        cases["case_id"].astype("int64").tolist(),
        cases["order_value"].astype("float64").tolist(),
        cases["customer_tier"].tolist(),
        cases["customer_segment"].tolist(),
        cases["priority"].tolist(),
        cases["is_new_customer"].astype("int64").tolist(),
        cases["fraud_risk"].astype("float64").tolist(),
        cases["region"].tolist(),
        cases["item_category"].tolist(),
        cases["claim_type"].tolist(),
        cases["claim_severity"].astype("float64").tolist(),
        cases["support_channel"].tolist(),
        cases["invoice_value"].astype("float64").tolist(),
        cases["invoice_exception"].astype("int64").tolist(),
        cases["invoice_exception_reason"].tolist(),
        cases["created_ts"].astype("float64").tolist(),
        cases["weekday"].astype("int64").tolist(),
        cases["hour"].astype("int64").tolist(),
        cases["needs_review"].astype("int64").tolist(),
    ))


def write_run(result, run_id, label=None, parent_run_id=None, ground_truth=None, conn=None):
    """Persist one simulated world. Returns the KPI dict written to `runs`.

    Re-writing an existing run_id replaces it, so a reset-and-rerun is
    idempotent -- same seed, identical result.
    """
    conn = conn or db.get_conn()
    cfg = result["config"]
    kpis = costs.run_kpis(result["events"], cfg["horizon_days"])

    event_rows = _event_rows(run_id, result["events"])
    case_rows = _case_rows(run_id, result["cases"])

    event_sql = "INSERT INTO event_log (%s) VALUES (%s)" % (
        ", ".join(_EVENT_COLS), ", ".join("?" * len(_EVENT_COLS)))
    case_sql = "INSERT INTO cases (%s) VALUES (%s)" % (
        ", ".join(_CASE_COLS), ", ".join("?" * len(_CASE_COLS)))

    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM event_log WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM cases WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM ground_truth WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

        conn.executemany(event_sql, event_rows)
        conn.executemany(case_sql, case_rows)

        if ground_truth:
            conn.execute(
                "INSERT INTO ground_truth (run_id, bottleneck_stage, true_cause, injected_at)"
                " VALUES (?, ?, ?, ?)",
                (run_id, ground_truth.get("bottleneck_stage"),
                 ground_truth.get("true_cause"), ground_truth.get("injected_at")),
            )

        conn.execute(
            "INSERT INTO runs (run_id, parent_run_id, label, config_json, created_at,"
            " mean_cycle_hours, cost_per_case, throughput_per_day) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, parent_run_id, label or cfg.get("label") or run_id,
             json.dumps(cfg), time.time(), kpis["mean_cycle_hours"],
             kpis["cost_per_case"], kpis["throughput_per_day"]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return kpis


def write_investigation(conclusion, nodes, conn=None):
    """persist an investigation and every node, each with its own
    `reasoning` string. That string is the explainability requirement: a node
    records why the agent chose that probe, what it found, and what it changed."""
    conn = conn or db.get_conn()
    inv_id = conclusion["inv_id"]
    node_rows = [
        (
            n.node_id, inv_id, n.parent_node_id, n.depth, n.seq, n.probe_type,
            n.target, float(n.selection_score), float(n.impact), float(n.uncertainty),
            json.dumps(n.evidence, default=float), json.dumps(n.hypotheses, default=float),
            n.reasoning,
        )
        for n in nodes
    ]
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM investigation_nodes WHERE inv_id = ?", (inv_id,))
        conn.execute("DELETE FROM investigations WHERE inv_id = ?", (inv_id,))
        conn.execute(
            "INSERT INTO investigations (inv_id, run_id, started_at, status,"
            " concluded_stage, concluded_cause, confidence) VALUES (?,?,?,?,?,?,?)",
            (inv_id, conclusion["run_id"], conclusion["started_at"], conclusion["status"],
             conclusion["concluded_stage"], conclusion["concluded_cause"],
             conclusion["confidence"]))
        conn.executemany(
            "INSERT INTO investigation_nodes (node_id, inv_id, parent_node_id, depth,"
            " seq, probe_type, target, selection_score, impact, uncertainty,"
            " evidence_json, hypotheses_json, reasoning) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            node_rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return inv_id


def load_investigation(inv_id, conn=None):
    row = (conn or db.get_conn()).execute(
        "SELECT * FROM investigations WHERE inv_id = ?", (inv_id,)).fetchone()
    return dict(row) if row else None


def load_nodes(inv_id, conn=None):
    return pd.read_sql(
        "SELECT * FROM investigation_nodes WHERE inv_id = ? ORDER BY seq",
        conn or db.get_conn(), params=(inv_id,))


def write_interventions(inv_id, candidates, conn=None):
    """persist an investigation's scored candidates.

    `int_id` is derived from (inv_id, action) rather than random, so re-running
    the same investigation produces the same ids. Two identical
    end-to-end runs, and a uuid here would break that for no benefit.
    """
    conn = conn or db.get_conn()
    rows = [
        (
            "%s--%s" % (inv_id, c["action"]), inv_id, c["stage"], c["action"],
            float(c["cost_30d"]), float(c["delta_hours"]),
            float(c["ci_low"]), float(c["ci_high"]),
            float(c["benefit_30d"]), float(c["roi"]),
            int(c.get("selected", 0)), int(c.get("applied", 0)),
        )
        for c in candidates
    ]
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM interventions WHERE inv_id = ?", (inv_id,))
        conn.executemany(
            "INSERT INTO interventions (int_id, inv_id, stage, action, cost,"
            " predicted_delta_hours, ci_low, ci_high, benefit_30d, roi, selected, applied)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return [r[0] for r in rows]


def mark_applied(int_id, conn=None):
    conn = conn or db.get_conn()
    conn.execute("UPDATE interventions SET applied = 1 WHERE int_id = ?", (int_id,))


# ------------------------------------------------------------------ reads ---
# Analytics run in pandas, in memory -- these just pull the frames back.

def load_events(run_id, conn=None):
    return pd.read_sql(
        "SELECT * FROM event_log WHERE run_id = ?", conn or db.get_conn(), params=(run_id,))


def load_cases(run_id, conn=None):
    return pd.read_sql(
        "SELECT * FROM cases WHERE run_id = ?", conn or db.get_conn(), params=(run_id,))


def load_run(run_id, conn=None):
    row = (conn or db.get_conn()).execute(
        "SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def load_interventions(inv_id, conn=None):
    return pd.read_sql(
        "SELECT * FROM interventions WHERE inv_id = ? ORDER BY roi DESC",
        conn or db.get_conn(), params=(inv_id,))
