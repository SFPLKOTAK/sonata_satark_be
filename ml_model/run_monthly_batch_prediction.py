import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, List

# Adjust sys.path to support execution from any working directory
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
satark_dir = os.path.join(base_dir, 'satark')
for path in [base_dir, satark_dir]:
    if path not in sys.path:
        sys.path.insert(0, path)

from ml_model.predict import predict_branch_audit_score
from ml_model.config import FEATURE_COLS

def generate_risk_key_points(row: pd.Series, warnings: List[str]) -> str:
    """
    Generates a clear, comma-separated list of key risk factors impacting the branch's audit score.
    """
    key_points = []
    
    # 1. PAR & Credit Risk Factors
    par1_30 = float(row.get('PAR_1_30_Rate_Pct', 0.0))
    if par1_30 > 3.0:
        key_points.append(f"High PAR 1-30 Days Bucket ({par1_30:.1f}%)")
    
    arrear_rate = float(row.get('Arrear_Rate_Pct', 0.0))
    if arrear_rate > 5.0:
        key_points.append(f"Elevated Arrear Rate ({arrear_rate:.1f}%)")
        
    npa_rate = float(row.get('NPA_Rate_Pct', 0.0))
    if npa_rate > 2.5:
        key_points.append(f"High NPA Portfolio Rate ({npa_rate:.1f}%)")

    new_defaults = int(row.get('NewDefaultsThisMonth', 0))
    if new_defaults > 5:
        key_points.append(f"Surge in New Defaults ({new_defaults} loans this month)")

    # 2. Staff Operations & Tenure Factors
    caseload = float(row.get('Staff_Caseload_Ratio', 0.0))
    if caseload > 350.0:
        key_points.append(f"High Staff Caseload Burden ({caseload:.0f} loans/staff)")

    overstay = float(row.get('Staff_Overstay_12M_Pct', 0.0))
    if overstay > 30.0:
        key_points.append(f"Staff Overstay Risk ({overstay:.1f}% staff > 12M at branch)")

    new_staff = float(row.get('Staff_Tenure_Under3M_Pct', 0.0))
    if new_staff > 40.0:
        key_points.append(f"Inexperienced Staff Inflow ({new_staff:.1f}% staff < 3M tenure)")

    # 3. Center Discipline Factors
    center_size = float(row.get('Avg_Center_Size', 0.0))
    if 0 < center_size < 6.0:
        key_points.append(f"Failing JLG Center Size ({center_size:.1f} borrowers/center)")

    coll_rate = float(row.get('CollectionRate_Pct', 100.0))
    if coll_rate < 92.0:
        key_points.append(f"Collection Efficiency Drop ({coll_rate:.1f}%)")

    # Combine with prediction warnings
    for w in warnings:
        if w not in key_points:
            key_points.append(w)

    return ", ".join(key_points) if key_points else "Satisfactory Operational Control"


