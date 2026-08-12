# Sonata Satark - Machine Learning Pipeline

Welcome to the Machine Learning module for the Sonata Satark Risk Predictor! 
This directory contains everything needed to train, evaluate, and run the ML models.

## Folder Structure

*   📁 **`data/`**: Place your raw CSV extracts from the database here (e.g., `branch_risk_score_data.csv`). This folder is ignored by Git to avoid uploading sensitive branch data.
*   📁 **`models/`**: When you run the training script, the saved AI model files (e.g., `random_forest_model.pkl`) will be output here. 
*   📁 **`notebooks/`**: For Jupyter Notebooks (`.ipynb`). Use this space for data exploration, testing new algorithms, and visualizing feature importance charts before putting them into production.
*   📁 **`scripts/`**: The actual production-ready Python code.
    *   `train.py`: The script to train the model from scratch on the CSV data.
    *   `predict.py`: The script used by the backend to generate scores for the current month.
*   📁 **`docs/`**: Contains the full architectural documentation, SQL schemas, and interactive HTML diagrams explaining how the system works.

## Quick Start
1. Export the latest 10-24 months of branch data using the SQL stored procedure.
2. Save it as `branch_risk_score_data.csv` inside the `data/` folder.
3. Run `python scripts/train.py` to train the Random Forest model and generate the `.pkl` file.
