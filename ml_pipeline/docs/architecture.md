# ML Model Feature Engineering Discussion

## Context
The goal is to train a Machine Learning model (specifically a Random Forest Regressor) to predict the Branch-Level Risk Score and Post-Audit Final Grade (A/B/C/D) based on historical microfinance branch data. 

## The Stored Procedure Provided
The following SQL Stored Procedure (`SP_BranchRiskScore`) is currently used in the system to calculate the pre-audit risk score deterministically:

```sql
USE [Sonata_Satark]
GO
/****** Object:  StoredProcedure [dbo].[SP_BranchRiskScore]    Script Date: 06-08-2026 10:20:47 ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
ALTER     PROCEDURE [dbo].[SP_BranchRiskScore]
    @AsOnDate  DATE,
    @Division  NVARCHAR(100)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @PriorDate  DATE     = DATEADD(DAY, -30, @AsOnDate);
    DECLARE @Msg        NVARCHAR(200);
    DECLARE @StartTime  DATETIME = GETDATE();
    DECLARE @StepTime   DATETIME;

    -- STEP 1 : Base snapshot — single scan, 2 date slices
    -- (Reads from Active_Loan_Performance..TBL_ActiveLoansPerformanceData)

    -- STEP 2 : Portfolio quality metrics  (current date only)
    -- (Calculates NPALoans, WeightedBucketScore, WriteOffAmt, etc.)

    -- STEP 3 : Trend / velocity metrics  (current vs prior)
    -- (Calculates NPA Drift, Arrear Velocity, MoM defaults)

    -- STEP 4 : Collection efficiency metrics  (current only)
    -- (Calculates TotalDue, TotalCollected, AvgDaysSinceCollection)

    -- STEP 5 : Customer & concentration risk  (current only)
    -- (Calculates TopCenterNPAConc, TopStaffNPAConc, DAWriteOffCount)

    -- STEP 6 : Final score assembly + output
    -- (Applies hardcoded weights to generate RiskScore and RiskGrade)
END
```

## AI Analysis: How this SQL script powers the ML Model
This SQL script is incredibly valuable for the Machine Learning pipeline because it is effectively doing the hardest part of ML: **Feature Engineering**. 

It perfectly groups the data at the Branch level (`GROUP BY BRANCH, BRANCHID`) and extracts the exact four categories of features required to train a highly accurate Random Forest model:

### 1. Portfolio Quality Features (Step 2)
The script is already calculating the perfect raw features for this:
*   `WriteOffCount` and `WriteOffAmt`
*   `NPALoans`
*   `PAR_1_30_Amt`, `PAR_31_60_Amt`, `PAR_61_90_Amt`
*   `WeightedBucketScore` (This is a fantastic feature to feed an ML model)

### 2. Trend & Velocity Features (Step 3)
By comparing `@AsOnDate` vs `@PriorDate` (Month-over-Month), the script creates extremely predictive momentum features:
*   `Cur_NPA_Amt` vs `Pri_NPA_Amt` (NPA Drift)
*   `NewDefaultsThisMonth`
*   `Cur_ArrearAmt` vs `Pri_ArrearAmt` (Arrear Velocity)

### 3. Collection Efficiency (Step 4)
*   `TotalDue` vs `TotalCollected` (This becomes your Collection Percentage feature).
*   `AvgDaysSinceCollection` (Measures collection recency).
*   `LoansWithMissedInst`

### 4. Concentration Risk (Step 5)
This is highly advanced and perfect for ML. It identifies if the risk is concentrated in one specific area:
*   `TopCenterNPAConc` (Is one center dragging down the whole branch?)
*   `TopStaffNPAConc` (Is one specific Field Officer responsible for all the NPAs?)

---

## Actionable Next Steps for Model Training
Right now, in **Step 6**, the script uses hardcoded math to create the final score (e.g., multiplying by `60.0` or `100.0` and capping at certain max limits). 

**To train the Random Forest Model:**
1. Run **Steps 1 through 5** of this SQL script across the last 24 months of historical data. 
2. Instead of running Step 6 (the hardcoded math), export the raw aggregated columns from `#PortfolioQuality`, `#TrendMetrics`, `#CollectionMetrics`, and `#ConcentrationRisk` into a CSV file.
3. Feed those raw columns into **Random Forest Regressor** as the Input Features (`X`), and set the historical actual grade/score as the Target Variable (`Y`). 
4. The Random Forest model will mathematically learn its own dynamic weights for these features, which will be significantly more accurate than the static `if/else` rules currently written in Step 6.

