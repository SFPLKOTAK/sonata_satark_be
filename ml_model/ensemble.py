import os
import json
import joblib
import warnings
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any

from sklearn.ensemble import (
    StackingRegressor, StackingClassifier,
    HistGradientBoostingRegressor, HistGradientBoostingClassifier,
    RandomForestRegressor, RandomForestClassifier, ExtraTreesRegressor
)
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.metrics import mean_absolute_error, accuracy_score, f1_score
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight

from .config import (
    MODEL_FILE_PATH, CLASSIFIER_FILE_PATH, LABEL_ENCODER_PATH,
    METRICS_FILE_PATH, ARTIFACTS_DIR, FEATURE_COLS, score_to_grade, GRADE_THRESHOLDS
)
from .feature_engineering import prepare_training_dataset
from .data_loader import load_data_from_csv, load_data_from_django_db

warnings.filterwarnings('ignore')

# Check XGBoost
try:
    from xgboost import XGBRegressor, XGBClassifier
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

# Check CatBoost
try:
    from catboost import CatBoostRegressor, CatBoostClassifier
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

# Check LightGBM
try:
    from lightgbm import LGBMRegressor, LGBMClassifier
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

ENSEMBLE_MODEL_FILE = ARTIFACTS_DIR / "ensemble_risk_model.joblib"
ENSEMBLE_CLASSIFIER_FILE = ARTIFACTS_DIR / "ensemble_grade_classifier.joblib"
ENSEMBLE_METRICS_FILE = ARTIFACTS_DIR / "ensemble_metrics.json"


