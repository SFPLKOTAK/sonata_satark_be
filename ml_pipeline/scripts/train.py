import os
import pyodbc
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import OrdinalEncoder
import joblib
import warnings

# Suppress pandas SQL warning about pyodbc
warnings.filterwarnings('ignore', message='.*pandas only supports SQLAlchemy connectable.*')

# Setup paths based on the ml_pipeline directory structure
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_OUTPUT = os.path.join(BASE_DIR, "models", "random_forest_model.pkl")
ENCODER_OUTPUT = os.path.join(BASE_DIR, "models", "categorical_encoder.pkl")

def get_db_connection():
    # Database credentials provided
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=172.17.130.164;"
        "DATABASE=Sonata_satark;"
        "UID=Paymee_VishalM;"
        "PWD=$V!sH@lM#231"
    )
    return pyodbc.connect(conn_str)

def train_model():
    print("Connecting to SQL Server to fetch training data...")
    try:
        conn = get_db_connection()
        query = "SELECT * FROM audit_branch_parameter_grade_training_data"
        df = pd.read_sql(query, conn)
        conn.close()
        print(f"Successfully loaded {len(df)} rows from the database.")
    except Exception as e:
        print(f"ERROR: Could not connect to the database or fetch data. Details:\n{e}")
        return

    # 2. Separate Features (X) and Target (Y)
    # Drop identifiers and text columns that the model can't process mathematically
    # Sort by Date so shift(1) correctly grabs the previous month chronologically
    if 'AsOnDate' in df.columns:
        df = df.sort_values(by=['Branch_ID', 'AsOnDate'])
        
    # Generate Previous Audit Score (Lag 1 per Branch)
    if 'Branch_ID' in df.columns and 'Score' in df.columns:
        df['Prev_Score'] = df.groupby('Branch_ID')['Score'].shift(1)
        df['Prev_Score'] = df['Prev_Score'].fillna(df['Score'])
    else:
        df['Prev_Score'] = 50.0

    columns_to_drop = [
        "Zone", "Branch_Name", "Branch_ID", "Month", "BRANCHID", "BranchName",
        "Grade", "RiskGrade", "Score", "RiskScore"
    ]
    
    # We want to predict the subjective Grade (A, B, C, D)
    if "Grade" not in df.columns:
        print("ERROR: 'Grade' column not found in dataset. This is required for training.")
        return

    # 1. Drop any rows where the Grade is missing
    initial_rows = len(df)
    df = df.dropna(subset=['Grade'])
    if len(df) < initial_rows:
        print(f"Dropped {initial_rows - len(df)} rows because their 'Grade' was missing (NULL).")

    Y = df["Grade"]
    
    # Drop columns if they exist in the dataframe
    X = df.drop(columns=[col for col in columns_to_drop if col in df.columns] + ["Grade"])
    
    # 2. Fill missing data with 0 (which is vastly superior to Median for financial risk data)
    X = X.fillna(0)
    
    # Encode Categorical String Columns
    cat_cols = [col for col in ["Division", "Region", "AsOnDate", "ComparedToDate"] if col in X.columns]
    print(f"Encoding categorical columns: {cat_cols}")
    encoder = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
    X[cat_cols] = encoder.fit_transform(X[cat_cols].astype(str))
    
    print(f"Training on {len(X.columns)} features...")

    # 3. Train/Test Split
    X_train, X_test, Y_train, Y_test = train_test_split(X, Y, test_size=0.2, random_state=42)

    # 4. Train the Random Forest Classifier
    print("Training Random Forest Classifier (this algorithm optimizes for exact letter grades)...")
    model = RandomForestClassifier(
        n_estimators=300, # Increased trees to 300 for maximum stability
        random_state=42,
        n_jobs=-1
    )
    
    model.fit(X_train, Y_train)
    
    print("Evaluating model on test set...")
    predictions = model.predict(X_test)
    
    # Calculate Classification Accuracy
    acc = accuracy_score(Y_test, predictions)
    report = classification_report(Y_test, predictions)

    print("\n==========================================")
    print("         MODEL ACCURACY REPORT            ")
    print("==========================================")
    print(f"Exact Letter Grade Match: {acc * 100:.2f}%\n")
    print("Detailed Grade Breakdown:")
    print(report)
    print("==========================================\n")

    # 6. Save the model and encoder to the models/ folder
    joblib.dump(model, MODEL_OUTPUT)
    joblib.dump(encoder, ENCODER_OUTPUT)
    print(f"Model successfully saved to {MODEL_OUTPUT}")
    print(f"Encoder successfully saved to {ENCODER_OUTPUT}")

if __name__ == "__main__":
    train_model()