### Exactly how the SQL creates the Feature Vector (X)
*   **Step 1** just grabs the raw, messy loan data.
*   **Steps 2, 3, 4, and 5** do the heavy lifting. They calculate the totals, averages, percentages, and MoM (Month-over-Month) changes specifically for each `BRANCHID`. 
*   If you `JOIN` the results from `#PortfolioQuality`, `#TrendMetrics`, `#CollectionMetrics`, and `#ConcentrationRisk` together using the `BRANCHID`, you get one massive row of incredibly rich, calculated data for each branch. That single combined row is your **Feature Vector (X)** for the Machine Learning model. 

### Why do we skip Step 6?
In Step 6 of the current SQL script, a human has manually decided the math rules. For example, the script says: *"If they have NPALoans, multiply it by 100 and divide by TotalLoans, but cap it at 100."*
When you use an ML model (like Random Forest), you don't want human-hardcoded rules. You want the AI to figure out the mathematical relationships dynamically based on historical outcomes.

---

## Model Selection & Architecture

You will use the **same type of algorithm** for predicting both the Pre-Audit Risk Score and the Post-Audit Final Grade, but you must train **two completely separate models**.

### Why train two separate models?
While a branch with a high Risk Score (CRITICAL) usually gets a bad Audit Grade (Grade D), this isn't always true. Sometimes a branch has a massive Risk Score because of external factors (like a volatile geographical area with high NPA), but the Branch Manager is strictly following all compliance rules, meaning they might still get a "Grade B" on their actual audit. Training two separate models allows the AI to learn the subtle differences between *"What makes a branch risky?"* versus *"What makes a branch fail compliance checks?"*

### Recommended Algorithm: Random Forest Regressor
For both models, the absolute best algorithm for a smaller dataset (~4,700 rows) is the **Random Forest Regressor**. 

*   **For Model A (Pre-Audit Risk Score):** The Risk Score is an open-ended integer (e.g., 100, 450, 800+). Random Forest is incredibly good at predicting unbounded numbers and handling extreme outliers without aggressively overfitting.
*   **For Model B (Post-Audit Percentage):** Your Audit Score is a percentage between 0 and 100. Random Forest Regressor is highly precise and will easily learn to predict exact decimals (like 78.5%), which allows you to accurately map it to your A/B/C/D logic. 

### Why Random Forest over Neural Networks (or XGBoost)?
For structured, tabular datasets of smaller sizes (like 4,700 rows), Bagging Ensemble Models (Random Forests) are the undisputed champions:

1.  **They Don't Care About Data Scale:** Neural Networks will completely fail unless you perfectly normalize and scale all numbers. Random Forest splits data based on thresholds, so it mathematically does not care if `collectionPct` is `98` and `portfolioSize` is `25,000,000`.
2.  **Immunity to Overfitting:** XGBoost uses "Boosting" which can overfit quickly on 4,700 rows if not tuned perfectly. Random Forest uses "Bagging" (Bootstrap Aggregating) which averages out hundreds of random trees, making it almost completely immune to overfitting.
3.  **Explainability:** In auditing, "black box" models are unacceptable. Random Forest provides clear **Feature Importance**, letting you generate a report that says: *"The model assigned a Grade D because [1] Collection dropped by 5%, [2] NPA is above 3%, and [3] there are 2 Open CAPs."* This explainability is mandatory for building trust with auditors.

---

## The Master Feature Vector (How the JOIN works)

To actually build the training dataset for the Machine Learning model, you need a single, flat table where **1 Row = 1 Branch**. You get this by combining the temporary tables created in Steps 2, 3, 4, and 5 of your SQL Stored Procedure using a standard `JOIN` on `BRANCHID`.

```sql
SELECT 
    pq.*, 
    tm.*, 
    cm.*, 
    cr.*
FROM #PortfolioQuality pq
JOIN #TrendMetrics tm ON pq.BRANCHID = tm.BRANCHID
JOIN #CollectionMetrics cm ON pq.BRANCHID = cm.BRANCHID
JOIN #ConcentrationRisk cr ON pq.BRANCHID = cr.BRANCHID;
```
*(You can export the results of this SQL query straight to a `.csv` file, and feed it directly into Python!)*