def train_stacking_ensemble(csv_filepath: str = None) -> Dict[str, Any]:
    """
    Trains a Stacking Ensemble combining XGBoost, CatBoost / LightGBM, and HistGradientBoosting
    with a Meta-Learner (Ridge / Logistic Regression) to maximize prediction accuracy.
    """
    print("\n" + "=" * 70)
    print(" [STACKING ENSEMBLE PIPELINE] Starting Dual Stacking Ensemble Training")
    print("=" * 70)

    # 1. Load Data
    print("\n [STEP 1/5] Loading Input Dataset...")
    if csv_filepath:
        if not os.path.exists(csv_filepath):
            raise FileNotFoundError(f"CSV file not found: {csv_filepath}")
        df = load_data_from_csv(csv_filepath)
    else:
        try:
            df = load_data_from_django_db()
        except Exception as e:
            raise RuntimeError(f"Database connection failed: {e}")

    # 2. Prepare Features & Targets
    print("\n [STEP 2/5] Preparing Feature Matrix & Targets...")
    X, y_score, y_grade, df_clean = prepare_training_dataset(df)

    label_encoder = LabelEncoder()
    y_grade_encoded = label_encoder.fit_transform(y_grade.astype(str))

    # Convert category dtypes for non-XGBoost models if needed
    X_numeric = X.copy()
    cat_cols = ['Zone', 'Division', 'Region']
    for c in cat_cols:
        if c in X_numeric.columns:
            X_numeric[c] = X_numeric[c].astype('category').cat.codes

    # 3. Train / Out-of-Time Test Split
    print("\n [STEP 3/5] Performing Time-Based Train/Test Split...")
    if 'AsOnDate' in df_clean.columns:
        df_clean['AsOnDate'] = pd.to_datetime(df_clean['AsOnDate'])
        latest_date = df_clean['AsOnDate'].max()
        test_mask = (df_clean['AsOnDate'] == latest_date)
        train_mask = ~test_mask

        X_train, X_test = X[train_mask], X[test_mask]
        X_train_num, X_test_num = X_numeric[train_mask], X_numeric[test_mask]
        y_score_train, y_score_test = y_score[train_mask], y_score[test_mask]
        y_grade_train, y_grade_test = y_grade_encoded[train_mask], y_grade_encoded[test_mask]

        print(f"  [DATA SPLIT] Train set: {len(X_train)} rows | Test set: {len(X_test)} rows ({latest_date.strftime('%B %Y')})")
    else:
        from sklearn.model_selection import train_test_split
        X_train, X_test, y_score_train, y_score_test, y_grade_train, y_grade_test = train_test_split(
            X, y_score, y_grade_encoded, test_size=0.2, random_state=42
        )
        X_train_num, X_test_num = X_numeric.iloc[X_train.index], X_numeric.iloc[X_test.index]
        print(f"  [DATA SPLIT] Train set: {len(X_train)} rows | Test set: {len(X_test)} rows")

    # 4. Construct Stacking Base Estimators
    print("\n [STEP 4/5] Building Stacking Ensemble Architecture...")
    estimators_reg = []
    estimators_clf = []

    # Base Model 1: XGBoost (Tuned Parameters)
    if HAS_XGBOOST:
        print("  [ENSEMBLE BASE 1] Including XGBoost Model...")
        estimators_reg.append(('xgb', XGBRegressor(
            n_estimators=400, max_depth=3, learning_rate=0.03, subsample=0.6,
            colsample_bytree=0.7, min_child_weight=5, reg_alpha=1.0, reg_lambda=1.0,
            enable_categorical=True, tree_method='hist', random_state=42
        )))
        estimators_clf.append(('xgb', XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.01, subsample=0.8,
            colsample_bytree=0.7, min_child_weight=5, reg_alpha=1.0, reg_lambda=1.0,
            enable_categorical=True, tree_method='hist', random_state=42
        )))

    # Base Model 2: CatBoost or LightGBM
    if HAS_CATBOOST:
        print("  [ENSEMBLE BASE 2] Including CatBoost Model...")
        estimators_reg.append(('cat', CatBoostRegressor(
            iterations=300, depth=4, learning_rate=0.05, verbose=0, random_seed=42
        )))
        estimators_clf.append(('cat', CatBoostClassifier(
            iterations=300, depth=4, learning_rate=0.03, verbose=0, random_seed=42
        )))
    elif HAS_LIGHTGBM:
        print("  [ENSEMBLE BASE 2] Including LightGBM Model...")
        estimators_reg.append(('lgb', LGBMRegressor(
            n_estimators=300, max_depth=4, learning_rate=0.03, subsample=0.7, random_state=42, verbose=-1
        )))
        estimators_clf.append(('lgb', LGBMClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.03, subsample=0.7, random_state=42, verbose=-1
        )))
    else:
        print("  [ENSEMBLE BASE 2] Including ExtraTrees Model...")
        estimators_reg.append(('et', ExtraTreesRegressor(n_estimators=200, max_depth=8, random_state=42)))
        estimators_clf.append(('et', RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42)))

    # Base Model 3: HistGradientBoosting
    print("  [ENSEMBLE BASE 3] Including HistGradientBoosting Model...")
    estimators_reg.append(('hgb', HistGradientBoostingRegressor(
        max_iter=300, max_depth=5, learning_rate=0.03, l2_regularization=1.0, random_state=42
    )))
    estimators_clf.append(('hgb', HistGradientBoostingClassifier(
        max_iter=300, max_depth=5, learning_rate=0.03, l2_regularization=1.0, random_state=42
    )))

    # Meta-Learners
    stacking_reg = StackingRegressor(
        estimators=estimators_reg,
        final_estimator=Ridge(alpha=1.0),
        cv=5,
        n_jobs=-1
    )
    stacking_clf = StackingClassifier(
        estimators=estimators_clf,
        final_estimator=LogisticRegression(C=1.0, max_iter=500),
        cv=5,
        n_jobs=-1
    )

    print("  [TRAINING STACKING ENSEMBLE] Fitting Meta-Learner across 5-Fold Base Predictions...")
    stacking_reg.fit(X_train_num, y_score_train)
    stacking_clf.fit(X_train_num, y_grade_train)

    # 5. Evaluate Stacking Performance
    print("\n [STEP 5/5] Evaluating Stacking Ensemble on Out-of-Time Test Set...")
    test_score_preds = stacking_reg.predict(X_test_num)
    test_grade_preds_encoded = stacking_clf.predict(X_test_num)

    test_mae = float(mean_absolute_error(y_score_test, test_score_preds))

    # Evaluate exact grade accuracy
    test_grades_from_score = [score_to_grade(s) for s in test_score_preds]
    actual_test_grades = [score_to_grade(s) for s in y_score_test]
    exact_acc = float(accuracy_score(actual_test_grades, test_grades_from_score)) * 100.0

    # Evaluate direct classifier grade accuracy
    direct_clf_acc = float(accuracy_score(y_grade_test, test_grade_preds_encoded)) * 100.0

    # High Risk Detection Accuracy (Grade C/D vs A/B)
    actual_high_risk = [1 if g in ['C', 'D'] else 0 for g in actual_test_grades]
    pred_high_risk = [1 if g in ['C', 'D'] else 0 for g in test_grades_from_score]
    high_risk_acc = float(accuracy_score(actual_high_risk, pred_high_risk)) * 100.0

    # 5-Fold Cross Validation MAE for Stacking Regressor
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    cv_maes = []
    for train_idx, val_idx in kf.split(X_numeric, y_score):
        X_tr, X_va = X_numeric.iloc[train_idx], X_numeric.iloc[val_idx]
        y_tr, y_va = y_score.iloc[train_idx], y_score.iloc[val_idx]
        reg_clone = StackingRegressor(estimators=estimators_reg, final_estimator=Ridge(alpha=1.0), cv=3)
        reg_clone.fit(X_tr, y_tr)
        preds = reg_clone.predict(X_va)
        cv_maes.append(mean_absolute_error(y_va, preds))
    overall_cv_mae = float(np.mean(cv_maes))

    # Save artifacts
    joblib.dump(stacking_reg, ENSEMBLE_MODEL_FILE)
    joblib.dump(stacking_clf, ENSEMBLE_CLASSIFIER_FILE)
    joblib.dump(stacking_reg, MODEL_FILE_PATH)  # Overwrite active model
    joblib.dump(stacking_clf, CLASSIFIER_FILE_PATH)  # Overwrite active classifier

    ensemble_metrics = {
        'training_timestamp': datetime.now().isoformat(),
        'model_type': 'Stacking Ensemble (XGBoost + CatBoost/LightGBM + HistGB)',
        'cv_5fold_mae': round(overall_cv_mae, 2),
        'out_of_time_test_mae': round(test_mae, 2),
        'exact_grade_accuracy': round(exact_acc, 1),
        'direct_classifier_accuracy': round(direct_clf_acc, 1),
        'high_risk_detection_accuracy': round(high_risk_acc, 1)
    }

    with open(ENSEMBLE_METRICS_FILE, 'w') as f:
        json.dump(ensemble_metrics, f, indent=2)

    print("\n" + "=" * 70)
    print(" [RESULTS SUMMARY] STACKING ENSEMBLE TRAINING COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print(f"  Ensemble Model Artifact   : {ENSEMBLE_MODEL_FILE}")
    print(f"  5-Fold CV Overall MAE     : {overall_cv_mae:.2f} score points")
    print(f"  Out-of-Time Test MAE      : {test_mae:.2f} score points ({latest_date.strftime('%B %Y') if 'AsOnDate' in df_clean.columns else 'Test Set'})")
    print(f"  4-Grade Exact Accuracy    : {exact_acc:.1f}% (Exact A/B/C/D letter match)")
    print(f"  Direct Classifier Accuracy: {direct_clf_acc:.1f}%")
    print(f"  High Risk Detection Acc   : {high_risk_acc:.1f}% (Flagging High Risk C/D vs Normal A/B)")
    print("=" * 70 + "\n")

    return ensemble_metrics


if __name__ == "__main__":
    train_stacking_ensemble()
