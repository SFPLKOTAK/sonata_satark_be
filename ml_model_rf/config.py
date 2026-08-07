import os
from pathlib import Path

# Base Directory Paths
BASE_DIR = Path(__file__).resolve().parent
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_FILE_PATH = ARTIFACTS_DIR / "audit_risk_model.joblib"
CLASSIFIER_FILE_PATH = ARTIFACTS_DIR / "audit_grade_classifier.joblib"
LABEL_ENCODER_PATH = ARTIFACTS_DIR / "grade_label_encoder.joblib"
CATEGORICAL_ENCODER_PATH = ARTIFACTS_DIR / "categorical_encoder.joblib"
METRICS_FILE_PATH = ARTIFACTS_DIR / "latest_training_metrics.json"

# Feature Column Definitions
FEATURE_COLS = [
    # Categorical Regional Hierarchy
    'Zone',
    'Division',
    'Region',

    # Size-Independent Ratios (%)
    'NPA_Rate_Pct',
    'Arrear_Rate_Pct',
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
    
    # Concentration Risks
    'TopCenter_NPAConc_Pct',
    'TopStaff_NPAConc_Pct',
    'RepeatBorrowerNPA',
    
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
    
    # Historical Previous Audit Score (Lag 1)
    'Prev_Score',

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

def score_to_grade(score: float) -> str:
    """Converts continuous audit score (0-100) into categorical grade (A, B, C, D)."""
    if score is None or str(score) == 'nan':
        return 'N/A'
    for min_score, grade in GRADE_THRESHOLDS:
        if score >= min_score:
            return grade
    return 'D'


