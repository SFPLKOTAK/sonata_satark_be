import pandas as pd
from ml_model_rf.train import train_model
from ml_model_rf.predict import predict_branch_audit_score

def test_pipeline():
    print("Generating sample dataset for pipeline verification...")
    
    # Create sample training data with 3 snapshot dates across 5 branches
    sample_data = []
    dates = ['2026-04-01', '2026-05-01', '2026-07-01']
    
    for branch_id in range(1, 10):
        for date_str in dates:
            npa_amt = 500000 + branch_id * 100000
            principal = 80000000
            score = max(35, min(95, 90 - (npa_amt / 100000) * 4))
            grade = 'A' if score >= 80 else ('B' if score >= 60 else ('C' if score >= 50 else 'D'))
            
            sample_data.append({
                'Branch_ID': branch_id,
                'BranchName': f'Branch_{branch_id}',
                'AsOnDate': date_str,
                'Grade': grade,
                'Score': score,
                'TotalLoans': 2000 + branch_id * 50,
                'TotalPrincipalOS': principal,
                'Cur_NPA_Amt': npa_amt,
                'Cur_ArrearAmt': 25000,
                'WriteOffCount': 50,
                'GoodLoanCount': 1600,
                'DeceasedCount': 4,
                'NewDefaultsThisMonth': 10 + branch_id,
                'NPA_Amt_Change_Pct': -5.0,
                'Arrear_Amt_Change_Pct': 10.0,
                'CollectionRate_Pct': 98.0,
                'AvgDaysSinceCollection': 15,
                'AvgArrearDays': 45,
                'TopCenter_NPAConc_Pct': 8.5,
                'TopStaff_NPAConc_Pct': 35.0 + branch_id,
                'RepeatBorrowerNPA': 150
            })
            
    df_sample = pd.DataFrame(sample_data)
    
    print("Testing train_model()...")
    metrics = train_model(data_source_df=df_sample)
    print("Train Metrics:", metrics)
    
    print("\nTesting predict_branch_audit_score()...")
    sample_branch = {
        'TotalLoans': 2351,
        'TotalPrincipalOS': 79107300,
        'Cur_NPA_Amt': 540394,
        'Cur_ArrearAmt': 25366,
        'WriteOffCount': 669,
        'GoodLoanCount': 1649,
        'DeceasedCount': 5,
        'NewDefaultsThisMonth': 17,
        'NPA_Amt_Change_Pct': -72.47,
        'Arrear_Amt_Change_Pct': 278.6,
        'CollectionRate_Pct': 98.5,
        'AvgDaysSinceCollection': 15,
        'AvgArrearDays': 45,
        'TopCenter_NPAConc_Pct': 8.71,
        'TopStaff_NPAConc_Pct': 50.81,
        'RepeatBorrowerNPA': 221
    }
    
    result = predict_branch_audit_score(sample_branch)
    print("Inference Result:", result)
    print("\nPIPELINE VERIFICATION SUCCESSFUL!")

if __name__ == '__main__':
    test_pipeline()
