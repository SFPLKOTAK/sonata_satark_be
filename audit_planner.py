"""
simple_audit_planner.py
========================
AI-powered Audit Planner using Groq - generates monthly audit schedule
with just basic branch and auditor information.

MINIMAL INPUT SCHEMAS:
----------------------
Branch:
    {
        "branch_id": "BR001",
        "branch_name": "Delhi Main",
        "risk_score": 450          # 0-1000
    }

Auditor:
    {
        "auditor_id": "A001",
        "auditor_name": "Rajesh Kumar",
        "performance_rating": 4.5  # out of 5
    }

USAGE:
    from simple_audit_planner import AuditPlanner
    
    planner = AuditPlanner(groq_api_key="your_key")
    result = planner.generate_plan(
        branches=branches,
        auditors=auditors,
        plan_month="2026-07"
    )
"""

import json
import os
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional
from openai import OpenAI

# Constants
WORKING_DAYS_PER_MONTH = 22
MAX_AUDIT_DAYS = 7
MIN_AUDIT_DAYS = 4

def get_audit_days(risk_score: int) -> int:
    """Calculate audit days based on risk score."""
    if risk_score > 600:
        return 7
    elif risk_score > 400:
        return 6
    elif risk_score > 200:
        return 5
    else:
        return 4

def get_risk_grade(risk_score: int) -> str:
    """Get risk grade based on score."""
    if risk_score > 600:
        return "CRITICAL"
    elif risk_score > 400:
        return "HIGH"
    elif risk_score > 200:
        return "MODERATE"
    else:
        return "LOW"

class AuditPlanner:
    """Simple audit planner using Groq AI."""
    
    def __init__(self, groq_api_key: Optional[str] = None):
        """Initialize with Groq API key."""
        self.api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is required")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.groq.com/openai/v1"
        )
    
    def generate_plan(
        self,
        branches: List[Dict],    # [{"branch_id": "B1", "branch_name": "Branch A", "risk_score": 450}]
        auditors: List[Dict],    # [{"auditor_id": "A1", "auditor_name": "John", "performance_rating": 4.5}]
        plan_month: Optional[str] = None  # "2026-07"
    ) -> Dict:
        """
        Generate audit schedule using Groq AI.
        
        Returns:
            {
                "schedule": [...],
                "summary": {...},
                "raw_response": "..."
            }
        """
        
        # Set default month if not provided
        if not plan_month:
            today = date.today()
            next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            plan_month = next_month.strftime("%Y-%m")
        
        # Calculate basic capacity
        total_available_days = len(auditors) * WORKING_DAYS_PER_MONTH
        total_required_days = sum(get_audit_days(b["risk_score"]) for b in branches)
        
        # Prepare simplified data for Groq
        branches_simple = []
        for b in branches:
            branches_simple.append({
                "id": b["branch_id"],
                "name": b["branch_name"],
                "risk_score": b["risk_score"],
                "risk_grade": get_risk_grade(b["risk_score"]),
                "audit_days": get_audit_days(b["risk_score"])
            })
        
        auditors_simple = []
        for a in auditors:
            auditors_simple.append({
                "id": a["auditor_id"],
                "name": a["auditor_name"],
                "performance": a["performance_rating"],
                "capacity": WORKING_DAYS_PER_MONTH
            })
        
        # Build prompt for Groq
        prompt = self._build_prompt(
            branches_simple, 
            auditors_simple, 
            plan_month,
            total_required_days,
            total_available_days
        )
        
        # Call Groq
        try:
            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert audit planner. Respond with valid JSON only."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000,
                response_format={"type": "json_object"}
            )
            
            raw_response = response.choices[0].message.content
            result = json.loads(raw_response)
            
            # Add summary
            result["summary"] = {
                "plan_month": plan_month,
                "total_branches": len(branches),
                "total_auditors": len(auditors),
                "total_required_days": total_required_days,
                "total_available_days": total_available_days,
                "capacity_utilization": f"{(total_required_days/total_available_days*100):.1f}%" if total_available_days > 0 else "N/A"
            }
            result["raw_response"] = raw_response
            
            return result
            
        except Exception as e:
            return {
                "error": str(e),
                "schedule": [],
                "summary": {
                    "plan_month": plan_month,
                    "total_branches": len(branches),
                    "total_auditors": len(auditors),
                    "total_required_days": total_required_days,
                    "total_available_days": total_available_days
                }
            }
    
    def _build_prompt(self, branches, auditors, plan_month, req_days, avail_days) -> str:
        """Build prompt for Groq."""
        
        return f"""
Create an audit schedule for {plan_month}.

BRANCHES (total {len(branches)}):
{json.dumps(branches, indent=2)}

AUDITORS (total {len(auditors)}):
{json.dumps(auditors, indent=2)}

CAPACITY:
- Required audit days: {req_days}
- Available auditor days: {avail_days}
- Each auditor capacity: {WORKING_DAYS_PER_MONTH} days

RULES:
1. Assign branches based on risk_score (higher risk gets better auditors)
2. Don't exceed any auditor's capacity
3. Prioritize: CRITICAL > HIGH > MODERATE > LOW risk
4. Use audit_days as the duration for each branch
5. For each scheduled audit, you MUST calculate and provide a "StartDate" and an "EndDate" (format: YYYY-MM-DD).
6. The first audit for any auditor must start on the first working day (Monday to Friday) of {plan_month}.
7. An audit runs for exactly "audit_days" working days (skipping Saturdays and Sundays). An auditor's next audit must start on the next working day after their previous audit's "EndDate".

OUTPUT FORMAT (JSON only):
{{
  "schedule": [
    {{
      "auditor_name": "Rajesh",
      "branch_name": "Delhi Main",
      "branch_id": "B001",
      "risk_score": 450,
      "risk_grade": "HIGH",
      "audit_days": 6,
      "priority": 1,
      "StartDate": "2026-06-01",
      "EndDate": "2026-06-08"
    }}
  ],
  "unscheduled": [
    {{
      "branch_name": "Branch X",
      "reason": "No capacity available"
    }}
  ]
}}

Generate schedule now (JSON only, no other text):
"""
    
    def print_plan(self, result: Dict):
        """Pretty print the plan."""
        if "error" in result:
            print(f"\n❌ ERROR: {result['error']}")
            return
        
        print("\n" + "="*60)
        print(f"AUDIT PLAN - {result['summary']['plan_month']}")
        print("="*60)
        
        print(f"\n📊 SUMMARY:")
        for key, value in result['summary'].items():
            print(f"   {key}: {value}")
        
        print(f"\n📋 SCHEDULE:")
        for item in result.get('schedule', []):
            print(f"   👤 {item['auditor_name']:15} → {item['branch_name']:20} "
                  f"(Risk: {item['risk_score']}, Days: {item['audit_days']})")
        
        if result.get('unscheduled'):
            print(f"\n⚠️ UNSCHEDULED BRANCHES:")
            for item in result['unscheduled']:
                print(f"   • {item['branch_name']}: {item['reason']}")


