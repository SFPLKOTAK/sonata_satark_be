"""
audit_planner.py
========================
Deterministic Audit Planner — generates a monthly audit schedule from
branch risk scores and auditor capacity entirely in Python.

The LLM (Groq) is used ONLY to produce a human-readable narrative summary
after the schedule has already been computed.  The schedule itself is
100% deterministic: identical inputs always produce an identical plan.

KEY GUARANTEES
--------------
1. Every branch from the DB is either scheduled or explicitly listed in
   ``overflow`` with a reason — no branch is silently dropped.
2. CRITICAL and HIGH risk branches always receive their full mandatory
   audit-days; those values are never reduced.
3. Running the API twice with the same inputs produces exactly the same
   schedule (no randomness, no AI influence on dates/assignments).

RISK TIER → MANDATORY AUDIT DAYS
---------------------------------
  CRITICAL  (score > 600)  →  7 days  (cannot be reduced)
  HIGH      (score > 400)  →  6 days  (cannot be reduced)
  MODERATE  (score > 200)  →  5 days
  LOW       (score ≤ 200)  →  4 days

MINIMAL INPUT SCHEMAS
----------------------
Branch:
    {"branch_id": "BR001", "branch_name": "Delhi Main", "risk_score": 450}

Auditor:
    {"auditor_id": "A001", "auditor_name": "Rajesh Kumar", "performance_rating": 4.5}

USAGE
-----
    planner = AuditPlanner()
    result  = planner.generate_plan(branches, auditors, plan_month="2026-07")
"""

import json
import os
import logging
from datetime import date, timedelta
from typing import List, Dict, Optional
# pyrefly: ignore [missing-import]
from openai import OpenAI

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logger = logging.getLogger("audit_planner")
logger.setLevel(logging.INFO)

if not logger.handlers:
    log_dir  = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(log_dir, "audit_planner.log")
    try:
        _fh = logging.FileHandler(log_file, encoding="utf-8")
        _fh.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
            )
        )
        logger.addHandler(_fh)
    except Exception as _e:
        print(f"Warning: could not open log file: {_e}")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WORKING_DAYS_PER_MONTH = 22

# Risk tier → mandatory audit days. CRITICAL and HIGH are hard minimums.
RISK_TIERS = [
    # (lower_bound_exclusive, grade,      audit_days, is_hard_minimum)
    (600, "CRITICAL", 7, True),
    (400, "HIGH",     6, True),
    (200, "MODERATE", 5, False),
    (  0, "LOW",      4, False),
]

# Scheduling priority (lower number = scheduled first)
RISK_PRIORITY = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}


# ---------------------------------------------------------------------------
# Pure helper functions  (no side-effects, fully deterministic)
# ---------------------------------------------------------------------------

def get_risk_grade(risk_score: int) -> str:
    for threshold, grade, _, _ in RISK_TIERS:
        if risk_score > threshold:
            return grade
    return "LOW"


def get_audit_days(risk_score: int) -> int:
    for threshold, _, days, _ in RISK_TIERS:
        if risk_score > threshold:
            return days
    return 4


def is_hard_minimum(risk_score: int) -> bool:
    """Return True if this branch's audit days cannot be reduced."""
    for threshold, _, _, hard in RISK_TIERS:
        if risk_score > threshold:
            return hard
    return False


def first_working_day(year: int, month: int) -> date:
    """Return the first Monday-Friday of the given month."""
    d = date(year, month, 1)
    while d.weekday() >= 5:          # 5=Sat, 6=Sun
        d += timedelta(days=1)
    return d


def add_working_days(start: date, num_days: int) -> date:
    """
    Return the date that is exactly ``num_days`` working days after
    (and including) ``start``.  Weekends are skipped.
    """
    count   = 0
    current = start
    while True:
        if current.weekday() < 5:
            count += 1
            if count == num_days:
                return current
        current += timedelta(days=1)


def next_working_day(d: date) -> date:
    """Return the next Mon-Fri after ``d``."""
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# AuditPlanner
# ---------------------------------------------------------------------------