def run_monthly_batch_inference(as_on_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Executes automated monthly batch scoring across all active branches.
    Reads staging data from: ML_TBL_Monthly_Branch_Feature_Staging
    Stores results into:
      1. Active Predictions Table: ML_TBL_Monthly_Branch_Risk_Predictions
      2. Historical Tracking Table: ML_TBL_Branch_Risk_Prediction_History
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
    df_staging = pd.DataFrame()
    
    # Primary: Read directly from ML_TBL_Monthly_Branch_Feature_Staging
    try:
        query_staging = f"SELECT * FROM ML_TBL_Monthly_Branch_Feature_Staging WHERE AsOnDate = '{as_on_date}'"
        df_staging = pd.read_sql(query_staging, connection)
    except Exception as e:
        print(f"  ⚠️ Staging query error: {e}")
        df_staging = pd.DataFrame()

    # Fallback to training table if staging is empty
    if len(df_staging) == 0:
        print(f"  ℹ️ Reading from table 'audit_branch_parameter_grade_training_data'...")
        try:
            query_train = f"SELECT * FROM audit_branch_parameter_grade_training_data WHERE AsOnDate = '{as_on_date}'"
            df_staging = pd.read_sql(query_train, connection)
        except Exception:
            df_staging = pd.DataFrame()

    # Final Fallback to latest available date
    if len(df_staging) == 0:
        print(f"  ⚠️  Attempting fallback to latest available snapshot date...")
        query_latest = "SELECT * FROM audit_branch_parameter_grade_training_data WHERE AsOnDate = (SELECT MAX(AsOnDate) FROM audit_branch_parameter_grade_training_data)"
        df_staging = pd.read_sql(query_latest, connection)
        if len(df_staging) > 0:
            as_on_date = pd.to_datetime(df_staging['AsOnDate'].iloc[0]).strftime('%Y-%m-%d')
            print(f"  🔄 [FALLBACK SUCCESS] Using latest date: '{as_on_date}' ({len(df_staging)} branches)")
        else:
            raise ValueError("No staging records available in database for scoring.")

    print(f"  ✅ [DATA LOADED] Loaded {len(df_staging)} active branch records for batch scoring.")

    # Standardize column mapping (BRANCHID -> Branch_ID)
    if 'BRANCHID' in df_staging.columns and 'Branch_ID' not in df_staging.columns:
        df_staging['Branch_ID'] = df_staging['BRANCHID']

    # Fetch Prev_Score directly from audit_branch_grade_history_final in Python
    print(f"  🔗 [PREV SCORE ENRICHMENT] Fetching previous audit scores from 'audit_branch_grade_history_final'...")
    try:
        query_prev = f"""
        WITH PriorScores AS (
            SELECT 
                Branch_ID, 
                Score AS Prev_Score_Fetched,
                ROW_NUMBER() OVER (PARTITION BY Branch_ID ORDER BY Month DESC) AS rnk
            FROM audit_branch_grade_history_final
            WHERE Month < '{as_on_date}'
        )
        SELECT Branch_ID, Prev_Score_Fetched
        FROM PriorScores
        WHERE rnk = 1
        """
        df_prev = pd.read_sql(query_prev, connection)
        if len(df_prev) > 0:
            df_staging['Branch_ID'] = df_staging['Branch_ID'].astype(int)
            df_prev['Branch_ID'] = df_prev['Branch_ID'].astype(int)
            df_staging = df_staging.merge(df_prev, on='Branch_ID', how='left')
            df_staging['Prev_Score'] = df_staging['Prev_Score_Fetched'].fillna(70.0)
            df_staging.drop(columns=['Prev_Score_Fetched'], inplace=True, errors='ignore')
            print(f"  ✅ [PREV SCORE ENRICHED] Successfully attached historical Prev_Score for branches.")
    except Exception as e:
        print(f"  ⚠️ Notice: Could not query 'audit_branch_grade_history_final' directly ({e}). Using default baseline.")

    # 4. Perform Batch Scoring via Predict API
    print(f"  🧠 [STEP 2/3] Executing Stacking Ensemble Scoring...")
    batch_results = predict_branch_audit_score(df_staging)
    predictions = batch_results['predictions']

    df_scored = df_staging.copy()
    df_scored['Predicted_Score'] = [p['predicted_score'] for p in predictions]
    df_scored['Predicted_Grade_From_Score'] = [p['predicted_grade_from_score'] for p in predictions]
    df_scored['Predicted_Grade_Direct_Classifier'] = [p['predicted_grade_direct_classifier'] for p in predictions]
    df_scored['Final_Recommended_Grade'] = [p['final_recommended_grade'] for p in predictions]
    df_scored['Risk_Level'] = [p['risk_level'] for p in predictions]
    df_scored['Risk_Warnings'] = [json.dumps(p['warnings']) if p['warnings'] else "[]" for p in predictions]
    df_scored['Key_points_impacting_risk'] = [generate_risk_key_points(row, p['warnings']) for row, p in zip(df_staging.to_dict('records'), predictions)]

    # Count Risk Levels
    high_risk_count = sum(1 for p in predictions if p['risk_level'] == 'HIGH')
    normal_risk_count = len(predictions) - high_risk_count

    # 5. Persist Predictions to Database
    print(f"  💾 [STEP 3/3] Saving Predictions to Active & Historical Tables...")
    cursor = connection.cursor()

    # Pre-scoring Cleanup: Remove existing predictions for target month if present
    print(f"  🗑️ [CLEANUP] Checking if prediction records already exist for AsOnDate = '{as_on_date}'...")
    try:
        cursor.execute(f"SELECT COUNT(*) FROM dbo.ML_TBL_Monthly_Branch_Risk_Predictions WHERE AsOnDate = '{as_on_date}'")
        active_cnt = cursor.fetchone()[0]
        if active_cnt > 0:
            cursor.execute(f"DELETE FROM dbo.ML_TBL_Monthly_Branch_Risk_Predictions WHERE AsOnDate = '{as_on_date}'")
            print(f"  🔥 [CLEANUP ACTIVE TABLE] Found {active_cnt} existing records for '{as_on_date}'. Successfully deleted old predictions.")
        else:
            print(f"  ℹ️ [CLEANUP ACTIVE TABLE] No existing active prediction records found for '{as_on_date}'.")

        cursor.execute(f"SELECT COUNT(*) FROM dbo.ML_TBL_Branch_Risk_Prediction_History WHERE AsOnDate = '{as_on_date}'")
        history_cnt = cursor.fetchone()[0]
        if history_cnt > 0:
            cursor.execute(f"DELETE FROM dbo.ML_TBL_Branch_Risk_Prediction_History WHERE AsOnDate = '{as_on_date}'")
            print(f"  🔥 [CLEANUP HISTORY TABLE] Found {history_cnt} existing records for '{as_on_date}'. Successfully deleted old historical records.")
        else:
            print(f"  ℹ️ [CLEANUP HISTORY TABLE] No existing historical prediction records found for '{as_on_date}'.")
    except Exception as e:
        print(f"  ⚠️ Pre-scoring cleanup notice: {e}")

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
        key_points = str(row['Key_points_impacting_risk']).replace("'", "''")

        # A. Upsert Active Predictions Table (dbo.ML_TBL_Monthly_Branch_Risk_Predictions)
        try:
            sql_active = f"""
            IF EXISTS (SELECT 1 FROM dbo.ML_TBL_Monthly_Branch_Risk_Predictions WHERE Branch_ID = {branch_id})
            BEGIN
                UPDATE dbo.ML_TBL_Monthly_Branch_Risk_Predictions
                SET BranchName = '{branch_name}', Zone = '{zone}', Division = '{division}', Region = '{region}',
                    AsOnDate = '{as_on_date}', Predicted_Score = {pred_score},
                    Predicted_Grade_From_Score = '{pred_grade_score}', Predicted_Grade_Direct_Classifier = '{pred_grade_clf}',
                    Final_Recommended_Grade = '{final_grade}', Risk_Level = '{risk_level}', Risk_Warnings = '{warnings_str}',
                    Key_points_impacting_risk = '{key_points}',
                    Model_Version = 'StackingEnsemble_v2.0', ScoredAt = GETDATE()
                WHERE Branch_ID = {branch_id};
            END
            ELSE
            BEGIN
                INSERT INTO dbo.ML_TBL_Monthly_Branch_Risk_Predictions 
                (Branch_ID, BranchName, Zone, Division, Region, AsOnDate, Predicted_Score, Predicted_Grade_From_Score, Predicted_Grade_Direct_Classifier, Final_Recommended_Grade, Risk_Level, Risk_Warnings, Key_points_impacting_risk, Model_Version, ScoredAt)
                VALUES ({branch_id}, '{branch_name}', '{zone}', '{division}', '{region}', '{as_on_date}', {pred_score}, '{pred_grade_score}', '{pred_grade_clf}', '{final_grade}', '{risk_level}', '{warnings_str}', '{key_points}', 'StackingEnsemble_v2.0', GETDATE());
            END
            """
            cursor.execute(sql_active)
        except Exception as e:
            print(f"  ⚠️ Error updating active table for branch {branch_id}: {e}")

        # B. Upsert Historical Archive Table (dbo.ML_TBL_Branch_Risk_Prediction_History)
        try:
            sql_history = f"""
            IF NOT EXISTS (SELECT 1 FROM dbo.ML_TBL_Branch_Risk_Prediction_History WHERE AsOnDate = '{as_on_date}' AND Branch_ID = {branch_id})
            BEGIN
                INSERT INTO dbo.ML_TBL_Branch_Risk_Prediction_History 
                (Branch_ID, BranchName, Zone, Division, Region, AsOnDate, Predicted_Score, Predicted_Grade_From_Score, Predicted_Grade_Direct_Classifier, Final_Recommended_Grade, Risk_Level, Risk_Warnings, Key_points_impacting_risk, Model_Version, ScoredAt)
                VALUES ({branch_id}, '{branch_name}', '{zone}', '{division}', '{region}', '{as_on_date}', {pred_score}, '{pred_grade_score}', '{pred_grade_clf}', '{final_grade}', '{risk_level}', '{warnings_str}', '{key_points}', 'StackingEnsemble_v2.0', GETDATE());
            END
            """
            cursor.execute(sql_history)
        except Exception as e:
            print(f"  ⚠️ Error updating history table for branch {branch_id}: {e}")

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