### Exact Features (Columns) Extracted from Each Step

Here is the exhaustive list of the exact columns (Features) that your Stored Procedure is already generating, which will become the `X` (Input) for the Random Forest model:

#### 1. Features from Step 2 (`#PortfolioQuality`)
This step gives the model the absolute baseline health of the branch on the current day:
*   `TotalLoans` (Volume of business)
*   `WriteOffCount` & `WriteOffAmt` (Absolute losses)
*   `LoansInArrear` & `TotalArrearAmt` (Current delinquency)
*   `NPALoans` (Non-performing assets count)
*   `TotalPrincipalOS` (Total outstanding balance)
*   **The Buckets:** `PAR_1_30_Amt`, `PAR_31_60_Amt`, `PAR_61_90_Amt`, `PAR_90Plus_Amt`
*   `DeceasedCount` (Client mortality risk)
*   `GoodLoanCount` (Healthy portfolio volume)
*   `WeightedBucketScore` (A fantastic aggregated risk metric)

#### 2. Features from Step 3 (`#TrendMetrics`)
This step gives the model "velocity" (is the branch getting better or worse month-over-month?). Random Forest relies heavily on these features to catch branches that are rapidly failing:
*   **Current vs Prior Snapshot:** `Cur_PrincipalOS` vs `Pri_PrincipalOS`
*   **NPA Drift:** `Cur_NPA_Amt` vs `Pri_NPA_Amt`
*   **Arrear Velocity:** `Cur_ArrearAmt` vs `Pri_ArrearAmt`
*   **Write-off Momentum:** `Cur_WriteOffAmt` vs `Pri_WriteOffAmt` (and counts)
*   **Early Warning Indicators:** `NewDefaultsThisMonth`, `Cur_MidBucketCount`, `Pri_EarlyBucketCount`

#### 3. Features from Step 4 (`#CollectionMetrics`)
This step gives the model insight into the operational efficiency of the field officers:
*   `TotalDue` & `TotalCollected` (The AI will mathematically learn the Collection Percentage from these two numbers).
*   `TotalInstInArrear` & `LoansWithMissedInst` (Missed installment volume)
*   `TotalLoansForColl` (Total demand)
*   `AvgDaysSinceCollection` & `MaxDaysSinceCollection` (Crucial recency metrics)
*   `AvgArrearDays` & `AvgInstallmentsInArrear` (Severity of the delinquency)

#### 4. Features from Step 5 (`#ConcentrationRisk`)
This step gives the model insight into whether the risk is systemic (branch-wide) or isolated to a specific bad actor:
*   `TotalForConc` & `TotalNPALoans` (Baselines for concentration)
*   `RepeatBorrowerNPA` (Are veteran clients defaulting?)
*   `DAWriteOffCount` (Direct Assignment portfolio risk)
*   `TopCenterNPAConc` (Percentage of NPA concentrated in the single worst center)
*   `TopStaffNPAConc` (Percentage of NPA tied to the single worst field officer)
*   `TopProductNPAConc` (Percentage of NPA tied to a specific loan product)
*   `TopProductNPAConc` (Percentage of NPA tied to a specific loan product)

---

## Training the Model (Focused solely on `Risk Score`)

Since we are focusing entirely on predicting the **Pre-Audit Risk Score** (Model A), you will be training a `Random Forest Regressor` where the target variable is the historical integer score (0 to 1000+).

Here is the exact Python workflow tailored specifically for this:

### 1. The Dataset Requirements
Your CSV file must contain the combined columns from Steps 2, 3, 4, and 5 for each `BRANCHID`. You must add one final column to this dataset:
*   `Historical_Risk_Score`: The actual risk score that branch got on that specific date.

### 2. The Python Code for Training (Optimized for Small Datasets ~4,700 rows)
Because the dataset is smaller, we use `RandomForestRegressor` instead of boosting models to ensure high accuracy without the risk of overfitting.

