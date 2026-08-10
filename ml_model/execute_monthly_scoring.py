import os
import sys
from datetime import datetime

# Adjust sys.path to support execution from any directory
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
satark_dir = os.path.join(base_dir, 'satark')
for path in [base_dir, satark_dir]:
    if path not in sys.path:
        sys.path.insert(0, path)

from ml_model.run_monthly_batch_prediction import run_monthly_batch_inference

# ===============================================================================
# 🗓️ TARGET MONTH PLACEHOLDER
# Set target snapshot date here for single-click execution (Format: 'YYYY-MM-DD')
# Example: TARGET_DATE = '2026-08-01'
# ===============================================================================
TARGET_DATE = '2026-08-01'


def main():
    print("=" * 80)
    print("🚀 [SONATA SATARK] DYNAMIC MONTHLY BRANCH RISK SCORING RUNNER")
    print("=" * 80)

    # 1. Determine Target Date (CLI Argument -> TARGET_DATE Placeholder -> Current Month Default)
    if len(sys.argv) > 1 and sys.argv[1].strip():
        target_date = sys.argv[1].strip()
    elif TARGET_DATE and TARGET_DATE.strip():
        target_date = TARGET_DATE.strip()
    else:
        target_date = datetime.now().strftime('%Y-%m-01')

    print(f"  🎯 Executing risk scoring for snapshot date: '{target_date}'...")

    # 2. Execute Batch Inference
    try:
        summary = run_monthly_batch_inference(as_on_date=target_date)
        print("\n" + "=" * 80)
        print(f"✅ [SUCCESS] Batch Scoring Completed Successfully for Date: {summary['as_on_date']}")
        print(f"   - Total Branches Scored : {summary['total_branches_scored']}")
        print(f"   - High Risk Branches    : {summary['high_risk_branches']} ({summary['high_risk_pct']}%)")
        print(f"   - Normal Risk Branches  : {summary['normal_risk_branches']}")
        print("=" * 80 + "\n")
    except Exception as e:
        import traceback
        print(f"\n❌ [ERROR] Monthly scoring failed for date '{target_date}': {e}")
        traceback.print_exc()

if __name__ == '__main__':
    main()
