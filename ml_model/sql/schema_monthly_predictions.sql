-- ===============================================================================
-- SONATA SATARK - MONTHLY BRANCH RISK PREDICTION ARCHITECTURE SCHEMA
-- Database: sonata_connect / active_loan_performance
-- Prefix: ML_
-- ===============================================================================

-- 1. STAGING TABLE (Exact Database Match: dbo.ML_TBL_Monthly_Branch_Feature_Staging)
IF OBJECT_ID('dbo.ML_TBL_Monthly_Branch_Feature_Staging', 'U') IS NOT NULL 
    DROP TABLE dbo.ML_TBL_Monthly_Branch_Feature_Staging;

CREATE TABLE dbo.ML_TBL_Monthly_Branch_Feature_Staging (
    BRANCHID                       INT           NULL,
    BranchName                     VARCHAR(255)  NULL,
    TotalLoans                     INT           NULL,
    TotalPrincipalOS               DECIMAL(18,2) NULL,
    PAR_1_30_Amt                   DECIMAL(18,2) NULL,
    PAR_31_60_Amt                  DECIMAL(18,2) NULL,
    PAR_61_90_Amt                  DECIMAL(18,2) NULL,
    
    -- SQL Sub-Scores
    Score_NPARate                  INT           NULL,
    Score_PAR0Rate                 INT           NULL,
    Score_WriteOffRate             INT           NULL,
    Score_BucketDist               INT           NULL,
    Score_NPADrift                 INT           NULL,
    Score_ArrearVelocity           INT           NULL,
    Score_WriteOffGrowth           INT           NULL,
    Score_NewDefaults              INT           NULL,
    Score_CollectionGap            INT           NULL,
    Score_CollectionRecency        INT           NULL,
    Score_MissedInst               INT           NULL,
    Score_GoodLoanInverse          INT           NULL,
    Score_DeceasedRate             INT           NULL,
    Score_RepeatBorrowerNPA        INT           NULL,
    Score_CenterConc               INT           NULL,
    Score_StaffConc                INT           NULL,
    Score_DAWriteOff               INT           NULL,
    RiskScore                      INT           NULL,
    RiskGrade                      VARCHAR(20)   NULL,
    
    SubScore_PortfolioQuality      INT           NULL,
    SubScore_TrendVelocity         INT           NULL,
    SubScore_CollectionEfficiency  INT           NULL,
    SubScore_CustomerRisk          INT           NULL,
    SubScore_ConcentrationRisk     INT           NULL,
    
    -- Raw Metrics & Ratios
    NPALoans                       INT           NULL,
    WriteOffCount                  INT           NULL,
    GoodLoanCount                  INT           NULL,
    DeceasedCount                  INT           NULL,
    TotalArrearAmt                 DECIMAL(18,2) NULL,
    Cur_NPA_Amt                    DECIMAL(18,2) NULL,
    Pri_NPA_Amt                    DECIMAL(18,2) NULL,
    NPA_Amt_Change_Pct             DECIMAL(10,2) NULL,
    Cur_ArrearAmt                  DECIMAL(18,2) NULL,
    Pri_ArrearAmt                  DECIMAL(18,2) NULL,
    Arrear_Amt_Change_Pct          DECIMAL(10,2) NULL,
    NewDefaultsThisMonth           INT           NULL,
    CollectionRate_Pct             DECIMAL(10,2) NULL,
    AvgDaysSinceCollection         INT           NULL,
    AvgArrearDays                  INT           NULL,
    RepeatBorrowerNPA              INT           NULL,
    TopCenter_NPAConc_Pct          DECIMAL(10,2) NULL,
    TopStaff_NPAConc_Pct           DECIMAL(10,2) NULL,
    
    -- Staff Operations & Tenure Risks
    ActiveStaffCount               INT           NULL,
    Staff_Caseload_Ratio           DECIMAL(10,2) NULL,
    Staff_Overstay_12M_Pct         DECIMAL(10,2) NULL,
    Staff_Tenure_Under3M_Pct       DECIMAL(10,2) NULL,
    
    -- Center Discipline Risks
    ActiveCenterCount              INT           NULL,
    Avg_Center_Size                DECIMAL(10,2) NULL,
    
    -- Date Slices
    AsOnDate                       DATE          NULL,
    ComparedToDate                 DATE          NULL
);