# ============================================================================
# QUICK TEST
# ============================================================================

if __name__ == "__main__":
    # Minimal input data
    branches = [
        {"branch_id": "B001", "branch_name": "Delhi Main", "risk_score": 750},
        {"branch_id": "B002", "branch_name": "Mumbai Central", "risk_score": 450},
        {"branch_id": "B003", "branch_name": "Bangalore North", "risk_score": 320},
        {"branch_id": "B004", "branch_name": "Chennai South", "risk_score": 180},
        {"branch_id": "B005", "branch_name": "Kolkata East", "risk_score": 520},
        {"branch_id": "B006", "branch_name": "Hyderabad West", "risk_score": 280},
    ]
    
    auditors = [
        {"auditor_id": "A001", "auditor_name": "Rajesh Kumar", "performance_rating": 4.8},
        {"auditor_id": "A002", "auditor_name": "Priya Singh", "performance_rating": 4.5},
        {"auditor_id": "A003", "auditor_name": "Amit Verma", "performance_rating": 4.2},
    ]
    
    # Make sure you have GROQ_API_KEY in environment or pass directly
    try:
        planner = AuditPlanner()  # Will read GROQ_API_KEY from env
        result = planner.generate_plan(branches, auditors, "2026-07")
        planner.print_plan(result)
        
        # Optional: Get JSON output
        print("\n" + "="*60)
        print("RAW JSON OUTPUT:")
        print("="*60)
        print(json.dumps(result, indent=2))
        
    except ValueError as e:
        print(f"\n❌ Error: {e}")
        print("Please set GROQ_API_KEY in your environment or pass it to AuditPlanner")