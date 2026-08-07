import os
import joblib
import pandas as pd
import numpy as np
from typing import Dict, Any, Union

from .config import MODEL_FILE_PATH, CLASSIFIER_FILE_PATH, LABEL_ENCODER_PATH, FEATURE_COLS, score_to_grade
from .feature_engineering import transform_features

_MODEL_CACHE = None

def get_models():
    """
    Loads and caches both Regressor and Classifier models.
    """
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        print(f"  [PREDICT SERVICE] Loading model artifacts into memory...")
        if not os.path.exists(MODEL_FILE_PATH) or not os.path.exists(CLASSIFIER_FILE_PATH):
            raise FileNotFoundError("Trained model artifacts not found. Please run `train_model()` first.")
        
        regressor = joblib.load(MODEL_FILE_PATH)
        classifier = joblib.load(CLASSIFIER_FILE_PATH)
        label_encoder = joblib.load(LABEL_ENCODER_PATH)
        
        _MODEL_CACHE = (regressor, classifier, label_encoder)
        print("  [PREDICT SERVICE] Models loaded into memory successfully.")
    return _MODEL_CACHE


def predict_branch_audit_score(branch_data: Union[Dict[str, Any], pd.DataFrame]) -> Dict[str, Any]:
    """
    Predicts Audit Score and Audit Grade for a branch given its portfolio risk metrics.
    """
    print("\n[PREDICT SERVICE] Received Prediction Request...")
    regressor, classifier, label_encoder = get_models()

    if isinstance(branch_data, dict):
        df_input = pd.DataFrame([branch_data])
    else:
        df_input = branch_data.copy()

    df_transformed = transform_features(df_input, is_training=False)
    X = df_transformed[FEATURE_COLS]

    # Regressor score prediction
    raw_scores = regressor.predict(X)
    clipped_scores = np.clip(raw_scores, 0, 100)

    # Classifier grade prediction
    classifier_grade_indices = classifier.predict(X)
    classifier_grades = label_encoder.inverse_transform(classifier_grade_indices)

    results = []
    for idx, score in enumerate(clipped_scores):
        score_val = round(float(score), 2)
        regressor_grade = score_to_grade(score_val)
        direct_classifier_grade = classifier_grades[idx]

        warnings = []
        row_dict = df_transformed.iloc[idx].to_dict()
        
        if row_dict.get('NPA_Rate_Pct', 0) > 5.0:
            warnings.append(f"High NPA Rate ({row_dict['NPA_Rate_Pct']:.1f}%)")
        if row_dict.get('TopStaff_NPAConc_Pct', 0) > 40.0:
            warnings.append(f"High Staff Concentration Risk ({row_dict['TopStaff_NPAConc_Pct']:.1f}%)")
        if row_dict.get('Arrear_Amt_Change_Pct', 0) > 100.0:
            warnings.append(f"Spike in Arrear Growth (+{row_dict['Arrear_Amt_Change_Pct']:.1f}%)")

        print(f"  [PREDICTION RESULT] Regressor Score: {score_val:.2f}/100 (Grade: {regressor_grade}) | Direct Classifier Grade: {direct_classifier_grade}")
        if warnings:
            print(f"  [RISK WARNINGS] {', '.join(warnings)}")

        results.append({
            'predicted_score': score_val,
            'predicted_grade_from_score': regressor_grade,
            'predicted_grade_direct_classifier': direct_classifier_grade,
            'final_recommended_grade': direct_classifier_grade,
            'risk_level': 'HIGH' if direct_classifier_grade in ['C', 'D'] else 'NORMAL',
            'warnings': warnings
        })

    if isinstance(branch_data, dict):
        return results[0]
    
    return {'predictions': results}



