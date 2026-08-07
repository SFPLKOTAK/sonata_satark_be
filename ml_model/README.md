# Sonata Satark - Branch Audit Risk ML Model

Predicting **Branch Audit Scores (0–100)** and **Audit Grades (A, B, C, D)** using SQL portfolio risk metrics and historical audit results.

---

## 📁 Directory Architecture

```
ml_model/
├── __init__.py               # Package exports
├── config.py                 # Feature definitions, grade cutoffs, paths
├── data_loader.py            # CSV / Django SQL database loader with OUTER APPLY
├── feature_engineering.py    # Size-independent ratio calculations & transformations
├── train.py                  # Model training pipeline & metric evaluation
├── predict.py                # Inference function for predicting scores/grades
├── requirements_ml.txt       # ML Python dependencies
└── artifacts/                # Saved trained model files & evaluation metrics
    ├── audit_risk_model.joblib
    └── latest_training_metrics.json
```

---

## 🚀 Quickstart Guide

### 1. Install ML Dependencies
```bash
pip install -r ml_model/requirements_ml.txt
```

### 2. Train Model from CSV Dataset
If you exported data from SQL stored procedure into a CSV file:
```bash
python -m ml_model.train path/to/your_training_data.csv
```

### 3. Programmatic Usage in Python / Django Views

```python
from ml_model import predict_branch_audit_score

# Input portfolio metrics for a branch
branch_data = {
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

# Run prediction
result = predict_branch_audit_score(branch_data)

print(result)
# Output:
# {
#    'predicted_score': 47.85,
#    'predicted_grade': 'D',
#    'risk_level': 'HIGH',
#    'warnings': ['High Staff Concentration Risk (50.8%)', 'Spike in Arrear Growth (+278.6%)']
# }
```