class AuditPlanner:
    """
    Deterministic audit planner.

    Scheduling is done entirely in Python.
    Groq is called only for a human-readable plan narrative.
    """

    def __init__(self, groq_api_key: Optional[str] = None):
        logger.info("Initialising AuditPlanner...")
        self.api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is required")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        logger.info("AuditPlanner initialised.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_plan(
        self,
        branches:   List[Dict],
        auditors:   List[Dict],
        plan_month: Optional[str] = None,
    ) -> Dict:
        """
        Generate a deterministic audit schedule.

        Parameters
        ----------
        branches   : list of branch dicts (branch_id, branch_name, risk_score)
        auditors   : list of auditor dicts (auditor_id, auditor_name, performance_rating)
        plan_month : "YYYY-MM" string; defaults to next calendar month

        Returns
        -------
        {
            "schedule"   : [...],     # all scheduled branches
            "overflow"   : [...],     # branches that could not be fitted (capacity exhausted)
            "summary"    : {...},
            "narrative"  : "..."      # LLM-generated human-readable summary
        }
        """
        # ---- default month ----
        if not plan_month:
            today      = date.today()
            next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            plan_month = next_month.strftime("%Y-%m")

        logger.info(
            f"Generating plan for {plan_month} — "
            f"{len(branches)} branches, {len(auditors)} auditors."
        )

        # ---- validate inputs ----
        if not branches:
            raise ValueError("branches list is empty — nothing to schedule.")
        if not auditors:
            raise ValueError("auditors list is empty — no one to assign.")

        year, month = map(int, plan_month.split("-"))

        # ---- compute capacity ----
        total_available_days = len(auditors) * WORKING_DAYS_PER_MONTH
        total_required_days  = sum(get_audit_days(b["risk_score"]) for b in branches)

        logger.info(
            f"Capacity: required={total_required_days} days, "
            f"available={total_available_days} days."
        )

        # ---- run deterministic scheduler ----
        schedule, overflow = self._schedule(branches, auditors, year, month)

        # ---- post-scheduling integrity check ----
        self._validate_schedule(schedule, branches)

        scheduled_days = sum(s["audit_days"] for s in schedule)

        summary = {
            "plan_month":           plan_month,
            "total_branches":       len(branches),
            "scheduled_branches":   len(schedule),
            "overflow_branches":    len(overflow),
            "total_auditors":       len(auditors),
            "total_required_days":  total_required_days,
            "total_available_days": total_available_days,
            "scheduled_days_used":  scheduled_days,
            "capacity_utilization": (
                f"{(scheduled_days / total_available_days * 100):.1f}%"
                if total_available_days > 0 else "N/A"
            ),
        }

        logger.info(
            f"Schedule complete — {len(schedule)} scheduled, "
            f"{len(overflow)} overflow."
        )

        # ---- optional LLM narrative (non-blocking) ----
        narrative = self._generate_narrative(schedule, overflow, summary)

        return {
            "schedule":  schedule,
            "overflow":  overflow,
            "summary":   summary,
            "narrative": narrative,
        }

    # ------------------------------------------------------------------
    # Deterministic scheduler  (all logic here — no AI)
    # ------------------------------------------------------------------

    def _schedule(
        self,
        branches: List[Dict],
        auditors: List[Dict],
        year:     int,
        month:    int,
    ):
        """
        Assign branches to auditors deterministically.

        Algorithm
        ---------
        1. Sort branches by risk priority (CRITICAL first), then risk_score
           descending so ties break consistently.
        2. Sort auditors by performance_rating descending so the best
           auditors are paired with the highest-risk branches.
        3. Iterate branches in priority order.  For each branch:
           a. Among auditors that still have remaining capacity, pick the
              one whose next_available_date is earliest.
           b. Assign the branch to that auditor; update their next_available
              date and days_used counter.
        4. If no auditor has capacity for a branch, record it in overflow.
           CRITICAL and HIGH branches are listed with a clear reason;
           their mandatory days are NEVER silently reduced.

        This is fully deterministic: same inputs → same output every time.
        """
        month_start = first_working_day(year, month)

        # Sort branches: priority tier first, then higher risk_score first
        sorted_branches = sorted(
            branches,
            key=lambda b: (
                RISK_PRIORITY[get_risk_grade(b["risk_score"])],
                -b["risk_score"],
                b["branch_id"],   # stable tie-break on branch ID
            ),
        )

        # Sort auditors: best performer first
        sorted_auditors = sorted(
            auditors,
            key=lambda a: (
                -a["performance_rating"],
                a["auditor_id"],  # stable tie-break
            ),
        )

        # Per-auditor tracking state
        auditor_next_date = {a["auditor_id"]: month_start for a in sorted_auditors}
        auditor_days_used = {a["auditor_id"]: 0           for a in sorted_auditors}

        schedule = []
        overflow = []

        for priority_rank, branch in enumerate(sorted_branches, start=1):
            risk_score  = branch["risk_score"]
            audit_days  = get_audit_days(risk_score)
            risk_grade  = get_risk_grade(risk_score)
            hard_min    = is_hard_minimum(risk_score)

            # Auditors that still have enough remaining capacity
            candidates = [
                a for a in sorted_auditors
                if auditor_days_used[a["auditor_id"]] + audit_days <= WORKING_DAYS_PER_MONTH
            ]

            if not candidates:
                reason = (
                    f"All auditors at full capacity. "
                    f"Required {audit_days} days "
                    f"({'MANDATORY — cannot reduce' if hard_min else 'reducible'})."
                )
                logger.warning(
                    f"Branch '{branch['branch_name']}' ({risk_grade}) moved to overflow: {reason}"
                )
                overflow.append({
                    "branch_id":    branch["branch_id"],
                    "branch_name":  branch["branch_name"],
                    "risk_score":   risk_score,
                    "risk_grade":   risk_grade,
                    "audit_days":   audit_days,
                    "hard_minimum": hard_min,
                    "reason":       reason,
                })
                continue

            # Pick candidate with earliest next_available_date;
            # break ties by better performance_rating (already ordered)
            best = min(
                candidates,
                key=lambda a: (
                    auditor_next_date[a["auditor_id"]],
                    -a["performance_rating"],
                    a["auditor_id"],
                ),
            )

            start_date = auditor_next_date[best["auditor_id"]]
            end_date   = add_working_days(start_date, audit_days)

            schedule.append({
                "priority":     priority_rank,
                "auditor_id":   best["auditor_id"],
                "auditor_name": best["auditor_name"],
                "branch_id":    branch["branch_id"],
                "branch_name":  branch["branch_name"],
                "risk_score":   risk_score,
                "risk_grade":   risk_grade,
                "audit_days":   audit_days,
                "hard_minimum": hard_min,
                "start_date":   start_date.strftime("%Y-%m-%d"),
                "end_date":     end_date.strftime("%Y-%m-%d"),
            })

            # Advance auditor state
            auditor_next_date[best["auditor_id"]] = next_working_day(end_date)
            auditor_days_used[best["auditor_id"]] += audit_days

        return schedule, overflow

    # ------------------------------------------------------------------
    # Post-scheduling integrity validator
    # ------------------------------------------------------------------

    def _validate_schedule(self, schedule: List[Dict], all_branches: List[Dict]):
        """
        Raise AssertionError if any constraint is violated.
        Called after scheduling so bugs surface loudly in testing.
        """
        branch_ids_scheduled = {s["branch_id"] for s in schedule}
        branch_ids_all       = {b["branch_id"] for b in all_branches}

        # Every scheduled entry must have its mandatory days intact
        for s in schedule:
            expected_days = get_audit_days(s["risk_score"])
            assert s["audit_days"] == expected_days, (
                f"Branch {s['branch_id']} has audit_days={s['audit_days']} "
                f"but rule requires {expected_days} for risk_score={s['risk_score']}."
            )

        # Verify no date overlaps for the same auditor
        from collections import defaultdict
        auditor_slots: Dict[str, List] = defaultdict(list)
        for s in schedule:
            start = date.fromisoformat(s["start_date"])
            end   = date.fromisoformat(s["end_date"])
            for prev_start, prev_end, prev_branch in auditor_slots[s["auditor_id"]]:
                assert not (start <= prev_end and end >= prev_start), (
                    f"Date overlap for auditor {s['auditor_id']}: "
                    f"{s['branch_name']} ({start}–{end}) overlaps "
                    f"{prev_branch} ({prev_start}–{prev_end})."
                )
            auditor_slots[s["auditor_id"]].append((start, end, s["branch_name"]))

        logger.info("Schedule validation passed.")

    # ------------------------------------------------------------------
    # LLM narrative  (non-blocking — schedule is already finalised)
    # ------------------------------------------------------------------

    def _generate_narrative(
        self,
        schedule: List[Dict],
        overflow: List[Dict],
        summary:  Dict,
    ) -> str:
        """
        Ask Groq to write a short human-readable summary of the plan.
        The schedule is already computed; this is purely presentational.
        If the API call fails, a plain-text fallback is returned.
        """
        try:
            prompt = (
                f"Write a concise 3-5 sentence professional summary of this audit plan "
                f"for {summary['plan_month']}.\n\n"
                f"Summary stats:\n{json.dumps(summary, indent=2)}\n\n"
                f"Highlight: total branches scheduled, any overflow, capacity utilisation, "
                f"and that CRITICAL/HIGH branches have their mandatory days protected.\n"
                f"Do NOT invent or change any numbers — use only the data provided."
            )

            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role":    "system",
                        "content": (
                            "You are an audit planning assistant. "
                            "Write concise professional summaries. Plain text only, no JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=300,
            )
            narrative = response.choices[0].message.content.strip()
            logger.info("Narrative summary generated via Groq.")
            return narrative

        except Exception as e:
            logger.warning(f"Narrative generation failed (non-critical): {e}")
            # Fallback plain-text summary
            lines = [
                f"Audit Plan — {summary['plan_month']}",
                f"Scheduled: {summary['scheduled_branches']} of {summary['total_branches']} branches.",
            ]
            if summary["overflow_branches"]:
                lines.append(
                    f"Overflow: {summary['overflow_branches']} branch(es) could not be "
                    f"fitted within available auditor capacity."
                )
            lines.append(
                f"Capacity utilisation: {summary['capacity_utilization']}. "
                f"All CRITICAL and HIGH risk branches retain their mandatory audit days."
            )
            return " ".join(lines)

    # ------------------------------------------------------------------
    # Pretty-print helper
    # ------------------------------------------------------------------

    def print_plan(self, result: Dict):
        if "error" in result:
            print(f"\n❌ ERROR: {result['error']}")
            return

        s = result["summary"]
        print("\n" + "=" * 65)
        print(f"  AUDIT PLAN — {s['plan_month']}")
        print("=" * 65)
        print(f"\n📊 SUMMARY")
        for k, v in s.items():
            print(f"   {k:<30}: {v}")

        print(f"\n📋 SCHEDULE  ({len(result['schedule'])} branches)")
        for item in result["schedule"]:
            hard = " [MANDATORY DAYS]" if item["hard_minimum"] else ""
            print(
                f"   {item['priority']:>2}. {item['auditor_name']:<18}"
                f"→ {item['branch_name']:<25}"
                f" [{item['risk_grade']:<8}] "
                f"{item['audit_days']}d  "
                f"{item['start_date']} → {item['end_date']}"
                f"{hard}"
            )

        if result.get("overflow"):
            print(f"\n⚠️  OVERFLOW  ({len(result['overflow'])} branches could not be scheduled)")
            for item in result["overflow"]:
                hard = " ⚠ MANDATORY DAYS — MUST SCHEDULE SEPARATELY" if item["hard_minimum"] else ""
                print(f"   • {item['branch_name']} [{item['risk_grade']}]: {item['reason']}{hard}")

        if result.get("narrative"):
            print(f"\n📝 NARRATIVE\n   {result['narrative']}")