-- 2. ACTIVE PREDICTIONS TABLE (Stores latest month predictions for Dashboard UI)
IF OBJECT_ID('dbo.ML_TBL_Monthly_Branch_Risk_Predictions', 'U') IS NOT NULL 
    DROP TABLE dbo.ML_TBL_Monthly_Branch_Risk_Predictions;

CREATE TABLE dbo.ML_TBL_Monthly_Branch_Risk_Predictions (
    Branch_ID                          INT           NOT NULL,
    BranchName                         VARCHAR(255)  NULL,
    Zone                               VARCHAR(100)  NULL,
    Division                           VARCHAR(100)  NULL,
    Region                             VARCHAR(100)  NULL,
    AsOnDate                           DATE          NULL,
    
    -- Model Output Predictions
    Predicted_Score                    DECIMAL(5,2)  NULL,
    Predicted_Grade_From_Score         VARCHAR(10)   NULL,
    Predicted_Grade_Direct_Classifier  VARCHAR(10)   NULL,
    Final_Recommended_Grade            VARCHAR(10)   NULL,
    Risk_Level                         VARCHAR(20)   NULL, -- 'HIGH' or 'NORMAL'
    Risk_Warnings                      NVARCHAR(MAX) NULL, -- JSON array of warnings
    
    -- Key Operational Drivers Snapshot
    Key_points_impacting_risk          NVARCHAR(MAX) NULL, -- Comma-separated list of all risky factors impacting that score

    -- Metadata
    Model_Version                      VARCHAR(50)   DEFAULT 'StackingEnsemble_v2.0',
    ScoredAt                           DATETIME      DEFAULT GETDATE(),
    CONSTRAINT PK_ML_TBL_Monthly_Branch_Risk_Predictions PRIMARY KEY (Branch_ID)
);


-- 3. HISTORICAL PREDICTION ARCHIVE TABLE (Append-Only MoM Risk Trajectory)
IF OBJECT_ID('dbo.ML_TBL_Branch_Risk_Prediction_History', 'U') IS NOT NULL 
    DROP TABLE dbo.ML_TBL_Branch_Risk_Prediction_History;

CREATE TABLE dbo.ML_TBL_Branch_Risk_Prediction_History (
    PredictionID                       BIGINT IDENTITY(1,1) NOT NULL,
    Branch_ID                          INT           NOT NULL,
    BranchName                         VARCHAR(255)  NULL,
    Zone                               VARCHAR(100)  NULL,
    Division                           VARCHAR(100)  NULL,
    Region                             VARCHAR(100)  NULL,
    AsOnDate                           DATE          NOT NULL,
    
    -- Model Output Predictions (Identical Structure to Active Predictions Table)
    Predicted_Score                    DECIMAL(5,2)  NULL,
    Predicted_Grade_From_Score         VARCHAR(10)   NULL,
    Predicted_Grade_Direct_Classifier  VARCHAR(10)   NULL,
    Final_Recommended_Grade            VARCHAR(10)   NULL,
    Risk_Level                         VARCHAR(20)   NULL, -- 'HIGH' or 'NORMAL'
    Risk_Warnings                      NVARCHAR(MAX) NULL, -- JSON array of warnings
    
    -- Key Operational Drivers Snapshot
    Key_points_impacting_risk          NVARCHAR(MAX) NULL, -- Comma-separated list of all risky factors impacting that score
    
    -- Actual Field Audit Ground Truth (Updated when Auditor completes field audit)
    Actual_Field_Score                 DECIMAL(5,2)  NULL,
    Actual_Field_Grade                 VARCHAR(10)   NULL,
    Actual_Audit_Date                  DATE          NULL,
    
    -- Metadata
    Model_Version                      VARCHAR(50)   DEFAULT 'StackingEnsemble_v2.0',
    ScoredAt                           DATETIME      DEFAULT GETDATE(),
    CONSTRAINT PK_ML_TBL_Branch_Risk_Prediction_History PRIMARY KEY (PredictionID),
    CONSTRAINT UQ_ML_Branch_Month_History UNIQUE (AsOnDate, Branch_ID)
);

CREATE INDEX IX_ML_PredictionHistory_Branch_Date ON dbo.ML_TBL_Branch_Risk_Prediction_History (Branch_ID, AsOnDate DESC);
CREATE INDEX IX_ML_PredictionHistory_RiskLevel ON dbo.ML_TBL_Branch_Risk_Prediction_History (AsOnDate, Risk_Level);
