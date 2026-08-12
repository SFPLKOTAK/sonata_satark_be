import os
import pyodbc
import pandas as pd
import joblib
import warnings

warnings.filterwarnings('ignore', message='.*pandas only supports SQLAlchemy connectable.*')

# Setup paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "random_forest_model.pkl")
ENCODER_PATH = os.path.join(BASE_DIR, "models", "categorical_encoder.pkl")

def get_db_connection():
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=172.17.130.164;"
        "DATABASE=Sonata_satark;"
        "UID=Paymee_VishalM;"
        "PWD=$V!sH@lM#231"
    )
    return pyodbc.connect(conn_str)

def run_predictions():
    print(f"Loading trained model from {MODEL_PATH}...")
    if not os.path.exists(MODEL_PATH) or not os.path.exists(ENCODER_PATH):
        print("ERROR: Model or Encoder not found. You must run train.py first to generate the AI model!")
        return
        
    model = joblib.load(MODEL_PATH)
    encoder = joblib.load(ENCODER_PATH)
    
    print("Connecting to database to fetch CURRENT month features...")
    try:
        conn = get_db_connection()
        # Fetch the branches that need to be planned for audit this month
        query = "SELECT * FROM [dbo].[TBL_ML_CurrentMonth_Features]"
        df = pd.read_sql(query, conn)
        
        if len(df) == 0:
            print("No current data found in TBL_ML_CurrentMonth_Features.")
            conn.close()
            return
            
        print(f"Generating Risk Scores for {len(df)} branches...")
        
        # Keep a copy of the Branch IDs for saving back to DB later
        branch_ids = df['Branch_ID']
        
        # Sort by Date so shift(1) correctly grabs the previous month chronologically
        if 'AsOnDate' in df.columns:
            df = df.sort_values(by=['Branch_ID', 'AsOnDate'])
            
        # Generate Previous Audit Score (Lag 1 per Branch)
        if 'Branch_ID' in df.columns and 'Score' in df.columns:
            df['Prev_Score'] = df.groupby('Branch_ID')['Score'].shift(1)
            df['Prev_Score'] = df['Prev_Score'].fillna(df['Score'])
        else:
            df['Prev_Score'] = 50.0

        # Drop text identifiers (must match EXACTLY what was dropped in train.py)
        columns_to_drop = [
            "Zone", "Branch_Name", "Branch_ID", "Month", "BRANCHID", "BranchName",
            "Grade", "RiskGrade", "Score", "RiskScore"
        ]
        
        X = df.drop(columns=[col for col in columns_to_drop if col in df.columns])
        
        # Fill any missing metrics with 0 (Matches the training script)
        X = X.fillna(0)
        
        # Encode Categorical String Columns
        cat_cols = [col for col in ["Division", "Region", "AsOnDate", "ComparedToDate"] if col in X.columns]
        X[cat_cols] = encoder.transform(X[cat_cols].astype(str))
        
        # Predict the scores using the trained Random Forest model
        predictions = model.predict(X)
        
        # Print the first few predictions to verify
        print("\n--- SAMPLE PREDICTIONS ---")
        for i in range(min(5, len(predictions))):
            print(f"Branch ID {branch_ids.iloc[i]}: Predicted Grade = {predictions[i]}")
            
        print("\nSUCCESS: Predictions generated! (Ready to push to TBL_ML_PredictedValues via SQL cursor)")
        
        conn.close()
        
    except Exception as e:
        print(f"ERROR generating predictions: {e}")

if __name__ == "__main__":
    run_predictions()
