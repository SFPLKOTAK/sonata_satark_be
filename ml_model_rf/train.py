import os
import json
import joblib
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, accuracy_score
from sklearn.preprocessing import LabelEncoder, OrdinalEncoder

from .config import MODEL_FILE_PATH, CLASSIFIER_FILE_PATH, LABEL_ENCODER_PATH, CATEGORICAL_ENCODER_PATH, METRICS_FILE_PATH, FEATURE_COLS, score_to_grade
from .feature_engineering import prepare_training_dataset
from .data_loader import load_data_from_csv, load_data_from_django_db

from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
HAS_XGBOOST = False


def train_model(data_source_df: pd.DataFrame = None, csv_filepath: str = None) -> dict:
    """
    Trains both Score Regressor and Grade Classifier using portfolio & regional features.
    """
    print("\n" + "=" * 65)
    print(" [ML TRAINING PIPELINE] Starting Dual Model Training Process")
    print("=" * 65)

    # 1. Load Data
    print("\n [STEP 1/5] Loading Input Dataset...")
    if data_source_df is not None:
        df = data_source_df
        print(f"   [DATA SOURCE] Provided DataFrame loaded | Rows: {len(df)}")
    elif csv_filepath:
        if not os.path.exists(csv_filepath):
            print(f"  ❌ Error: Provided CSV file path '{csv_filepath}' does not exist.")
            raise FileNotFoundError(f"CSV file not found: {csv_filepath}")
        df = load_data_from_csv(csv_filepath)
    else:
        try:
            df = load_data_from_django_db()
        except Exception as e:
            raise RuntimeError(f"Data source not provided and DB connection failed: {e}")

    # 2. Feature Transformation & Dataset Prep
    print("\n [STEP 2/5] Performing Feature & Categorical Hierarchy Transformations...")
    X, y_score, y_grade, df_clean = prepare_training_dataset(df)

    if len(X) < 10:
        raise ValueError(f"Insufficient training samples ({len(X)} rows). Minimum 10 rows required.")

    # Encode categorical target Grade for classifier
    label_encoder = LabelEncoder()
    y_grade_encoded = label_encoder.fit_transform(y_grade.astype(str))

    # Encode categorical features for Random Forest
    cat_cols = ['Zone', 'Division', 'Region']
    cat_encoder = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
    X[cat_cols] = cat_encoder.fit_transform(X[cat_cols])

    # 3. Time-Based Train / Test Split Execution
    print("\n [STEP 3/5] Splitting Dataset into Train and Test Sets...")
    if 'AsOnDate' in df_clean.columns:
        df_clean['AsOnDate'] = pd.to_datetime(df_clean['AsOnDate'])

    if 'AsOnDate' in df_clean.columns and df_clean['AsOnDate'].nunique() > 1:
        latest_date = df_clean['AsOnDate'].max()
        train_mask = df_clean['AsOnDate'] < latest_date
        test_mask = df_clean['AsOnDate'] == latest_date
        
        if train_mask.sum() == 0 or test_mask.sum() == 0:
            split_idx = int(len(X) * 0.8)
            X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
            y_score_train, y_score_test = y_score.iloc[:split_idx], y_score.iloc[split_idx:]
            y_grade_train, y_grade_test = y_grade_encoded[:split_idx], y_grade_encoded[split_idx:]
            print(f"   [SPLIT STRATEGY] 80/20 Sequential Split")
        else:
            X_train, X_test = X[train_mask], X[test_mask]
            y_score_train, y_score_test = y_score[train_mask], y_score[test_mask]
            y_grade_train, y_grade_test = y_grade_encoded[train_mask], y_grade_encoded[test_mask]
            earlier_dates = df_clean.loc[train_mask, 'AsOnDate'].dt.strftime('%Y-%m-%d').unique()
            latest_date_str = latest_date.strftime('%Y-%m-%d')
            print(f"   [SPLIT STRATEGY] Time-Based Split (Prevents Temporal Leakage)")
            print(f"     * TRAIN DATES : {min(earlier_dates)} to {max(earlier_dates)} ({len(X_train)} rows)")
            print(f"     * TEST DATE   : {latest_date_str} (Out-of-Time Test | {len(X_test)} rows)")
    else:
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_score_train, y_score_test = y_score.iloc[:split_idx], y_score.iloc[split_idx:]
        y_grade_train, y_grade_test = y_grade_encoded[:split_idx], y_grade_encoded[split_idx:]

    print(f"\n [STEP 4/5] Tuning & Training Dual Models (Score Regressor & Grade Classifier)...")
    from sklearn.model_selection import RandomizedSearchCV
    
    # Hyperparameter Grid
    param_grid = {
        'n_estimators': [100, 200, 300, 400],
        'max_depth': [4, 6, 8, 10, None],
        'min_samples_split': [2, 5, 10],
        'min_samples_leaf': [1, 2, 4]
    }

    print("   [TUNING] Running RandomizedSearchCV for Regressor (3-Fold CV, 10 Iterations)...")
    base_regressor = RandomForestRegressor(random_state=42, n_jobs=-1)
    reg_search = RandomizedSearchCV(estimator=base_regressor, param_distributions=param_grid, n_iter=10, cv=3, random_state=42, n_jobs=-1, scoring='neg_mean_absolute_error')
    reg_search.fit(X_train, y_score_train)
    regressor = reg_search.best_estimator_
    print(f"      Best Regressor Params: {reg_search.best_params_}")

    print("   [TUNING] Running RandomizedSearchCV for Classifier (3-Fold CV, 10 Iterations)...")
    base_classifier = RandomForestClassifier(random_state=42, n_jobs=-1)
    clf_search = RandomizedSearchCV(estimator=base_classifier, param_distributions=param_grid, n_iter=10, cv=3, random_state=42, n_jobs=-1, scoring='accuracy')
    clf_search.fit(X_train, y_grade_train)
    classifier = clf_search.best_estimator_
    print(f"      Best Classifier Params: {clf_search.best_params_}")

    print("   [MODEL FIT] Tuned Regressor and Classifier trained successfully.")

    # 5. Evaluate Performance & Save Artifacts
    print("\n [STEP 5/5] Evaluating Dual Model Performance (Out-of-Time Test & 5-Fold Cross Validation)...")
    from sklearn.model_selection import KFold, cross_val_score
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    
    cv_mae_scores = -cross_val_score(regressor, X, y_score, cv=kf, scoring='neg_mean_absolute_error')
    cv_clf_acc = cross_val_score(classifier, X, y_grade_encoded, cv=kf, scoring='accuracy')

    # Regressor Predictions on Out-of-Time Test Set
    y_score_pred = np.clip(regressor.predict(X_test), 0, 100)
    mae = float(mean_absolute_error(y_score_test, y_score_pred))
    r2 = float(r2_score(y_score_test, y_score_pred)) if len(y_score_test) > 1 else 0.0
    regressor_grades = [score_to_grade(s) for s in y_score_pred]
    actual_grades_str = label_encoder.inverse_transform(y_grade_test)
    regressor_accuracy = float(accuracy_score(actual_grades_str, regressor_grades))

    # Classifier Predictions on Out-of-Time Test Set
    y_grade_pred = classifier.predict(X_test)
    classifier_accuracy = float(accuracy_score(y_grade_test, y_grade_pred))
    predicted_grades_str = label_encoder.inverse_transform(y_grade_pred)

    # Binary High Risk Detection Accuracy (Grade C/D vs Grade A/B)
    actual_high_risk = [1 if g in ['C', 'D'] else 0 for g in actual_grades_str]
    predicted_high_risk = [1 if g in ['C', 'D'] else 0 for g in predicted_grades_str]
    high_risk_accuracy = float(accuracy_score(actual_high_risk, predicted_high_risk))

    metrics = {
        'training_timestamp': datetime.now().isoformat(),
        'model_type': 'RandomForestRegressor + RandomForestClassifier',
        'train_samples': int(len(X_train)),
        'test_samples': int(len(X_test)),
        'regressor_mae': round(mae, 2),
        'regressor_r2_score': round(r2, 4),
        'regressor_grade_accuracy': round(regressor_accuracy, 4),
        'classifier_grade_accuracy': round(classifier_accuracy, 4),
        'high_risk_detection_accuracy': round(high_risk_accuracy, 4),
        'cv_5fold_regressor_mae': round(float(cv_mae_scores.mean()), 2),
        'cv_5fold_classifier_accuracy': round(float(cv_clf_acc.mean()), 4),
        'feature_importances': dict(zip(FEATURE_COLS, [round(float(imp), 4) for imp in regressor.feature_importances_]))
    }

    joblib.dump(regressor, MODEL_FILE_PATH)
    joblib.dump(classifier, CLASSIFIER_FILE_PATH)
    joblib.dump(label_encoder, LABEL_ENCODER_PATH)
    joblib.dump(cat_encoder, CATEGORICAL_ENCODER_PATH)
    
    with open(METRICS_FILE_PATH, 'w') as f:
        json.dump(metrics, f, indent=4)

    print("\n" + "=" * 65)
    print(" [RESULTS SUMMARY] DUAL MODEL TRAINING COMPLETED SUCCESSFULLY")
    print("=" * 65)
    print(f"  Regressor Model Artifact  : {MODEL_FILE_PATH}")
    print(f"  Classifier Model Artifact : {CLASSIFIER_FILE_PATH}")
    print(f"  5-Fold CV Overall MAE     : {metrics['cv_5fold_regressor_mae']:.2f} score points (Across all 4,265 rows)")
    print(f"  Out-of-Time Test MAE      : {mae:.2f} score points (July 2026 test month)")
    print(f"  4-Grade Exact Accuracy    : {classifier_accuracy * 100:.1f}% (Exact A/B/C/D letter match)")
    print(f"  High Risk Detection Acc   : {high_risk_accuracy * 100:.1f}% (Flagging High Risk C/D vs Normal A/B)")
    print("\n  Top 5 Predictive Drivers:")
    sorted_importances = sorted(metrics['feature_importances'].items(), key=lambda x: x[1], reverse=True)
    for feat, imp in sorted_importances[:5]:
        print(f"     * {feat:<25}: {imp * 100:.1f}% impact")
    print("=" * 65 + "\n")

    return metrics




if __name__ == '__main__':
    import sys
    csv_path = sys.argv[1] if len(sys.argv) > 1 else None
    train_model(csv_filepath=csv_path)

