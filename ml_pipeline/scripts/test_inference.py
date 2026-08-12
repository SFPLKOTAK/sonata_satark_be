import os
import pyodbc
import pandas as pd
import joblib
import random

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

print(f"Loading trained model from {MODEL_PATH}...")
if not os.path.exists(MODEL_PATH) or not os.path.exists(ENCODER_PATH):
    print("ERROR: Model or Encoder not found. Please run train.py first!")
    exit()

model = joblib.load(MODEL_PATH)
encoder = joblib.load(ENCODER_PATH)

print("Fetching a random sample of branches to test...")
conn = get_db_connection()
query = "SELECT * FROM audit_branch_parameter_grade_training_data"
df = pd.read_sql(query, conn)
conn.close()

# Drop rows where Grade is missing
df = df.dropna(subset=['Grade'])

# Sort by Date so shift(1) correctly grabs the previous month chronologically
if 'AsOnDate' in df.columns:
    df = df.sort_values(by=['Branch_ID', 'AsOnDate'])
    
# Generate Previous Audit Score (Lag 1 per Branch)
if 'Branch_ID' in df.columns and 'Score' in df.columns:
    df['Prev_Score'] = df.groupby('Branch_ID')['Score'].shift(1)
    df['Prev_Score'] = df['Prev_Score'].fillna(df['Score'])
else:
    df['Prev_Score'] = 50.0

# Randomly select 5 branches to test
sample_df = df.sample(n=5, random_state=random.randint(1, 1000))

# Prepare the data for the AI just like in train.py
columns_to_drop = [
    "Zone", "Branch_Name", "Branch_ID", "Month", "BRANCHID", "BranchName",
    "Grade", "RiskGrade", "Score", "RiskScore"
]

X = sample_df.drop(columns=[col for col in columns_to_drop if col in sample_df.columns])
X = X.fillna(0)

# Encode Categorical String Columns
cat_cols = [col for col in ["Division", "Region", "AsOnDate", "ComparedToDate"] if col in X.columns]
X[cat_cols] = encoder.transform(X[cat_cols].astype(str))

# Ask the AI to predict the scores
predictions = model.predict(X)

print("\n==============================================")
print("     AI PREDICTION vs ACTUAL SCORE TEST       ")
print("==============================================")

for i in range(5):
    branch = sample_df.iloc[i]['Branch_Name']
    actual = sample_df.iloc[i]['Grade']
    predicted = predictions[i]
    
    print(f"Branch: {branch}")
    print(f"   Real Database Audit Grade: {actual}")
    print(f"   AI's Predicted Grade:      {predicted}")
    print("-" * 46)
