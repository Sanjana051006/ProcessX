"""P4.1 -- the agent's working state (Architecture §5).

Serialised to `investigations` / `investigation_nodes` after each step, which is
what lets the dashboard render the tree.
"""

from dataclasses import dataclass, field


@dataclass
class Hypothesis:
    cause: str
    p: float
    status: str = "open"        # open | supported | rejected

    def as_dict(self):
        return {"cause": self.cause, "p": self.p, "status": self.status}


@dataclass
class Evidence:
    probe_type: str             # 'stage' | 'factor'
    target: str                 # 'pick_pack' or 'order_validation:weekday'
    stage: str
    data: dict
    summary: str

    def as_dict(self):
        return {"probe_type": self.probe_type, "target": self.target,
                "stage": self.stage, "summary": self.summary, "data": self.data}


@dataclass
class StageHealth:
    """M1/M2/M3 output for one stage."""
    stage: str
    mean_wait: float
    mean_service: float
    mean_duration: float
    utilisation: float
    wait_to_service_ratio: float
    impact_share: float
    contribution_pct: float
    rank: int
    anomaly_share: float = 0.0
    anomalous: bool = False

    def as_dict(self):
        return self.__dict__.copy()


@dataclass
class Node:
    node_id: str
    parent_node_id: str | None
    depth: int
    seq: int
    probe_type: str
    target: str
    selection_score: float
    impact: float
    uncertainty: float
    evidence: dict
    hypotheses: list
    reasoning: str


@dataclass
class ProcessState:
    run_id: str
    stage_health: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    open_hypotheses: list = field(default_factory=list)
    tested_hypotheses: list = field(default_factory=list)
    budget_remaining: float = 0.0
    probes_remaining: int = 0
    actions_taken: list = field(default_factory=list)

    # Bookkeeping the loop needs on top of Architecture §5.
    probed_stages: set = field(default_factory=set)
    probed_factors: set = field(default_factory=set)   # (stage, dimension)
    hypotheses_by_stage: dict = field(default_factory=dict)
    stage_node_ids: dict = field(default_factory=dict)
    nodes: list = field(default_factory=list)

    def entropy_source(self, stage):
        """Hypotheses currently held for a stage, or None if never probed.

        A stage the agent has not looked at carries maximum uncertainty -- that
        is what makes the selection score reduce to impact for fresh candidates
        and collapse once a probe has answered the question.
        """
        return self.hypotheses_by_stage.get(stage)

    def top_hypothesis(self, stage=None, threshold=0.0):
        """The stage the agent is calling the bottleneck.

        Ranked by M2 IMPACT among stages whose cause is settled, not by
        probability. Once the agent has probed more than one stage it can hold
        two confident diagnoses at once -- in the bottleneck-A world both
        order_validation and pick_pack come back at p = 1.00 -- and the one
        worth acting on is the one carrying the delay, not whichever the
        classifier happened to be marginally surer about.
        """
        if stage is not None:
            hyps = self.hypotheses_by_stage.get(stage) or []
            return hyps[0] if hyps else None
        best, best_stage, best_impact = None, None, -1.0
        for stg, hyps in self.hypotheses_by_stage.items():
            if not hyps:
                continue
            lead = hyps[0]
            if lead["cause"] == "normal" or lead["p"] < threshold:
                continue
            health = self.stage_health.get(stg)
            impact = health.impact_share if health else 0.0
            if impact > best_impact:
                best, best_stage, best_impact = lead, stg, impact
        return (best_stage, best) if best else (None, None)

    def record(self, node, evidence, hypotheses):
        self.nodes.append(node)
        self.evidence.append(evidence)
        if hypotheses:
            self.hypotheses_by_stage[evidence.stage] = hypotheses
            self.open_hypotheses = [Hypothesis(**h).as_dict() for h in hypotheses]
        self.probes_remaining -= 1

    def as_dict(self):
        stage, lead = self.top_hypothesis()
        return {
            "run_id": self.run_id,
            "stage_health": {k: v.as_dict() for k, v in self.stage_health.items()},
            "evidence": [e.as_dict() for e in self.evidence],
            "open_hypotheses": self.open_hypotheses,
            "tested_hypotheses": self.tested_hypotheses,
            "budget_remaining": self.budget_remaining,
            "probes_remaining": self.probes_remaining,
            "actions_taken": self.actions_taken,
            "concluded_stage": stage,
            "concluded_cause": lead["cause"] if lead else None,
            "confidence": lead["p"] if lead else 0.0,
        }
