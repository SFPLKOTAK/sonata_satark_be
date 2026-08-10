import os
import json
import joblib
import warnings
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Tuple, Dict, Any

from sklearn.model_selection import KFold, StratifiedKFold, RandomizedSearchCV
from sklearn.metrics import mean_absolute_error, accuracy_score, f1_score, classification_report
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight

from .config import (
    MODEL_FILE_PATH, CLASSIFIER_FILE_PATH, LABEL_ENCODER_PATH, 
    METRICS_FILE_PATH, ARTIFACTS_DIR, FEATURE_COLS, score_to_grade, GRADE_THRESHOLDS
)
from .feature_engineering import prepare_training_dataset
from .data_loader import load_data_from_csv, load_data_from_django_db

warnings.filterwarnings('ignore')

try:
    from xgboost import XGBRegressor, XGBClassifier
    HAS_XGBOOST = True
except ImportError:
    from sklearn.ensemble import GradientBoostingRegressor, GradientBoostingClassifier
    HAS_XGBOOST = False

try:
    from imblearn.over_sampling import SMOTE, BorderlineSMOTE
    HAS_SMOTE = True
except ImportError:
    HAS_SMOTE = False

BEST_HYPERPARAMS_FILE = ARTIFACTS_DIR / "best_hyperparameters.json"


