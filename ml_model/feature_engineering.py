import pandas as pd
import numpy as np
from typing import Tuple, List
from .config import FEATURE_COLS

def transform_features(df: pd.DataFrame, is_training: bool = True) -> pd.DataFrame:
    """
    Transforms raw portfolio metrics into size-independent ratios and velocity features.
    Encodes categorical features like Zone, Division, Region as category dtypes for XGBoost.
    """
    if is_training:
        print("  [FEATURE ENGINEERING] Calculating size-independent ratios & encoding categorical features...")

    df = df.copy()

    # 1. Categorical Hierarchy Features
    cat_cols = ['Zone', 'Division', 'Region']
    for cat in cat_cols:
        if cat in df.columns:
            df[cat] = df[cat].fillna('Unknown').astype('category')
        else:
            df[cat] = pd.Series(['Unknown'] * len(df), dtype='category')

    # 2. Calculate Size-Independent Ratios (%)
    principal_os = df['TotalPrincipalOS'].replace(0, np.nan) if 'TotalPrincipalOS' in df.columns else 1
    total_loans = df['TotalLoans'].replace(0, np.nan) if 'TotalLoans' in df.columns else 1

    df['NPA_Rate_Pct'] = (df['Cur_NPA_Amt'] * 100.0 / principal_os).fillna(0)
    df['Arrear_Rate_Pct'] = (df['Cur_ArrearAmt'] * 100.0 / principal_os).fillna(0)
    df['WriteOff_Rate_Pct'] = (df['WriteOffCount'] * 100.0 / total_loans).fillna(0)
    df['GoodLoan_Rate_Pct'] = (df['GoodLoanCount'] * 100.0 / total_loans).fillna(0)
    df['NewDefault_Rate_Pct'] = (df['NewDefaultsThisMonth'] * 100.0 / total_loans).fillna(0)
    df['Deceased_Rate_Pct'] = (df['DeceasedCount'] * 100.0 / total_loans).fillna(0)

    # 3. Historical Previous Audit Score (Lag 1 per Branch)
    if 'Branch_ID' in df.columns and 'Score' in df.columns:
        df['Prev_Score'] = df.groupby('Branch_ID')['Score'].shift(1)
        df['Prev_Score'] = df['Prev_Score'].fillna(df['Score'])
    else:
        df['Prev_Score'] = 50.0

    # 4. Fill missing default values for numerical sub-scores and metrics
    fill_defaults = {
        'NPA_Amt_Change_Pct': 0.0,
        'Arrear_Amt_Change_Pct': 0.0,
        'CollectionRate_Pct': 100.0,
        'AvgDaysSinceCollection': 0.0,
        'AvgArrearDays': 0.0,
        'TopCenter_NPAConc_Pct': 0.0,
        'TopStaff_NPAConc_Pct': 0.0,
        'RepeatBorrowerNPA': 0,
        'TotalLoans': 0,
        'TotalPrincipalOS': 0.0,
        'Score_NPARate': 0,
        'Score_PAR0Rate': 0,
        'Score_WriteOffRate': 0,
        'Score_BucketDist': 0,
        'Score_NPADrift': 0,
        'Score_ArrearVelocity': 0,
        'Score_WriteOffGrowth': 0,
        'Score_NewDefaults': 0,
        'Score_CollectionGap': 0,
        'Score_CollectionRecency': 0,
        'Score_MissedInst': 0,
        'Score_GoodLoanInverse': 0,
        'Score_DeceasedRate': 0,
        'Score_RepeatBorrowerNPA': 0,
        'Score_CenterConc': 0,
        'Score_StaffConc': 0,
        'Score_DAWriteOff': 0,
        'SubScore_PortfolioQuality': 0,
        'SubScore_TrendVelocity': 0,
        'SubScore_CollectionEfficiency': 0,
        'SubScore_CustomerRisk': 0,
        'SubScore_ConcentrationRisk': 0
    }
    
    for col, default_val in fill_defaults.items():
        if col in df.columns:
            df[col] = df[col].fillna(default_val)
        else:
            df[col] = default_val

    # 5. Handle infinity values for numerical columns
    num_cols = [c for c in FEATURE_COLS if c not in cat_cols]
    df[num_cols] = df[num_cols].replace([np.inf, -np.inf], 0.0)

    if is_training:
        print(f"  [FEATURE ENGINEERING] Successfully transformed {len(FEATURE_COLS)} features across {len(df)} rows.")

    return df


def prepare_training_dataset(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.DataFrame]:
    """
    Prepares X (features), y_score (regressor target), y_grade (classifier target) from training dataframe.
    """
    df_transformed = transform_features(df, is_training=True)

    if 'Score' not in df_transformed.columns:
        raise ValueError("Dataframe must contain 'Score' column for training target.")

    df_clean = df_transformed.dropna(subset=['Score']).copy()
    
    X = df_clean[FEATURE_COLS]
    y_score = df_clean['Score']
    y_grade = df_clean['Grade'] if 'Grade' in df_clean.columns else df_clean['Score'].apply(lambda s: 'A' if s>=80 else ('B' if s>=60 else ('C' if s>=50 else 'D')))

    print(f"  [DATASET PREP] Target variables prepared | Score Range: [{y_score.min():.1f} to {y_score.max():.1f}] | Grade Distribution: {dict(y_grade.value_counts())}")
    
    return X, y_score, y_grade, df_clean



