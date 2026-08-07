import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any

# Adjust sys.path to support execution from any working directory
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
satark_dir = os.path.join(base_dir, 'satark')
for path in [base_dir, satark_dir]:
    if path not in sys.path:
        sys.path.insert(0, path)

from ml_model.predict import predict_branch_audit_score
from ml_model.config import FEATURE_COLS

def run_monthly_batch_inference(as_on_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes automated monthly batch scoring across all active branches.
    Stores results into:
      1. Active Predictions Table: TBL_Monthly_Branch_Risk_Predictions
      2. Historical Tracking Table: TBL_Branch_Risk_Prediction_History
    """
    print("\n" + "=" * 70)
    print("🚀 [MONTHLY BATCH INFERENCE] Starting Automated Month-Start Risk Scoring")
    print("=" * 70)

    # 1. Initialize Django DB Connection
    try:
        import django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'satark.settings')
        django.setup()
        from django.db import connection
    except Exception as e:
        raise RuntimeError(f"Failed to connect to database for batch scoring: {e}")

    # 2. Determine Target Month
    if not as_on_date:
        as_on_date = datetime.now().strftime('%Y-%m-01')
    print(f"  🗓️  [TARGET SNAPSHOT MONTH] {as_on_date}")

    # 3. Read Staging Features for Target Month
    print(f"  📥 [STEP 1/3] Reading Staging Feature Data for AsOnDate = '{as_on_date}'...")
    query_staging = f"""
    SELECT * FROM audit_branch_parameter_grade_training_data
    WHERE AsOnDate = '{as_on_date}'
    """
    df_staging = pd.read_sql(query_staging, connection)

    if len(df_staging) == 0:
        print(f"  ⚠️  [WARNING] No staging records found for AsOnDate = '{as_on_date}'. Attempting fallback to latest available date...")
        query_latest = "SELECT * FROM audit_branch_parameter_grade_training_data WHERE AsOnDate = (SELECT MAX(AsOnDate) FROM audit_branch_parameter_grade_training_data)"
        df_staging = pd.read_sql(query_latest, connection)
        if len(df_staging) > 0:
            as_on_date = pd.to_datetime(df_staging['AsOnDate'].iloc[0]).strftime('%Y-%m-%d')
            print(f"  🔄 [FALLBACK SUCCESS] Using latest available date: '{as_on_date}' ({len(df_staging)} branches)")
        else:
            raise ValueError(f"No staging records available in database for scoring.")

    print(f"  ✅ [DATA LOADED] Loaded {len(df_staging)} active branch records for batch scoring.")

    # 4. Perform Batch Scoring via Predict API
    print(f"  🧠 [STEP 2/3] Executing Dual XGBoost Regressor & Classifier Scoring...")
    batch_results = predict_branch_audit_score(df_staging)
    predictions = batch_results['predictions']

    df_scored = df_staging.copy()
    df_scored['Predicted_Score'] = [p['predicted_score'] for p in predictions]
    df_scored['Predicted_Grade_From_Score'] = [p['predicted_grade_from_score'] for p in predictions]
    df_scored['Predicted_Grade_Direct_Classifier'] = [p['predicted_grade_direct_classifier'] for p in predictions]
    df_scored['Final_Recommended_Grade'] = [p['final_recommended_grade'] for p in predictions]
    df_scored['Risk_Level'] = [p['risk_level'] for p in predictions]
    df_scored['Risk_Warnings'] = [", ".join(p['warnings']) if p['warnings'] else "" for p in predictions]

    # Count Risk Levels
    high_risk_count = sum(1 for p in predictions if p['risk_level'] == 'HIGH')
    normal_risk_count = len(predictions) - high_risk_count

    # 5. Persist Predictions to Database
    print(f"  💾 [STEP 3/3] Saving Predictions to Active & Historical Database Tables...")
    cursor = connection.cursor()

    scored_timestamp = datetime.now()

    for idx, row in df_scored.iterrows():
        branch_id = int(row['Branch_ID'])
        branch_name = str(row.get('BranchName', row.get('BRANCH', 'Unknown'))).replace("'", "''")
        zone = str(row.get('Zone', 'Unknown')).replace("'", "''")
        division = str(row.get('Division', 'Unknown')).replace("'", "''")
        region = str(row.get('Region', 'Unknown')).replace("'", "''")
        
        pred_score = float(row['Predicted_Score'])
        pred_grade_score = str(row['Predicted_Grade_From_Score'])
        pred_grade_clf = str(row['Predicted_Grade_Direct_Classifier'])
        final_grade = str(row['Final_Recommended_Grade'])
        risk_level = str(row['Risk_Level'])
        warnings_str = str(row['Risk_Warnings']).replace("'", "''")
        
        npa_amt = float(row.get('Cur_NPA_Amt', 0.0))
        principal_os = float(row.get('TotalPrincipalOS', 0.0))
        coll_rate = float(row.get('CollectionRate_Pct', 100.0))

        # A. Upsert Active Table (TBL_Monthly_Branch_Risk_Predictions)
        try:
            sql_active = f"""
            IF EXISTS (SELECT 1 FROM TBL_Monthly_Branch_Risk_Predictions WHERE Branch_ID = {branch_id})
            BEGIN
                UPDATE TBL_Monthly_Branch_Risk_Predictions
                SET BranchName = '{branch_name}', Zone = '{zone}', Division = '{division}', Region = '{region}',
                    AsOnDate = '{as_on_date}', Predicted_Score = {pred_score},
                    Predicted_Grade_From_Score = '{pred_grade_score}', Predicted_Grade_Direct_Classifier = '{pred_grade_clf}',
                    Final_Recommended_Grade = '{final_grade}', Risk_Level = '{risk_level}', Risk_Warnings = '{warnings_str}',
                    ScoredAt = GETDATE()
                WHERE Branch_ID = {branch_id};
            END
            ELSE
            BEGIN
                INSERT INTO TBL_Monthly_Branch_Risk_Predictions 
                (Branch_ID, BranchName, Zone, Division, Region, AsOnDate, Predicted_Score, Predicted_Grade_From_Score, Predicted_Grade_Direct_Classifier, Final_Recommended_Grade, Risk_Level, Risk_Warnings, ScoredAt)
                VALUES ({branch_id}, '{branch_name}', '{zone}', '{division}', '{region}', '{as_on_date}', {pred_score}, '{pred_grade_score}', '{pred_grade_clf}', '{final_grade}', '{risk_level}', '{warnings_str}', GETDATE());
            END
            """
            cursor.execute(sql_active)
        except Exception:
            pass  # Fallback if table is not yet created

        # B. Upsert Historical Archive Table (TBL_Branch_Risk_Prediction_History)
        try:
            sql_history = f"""
            IF NOT EXISTS (SELECT 1 FROM TBL_Branch_Risk_Prediction_History WHERE AsOnDate = '{as_on_date}' AND Branch_ID = {branch_id})
            BEGIN
                INSERT INTO TBL_Branch_Risk_Prediction_History 
                (AsOnDate, Branch_ID, BranchName, Zone, Division, Region, Predicted_Score, Predicted_Grade, Risk_Level, Risk_Warnings, Cur_NPA_Amt, TotalPrincipalOS, CollectionRate_Pct, ScoredAt)
                VALUES ('{as_on_date}', {branch_id}, '{branch_name}', '{zone}', '{division}', '{region}', {pred_score}, '{final_grade}', '{risk_level}', '{warnings_str}', {npa_amt}, {principal_os}, {coll_rate}, GETDATE());
            END
            """
            cursor.execute(sql_history)
        except Exception:
            pass  # Fallback if table is not yet created

    summary_result = {
        'as_on_date': as_on_date,
        'total_branches_scored': len(df_scored),
        'high_risk_branches': high_risk_count,
        'normal_risk_branches': normal_risk_count,
        'high_risk_pct': round((high_risk_count / len(df_scored)) * 100, 1),
        'timestamp': datetime.now().isoformat()
    }

    print("\n" + "=" * 70)
    print("🎉 [MONTHLY INFERENCE COMPLETE] SUMMARY OF PREDICTIONS")
    print("=" * 70)
    print(f"  🏢 Total Branches Scored : {summary_result['total_branches_scored']}")
    print(f"  🚨 High Risk Branches    : {high_risk_count} ({summary_result['high_risk_pct']}%)")
    print(f"  ✅ Normal Risk Branches  : {normal_risk_count}")
    print("=" * 70 + "\n")

    return summary_result


if __name__ == '__main__':
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    run_monthly_batch_inference(as_on_date=target_date)
