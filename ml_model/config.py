import os
from pathlib import Path

# Base Directory Paths
BASE_DIR = Path(__file__).resolve().parent
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_FILE_PATH = ARTIFACTS_DIR / "audit_risk_model.joblib"
CLASSIFIER_FILE_PATH = ARTIFACTS_DIR / "audit_grade_classifier.joblib"
LABEL_ENCODER_PATH = ARTIFACTS_DIR / "grade_label_encoder.joblib"
METRICS_FILE_PATH = ARTIFACTS_DIR / "latest_training_metrics.json"

# Feature Column Definitions
FEATURE_COLS = [
    # Categorical Regional Hierarchy
    'Zone',
    'Division',
    'Region',

    # Historical Autoregressive Score
    'Prev_Score',

    # Size-Independent Ratios (%)
    'NPA_Rate_Pct',
    'Arrear_Rate_Pct',
    'PAR_1_30_Rate_Pct',
    'PAR_31_60_Rate_Pct',
    'PAR_61_90_Rate_Pct',
    'WriteOff_Rate_Pct',
    'GoodLoan_Rate_Pct',
    'NewDefault_Rate_Pct',
    'Deceased_Rate_Pct',

    
    # Portfolio Velocity Trends
    'NPA_Amt_Change_Pct',
    'Arrear_Amt_Change_Pct',
    
    # Operations & Collections
    'CollectionRate_Pct',
    'AvgDaysSinceCollection',
    'AvgArrearDays',
    
    # Concentration & Staff Load/Tenure Risks
    'TopCenter_NPAConc_Pct',
    'TopStaff_NPAConc_Pct',
    'RepeatBorrowerNPA',
    'Staff_Caseload_Ratio',
    'ActiveStaffCount',
    'Staff_Overstay_12M_Pct',
    'Staff_Tenure_Under3M_Pct',
    'Avg_Center_Size',
    'ActiveCenterCount',



    
    # SQL SP Sub-Scores
    'Score_NPARate',
    'Score_PAR0Rate',
    'Score_WriteOffRate',
    'Score_BucketDist',
    'Score_NPADrift',
    'Score_ArrearVelocity',
    'Score_WriteOffGrowth',
    'Score_NewDefaults',
    'Score_CollectionGap',
    'Score_CollectionRecency',
    'Score_MissedInst',
    'Score_GoodLoanInverse',
    'Score_DeceasedRate',
    'Score_RepeatBorrowerNPA',
    'Score_CenterConc',
    'Score_StaffConc',
    'Score_DAWriteOff',
    'SubScore_PortfolioQuality',
    'SubScore_TrendVelocity',
    'SubScore_CollectionEfficiency',
    'SubScore_CustomerRisk',
    'SubScore_ConcentrationRisk',

    # Absolute Scale Metrics
    'TotalLoans',
    'TotalPrincipalOS'
]


# Grade Threshold Rules (A >= 70, B: 60-69, C: 50-59, D < 50)
GRADE_THRESHOLDS = [
    (70, 'A'),
    (60, 'B'),
    (50, 'C'),
    (0,  'D')
]

def score_to_grade(score: float, thresholds: tuple = None) -> str:
    """Converts continuous audit score (0-100) into categorical grade (A, B, C, D)."""
    if score is None or str(score) == 'nan':
        return 'N/A'
    if thresholds is not None and len(thresholds) == 3:
        t_A, t_B, t_C = thresholds
        if score >= t_A:
            return 'A'
        elif score >= t_B:
            return 'B'
        elif score >= t_C:
            return 'C'
        else:
            return 'D'
    
    for min_score, grade in GRADE_THRESHOLDS:
        if score >= min_score:
            return grade
    return 'D'


def optimize_grade_thresholds(y_true_scores, y_pred_scores) -> tuple:
    """
    Optimizes (t_A, t_B, t_C) decision boundaries using Nelder-Mead optimization
    to maximize exact 4-grade match accuracy on the validation set.
    """
    from scipy.optimize import minimize
    
    true_grades = [score_to_grade(s) for s in y_true_scores]
    
    def loss_func(thresholds):
        t_A, t_B, t_C = thresholds
        if t_A <= t_B or t_B <= t_C or t_A > 95 or t_C < 20:
            return 100.0
        pred_grades = [score_to_grade(s, thresholds=(t_A, t_B, t_C)) for s in y_pred_scores]
        acc = np.mean([1.0 if p == t else 0.0 for p, t in zip(pred_grades, true_grades)])
        return -acc

    init_thresholds = [70.0, 60.0, 50.0]
    try:
        res = minimize(loss_func, init_thresholds, method='Nelder-Mead', options={'maxiter': 500})
        t_A, t_B, t_C = res.x
        return (round(float(t_A), 2), round(float(t_B), 2), round(float(t_C), 2))
    except Exception:
        return (70.0, 60.0, 50.0)