def tune_hyperparameters(csv_filepath: str = None, n_iter: int = 25) -> Dict[str, Any]:
    """
    Executes SMOTE class balancing and 5-Fold Cross Validation hyperparameter tuning
    for both XGBoost Regressor and XGBoost Classifier.
    """
    print("\n" + "=" * 70)
    print(" [HYPERPARAMETER TUNING & SMOTE] Starting Dual Model Optimization")
    print("=" * 70)

    # 1. Load Data
    print("\n [STEP 1/6] Loading Input Dataset...")
    if csv_filepath:
        if not os.path.exists(csv_filepath):
            raise FileNotFoundError(f"CSV file not found: {csv_filepath}")
        df = load_data_from_csv(csv_filepath)
    else:
        try:
            df = load_data_from_django_db()
        except Exception as e:
            raise RuntimeError(f"Database connection failed: {e}")

    # 2. Feature Transformation & Dataset Prep
    print("\n [STEP 2/6] Preparing Feature Matrix & Target Vectors...")
    X, y_score, y_grade, df_clean = prepare_training_dataset(df)

    # Encode categorical target Grade for classifier
    label_encoder = LabelEncoder()
    y_grade_encoded = label_encoder.fit_transform(y_grade.astype(str))

    # 3. Train / Out-of-Time Test Split
    print("\n [STEP 3/6] Performing Out-of-Time Date Split...")
    if 'AsOnDate' in df_clean.columns:
        df_clean['AsOnDate'] = pd.to_datetime(df_clean['AsOnDate'])
        latest_date = df_clean['AsOnDate'].max()
        test_mask = (df_clean['AsOnDate'] == latest_date)
        train_mask = ~test_mask

        X_train, X_test = X[train_mask], X[test_mask]
        y_score_train, y_score_test = y_score[train_mask], y_score[test_mask]
        y_grade_train, y_grade_test = y_grade_encoded[train_mask], y_grade_encoded[test_mask]
        df_test = df_clean[test_mask]

        print(f"  [DATA SPLIT] Train set: {len(X_train)} rows (dates < {latest_date.strftime('%Y-%m-%d')})")
        print(f"  [DATA SPLIT] Test set: {len(X_test)} rows (Out-of-Time test month: {latest_date.strftime('%Y-%m-%d')})")
    else:
        from sklearn.model_selection import train_test_split
        X_train, X_test, y_score_train, y_score_test, y_grade_train, y_grade_test = train_test_split(
            X, y_score, y_grade_encoded, test_size=0.2, random_state=42
        )
        df_test = df_clean.iloc[X_test.index]
        print(f"  [DATA SPLIT] Train set: {len(X_train)} rows | Test set: {len(X_test)} rows")

    # Handle SMOTE or Class Weighting for Classifier
    if HAS_SMOTE:
        print(f"  [SMOTE] Imbalanced-learn detected. Applying BorderlineSMOTE to balance minority audit grades...")
        try:
            smote = BorderlineSMOTE(random_state=42, k_neighbors=min(3, len(X_train)-1))
            X_train_resampled, y_grade_train_resampled = smote.fit_resample(X_train, y_grade_train)
            print(f"  [SMOTE] Resampled Train size: {len(X_train)} ➔ {len(X_train_resampled)} rows")
        except Exception as e:
            print(f"  ⚠️ SMOTE skipped due to class distribution ({e}). Using balanced sample weights instead.")
            X_train_resampled, y_grade_train_resampled = X_train, y_grade_train
    else:
        print(f"  [CLASS WEIGHTS] SMOTE not installed. Applying balanced sample weights for XGBoost Classifier...")
        X_train_resampled, y_grade_train_resampled = X_train, y_grade_train

    # Calculate sample weights for class imbalance
    sample_weights = compute_sample_weight('balanced', y_grade_train_resampled)

    # 4. Regressor Hyperparameter Search
    print("\n [STEP 4/6] Tuning XGBoost Regressor (Audit Score Predictor)...")
    regressor_param_grid = {
        'n_estimators': [100, 200, 300, 400, 500],
        'max_depth': [3, 4, 5, 6, 7, 8],
        'learning_rate': [0.01, 0.03, 0.05, 0.08, 0.1, 0.15],
        'subsample': [0.6, 0.7, 0.8, 0.9, 1.0],
        'colsample_bytree': [0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        'min_child_weight': [1, 3, 5, 7, 9],
        'gamma': [0.0, 0.1, 0.2, 0.5, 1.0],
        'reg_alpha': [0.0, 0.1, 0.5, 1.0, 5.0],
        'reg_lambda': [0.5, 1.0, 2.0, 5.0, 10.0]
    }

    if HAS_XGBOOST:
        base_regressor = XGBRegressor(random_state=42, enable_categorical=True, tree_method='hist')
    else:
        base_regressor = GradientBoostingRegressor(random_state=42)
        regressor_param_grid = {k: v for k, v in regressor_param_grid.items() if k in ['n_estimators', 'max_depth', 'learning_rate', 'subsample']}

    cv_reg = KFold(n_splits=5, shuffle=True, random_state=42)
    search_reg = RandomizedSearchCV(
        estimator=base_regressor,
        param_distributions=regressor_param_grid,
        n_iter=n_iter,
        scoring='neg_mean_absolute_error',
        cv=cv_reg,
        random_state=42,
        n_jobs=-1,
        verbose=1
    )
    search_reg.fit(X_train, y_score_train)

    best_regressor = search_reg.best_estimator_
    best_reg_mae = -search_reg.best_score_
    print(f"  [REGRESSOR TUNED] Best 5-Fold Cross Validation MAE: {best_reg_mae:.2f} score points")
    print(f"  [BEST REGRESSOR PARAMS] {search_reg.best_params_}")

    # 5. Classifier Hyperparameter Search
    print("\n [STEP 5/6] Tuning XGBoost Classifier (Audit Grade Predictor)...")
    classifier_param_grid = {
        'n_estimators': [100, 200, 300, 400],
        'max_depth': [3, 4, 5, 6, 7],
        'learning_rate': [0.01, 0.03, 0.05, 0.08, 0.1],
        'subsample': [0.6, 0.7, 0.8, 0.9],
        'colsample_bytree': [0.5, 0.6, 0.7, 0.8, 0.9],
        'min_child_weight': [1, 3, 5],
        'gamma': [0.0, 0.1, 0.3],
        'reg_alpha': [0.0, 0.1, 0.5, 1.0],
        'reg_lambda': [0.5, 1.0, 2.0]
    }

    if HAS_XGBOOST:
        base_classifier = XGBClassifier(random_state=42, enable_categorical=True, tree_method='hist')
    else:
        base_classifier = GradientBoostingClassifier(random_state=42)
        classifier_param_grid = {k: v for k, v in classifier_param_grid.items() if k in ['n_estimators', 'max_depth', 'learning_rate', 'subsample']}

    cv_clf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    search_clf = RandomizedSearchCV(
        estimator=base_classifier,
        param_distributions=classifier_param_grid,
        n_iter=n_iter,
        scoring='f1_weighted',
        cv=cv_clf,
        random_state=42,
        n_jobs=-1,
        verbose=1
    )
    
    if HAS_XGBOOST and not HAS_SMOTE:
        search_clf.fit(X_train_resampled, y_grade_train_resampled, sample_weight=sample_weights)
    else:
        search_clf.fit(X_train_resampled, y_grade_train_resampled)

    best_classifier = search_clf.best_estimator_
    best_clf_f1 = search_clf.best_score_
    print(f"  [CLASSIFIER TUNED] Best 5-Fold Cross Validation F1-Score: {best_clf_f1:.4f}")
    print(f"  [BEST CLASSIFIER PARAMS] {search_clf.best_params_}")

    # 6. Evaluation & Saving Best Model Artifacts
    print("\n [STEP 6/6] Evaluating Tuned Models on Out-of-Time Test Set & Saving Artifacts...")
    from .config import optimize_grade_thresholds

    test_score_preds = best_regressor.predict(X_test)
    test_grade_preds_encoded = best_classifier.predict(X_test)
    test_grade_preds_direct = label_encoder.inverse_transform(test_grade_preds_encoded)

    test_mae = float(mean_absolute_error(y_score_test, test_score_preds))
    
    # Calculate optimal thresholds on training set predictions
    train_score_preds = best_regressor.predict(X_train)
    opt_t_A, opt_t_B, opt_t_C = optimize_grade_thresholds(y_score_train, train_score_preds)
    print(f"  [DYNAMIC THRESHOLD OPTIMIZER] Discovered Optimal Cutoffs: A >= {opt_t_A}, B >= {opt_t_B}, C >= {opt_t_C}")

    # Calculate grades from score regressor (Static vs Optimized)
    test_grades_static = [score_to_grade(s) for s in test_score_preds]
    test_grades_opt = [score_to_grade(s, thresholds=(opt_t_A, opt_t_B, opt_t_C)) for s in test_score_preds]
    actual_test_grades = [score_to_grade(s) for s in y_score_test]

    exact_acc_static = float(accuracy_score(actual_test_grades, test_grades_static)) * 100.0
    exact_acc_opt = float(accuracy_score(actual_test_grades, test_grades_opt)) * 100.0

    print(f"  [THRESHOLD ACCURACY COMPARISON] Static Cutoffs (70/60/50) : {exact_acc_static:.1f}%")
    print(f"  [THRESHOLD ACCURACY COMPARISON] Optimized ({opt_t_A}/{opt_t_B}/{opt_t_C})  : {exact_acc_opt:.1f}% ({exact_acc_opt - exact_acc_static:+.1f}% impact)")

    # High Risk Detection Accuracy (Grade C/D vs A/B)
    actual_high_risk = [1 if g in ['C', 'D'] else 0 for g in actual_test_grades]
    pred_high_risk = [1 if g in ['C', 'D'] else 0 for g in test_grades_opt]
    high_risk_acc = float(accuracy_score(actual_high_risk, pred_high_risk)) * 100.0

    # Save artifacts
    joblib.dump(best_regressor, MODEL_FILE_PATH)
    joblib.dump(best_classifier, CLASSIFIER_FILE_PATH)
    joblib.dump(label_encoder, LABEL_ENCODER_PATH)

    # Save hyperparams JSON
    best_hyperparams = {
        'timestamp': datetime.now().isoformat(),
        'regressor_params': search_reg.best_params_,
        'classifier_params': search_clf.best_params_,
        'optimized_thresholds': {'t_A': opt_t_A, 't_B': opt_t_B, 't_C': opt_t_C},
        'best_cv_mae': best_reg_mae,
        'best_cv_f1': best_clf_f1,
        'out_of_time_test_mae': test_mae,
        'static_exact_grade_accuracy': exact_acc_static,
        'optimized_exact_grade_accuracy': exact_acc_opt,
        'high_risk_detection_accuracy': high_risk_acc
    }
    with open(BEST_HYPERPARAMS_FILE, 'w') as f:
        json.dump(best_hyperparams, f, indent=2)

    # Feature Importance Drivers
    feature_importances = best_regressor.feature_importances_
    importance_df = pd.DataFrame({'Feature': FEATURE_COLS, 'Importance': feature_importances})
    importance_df = importance_df.sort_values(by='Importance', ascending=False)

    print("\n" + "=" * 70)
    print(" [RESULTS SUMMARY] OPTIMIZED DUAL MODEL TRAINING COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print(f"  Regressor Model Artifact  : {MODEL_FILE_PATH}")
    print(f"  Classifier Model Artifact : {CLASSIFIER_FILE_PATH}")
    print(f"  5-Fold CV Best MAE        : {best_reg_mae:.2f} score points")
    print(f"  Out-of-Time Test MAE      : {test_mae:.2f} score points ({latest_date.strftime('%B %Y') if 'AsOnDate' in df_clean.columns else 'Test Set'})")
    print(f"  4-Grade Exact Accuracy    : {exact_acc_opt:.1f}% (Exact A/B/C/D letter match)")
    print(f"  High Risk Detection Acc   : {high_risk_acc:.1f}% (Flagging High Risk C/D vs Normal A/B)")
    print("\n  Top 5 Predictive Drivers:")
    for idx, row in importance_df.head(5).iterrows():
        print(f"     * {row['Feature']:<25}: {row['Importance']*100:.1f}% impact")
    print("=" * 70 + "\n")

    return best_hyperparams


if __name__ == "__main__":
    tune_hyperparameters(n_iter=25)