```python
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_absolute_error

# 1. Load your exported CSV (from the SQL JOIN)
df = pd.read_csv("branch_risk_score_data.csv")

# 2. Separate Features (X) and Target (Y)
X = df.drop(columns=["BRANCHID", "Historical_Risk_Score"]) 
Y = df["Historical_Risk_Score"] # The model's "Answer Key"

# 3. Train/Test Split (80% training, 20% testing)
X_train, X_test, Y_train, Y_test = train_test_split(X, Y, test_size=0.2, random_state=42)

# 4. Initialize the Random Forest Model
# n_estimators=100 means the AI will build 100 independent decision trees and average them
model = RandomForestRegressor(
    n_estimators=100, 
    random_state=42
)

# Optional: Run 5-Fold Cross-Validation to ensure stability on 4.7k rows
cv_scores = cross_val_score(model, X_train, Y_train, cv=5, scoring='neg_mean_absolute_error')
print(f"Cross-Validation Average Error: {-cv_scores.mean():.2f}")

# 5. Train the Model and Evaluate!
model.fit(X_train, Y_train)
predictions = model.predict(X_test)
error = mean_absolute_error(Y_test, predictions)

print(f"The model's final predictions are off by an average of {error:.2f} points.")
```

### 3. Deploying the Score Predictor
Once trained and saved (e.g., `model.pkl`), using it in production is incredibly simple. 
When the backend needs to generate the Risk Score for a branch today, it simply runs Steps 1-5 of the SQL script to get the current aggregated features, passes them into `model.predict()`, and the AI will output the predicted `Risk Score` dynamically!

---

## Final Training Table Schema

To automate your machine learning pipeline, it is best practice to create a dedicated table in your database (e.g., `tbl_ML_TrainingData_RiskScore`). You can set up a monthly SQL Job that runs on the 1st of every month to calculate all features and insert a new batch of rows into this table.

Here is the exact schema you need for that single, flattened table:

### 1. Identifiers (Ignored by the ML Model)
These columns are used by humans to identify the row, but are dropped before passing the data to Random Forest.
*   `SnapshotDate` (DATE) — e.g., 2026-08-01
*   `BRANCHID` (INT / VARCHAR)
*   `BranchName` (VARCHAR)
*   `Division` (VARCHAR)

### 2. The Target Variable (The Answer Key)
*   `Historical_Risk_Score` (FLOAT) — The actual integer score calculated historically.

### 3. Feature Vector (The 'X' Columns)
*All of these should be `FLOAT` or `INT` depending on your DB precision preferences.*

**From Step 2 (Portfolio Quality):**
*   `TotalLoans`
*   `WriteOffCount`
*   `WriteOffAmt`
*   `LoansInArrear`
*   `NPALoans`
*   `TotalPrincipalOS`
*   `PAR_1_30_Amt`
*   `PAR_31_60_Amt`
*   `PAR_61_90_Amt`
*   `PAR_90Plus_Amt`
*   `TotalArrearAmt`
*   `DeceasedCount`
*   `GoodLoanCount`
*   `WeightedBucketScore`

**From Step 3 (Trend / Velocity):**
*   `Cur_PrincipalOS`
*   `Cur_PAR0_Amt`
*   `Cur_NPA_Amt`
*   `Cur_ArrearAmt`
*   `Cur_WriteOffAmt`
*   `Cur_WriteOffCount`
*   `Pri_PrincipalOS`
*   `Pri_PAR0_Amt`
*   `Pri_NPA_Amt`
*   `Pri_ArrearAmt`
*   `Pri_WriteOffAmt`
*   `Pri_WriteOffCount`
*   `NewDefaultsThisMonth`
*   `Cur_MidBucketCount`
*   `Pri_EarlyBucketCount`

**From Step 4 (Collection Efficiency):**
*   `TotalDue`
*   `TotalCollected`
*   `TotalInstInArrear`
*   `LoansWithMissedInst`
*   `TotalLoansForColl`
*   `AvgDaysSinceCollection`
*   `MaxDaysSinceCollection`
*   `AvgArrearDays`
*   `AvgInstallmentsInArrear`

**From Step 5 (Concentration Risk):**
*   `TotalForConc`
*   `TotalNPALoans_Conc` *(Renamed slightly if conflicting with Step 2)*
*   `RepeatBorrowerNPA`
*   `DAWriteOffCount`
*   `TopCenterNPAConc`
*   `TopStaffNPAConc`
*   `TopProductNPAConc`
