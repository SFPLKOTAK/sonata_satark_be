-- ===============================================================================
-- SONATA SATARK - MONTHLY BRANCH RISK PREDICTION ARCHITECTURE SCHEMA
-- Database: sonata_connect / active_loan_performance
-- ===============================================================================

-- 1. STAGING TABLE (Populated on the 1st of every month with fresh SP features)
IF OBJECT_ID('dbo.TBL_Monthly_Branch_Feature_Staging', 'U') IS NOT NULL 
    DROP TABLE dbo.TBL_Monthly_Branch_Feature_Staging;

CREATE TABLE dbo.TBL_Monthly_Branch_Feature_Staging (
    AsOnDate                DATE          NOT NULL,
    Branch_ID               INT           NOT NULL,
    BranchName              VARCHAR(255)  NOT NULL,
    Zone                    VARCHAR(100)  NULL,
    Division                VARCHAR(100)  NULL,
    Region                  VARCHAR(100)  NULL,
    
    -- Volume & Portfolio Scale
    TotalLoans              INT           DEFAULT 0,
    TotalPrincipalOS        DECIMAL(18,2) DEFAULT 0.00,
    
    -- Arrears & NPA Raw Amounts
    Cur_NPA_Amt             DECIMAL(18,2) DEFAULT 0.00,
    Pri_NPA_Amt             DECIMAL(18,2) DEFAULT 0.00,
    NPA_Amt_Change_Pct      DECIMAL(10,2) DEFAULT 0.00,
    Cur_ArrearAmt           DECIMAL(18,2) DEFAULT 0.00,
    Pri_ArrearAmt           DECIMAL(18,2) DEFAULT 0.00,
    Arrear_Amt_Change_Pct   DECIMAL(10,2) DEFAULT 0.00,
    NewDefaultsThisMonth    INT           DEFAULT 0,
    WriteOffCount           INT           DEFAULT 0,
    GoodLoanCount           INT           DEFAULT 0,
    DeceasedCount           INT           DEFAULT 0,
    
    -- Operations & Collections
    CollectionRate_Pct      DECIMAL(10,2) DEFAULT 100.00,
    AvgDaysSinceCollection  INT           DEFAULT 0,
    AvgArrearDays           INT           DEFAULT 0,
    
    -- Concentration Risks
    TopCenter_NPAConc_Pct   DECIMAL(10,2) DEFAULT 0.00,
    TopStaff_NPAConc_Pct    DECIMAL(10,2) DEFAULT 0.00,
    RepeatBorrowerNPA       INT           DEFAULT 0,
    
    -- SQL Sub-Scores
    Score_NPARate           INT DEFAULT 0,
    Score_PAR0Rate          INT DEFAULT 0,
    Score_WriteOffRate      INT DEFAULT 0,
    Score_BucketDist        INT DEFAULT 0,
    Score_NPADrift          INT DEFAULT 0,
    Score_ArrearVelocity    INT DEFAULT 0,
    Score_WriteOffGrowth    INT DEFAULT 0,
    Score_NewDefaults       INT DEFAULT 0,
    Score_CollectionGap     INT DEFAULT 0,
    Score_CollectionRecency INT DEFAULT 0,
    Score_MissedInst        INT DEFAULT 0,
    Score_GoodLoanInverse   INT DEFAULT 0,
    Score_DeceasedRate      INT DEFAULT 0,
    Score_RepeatBorrowerNPA INT DEFAULT 0,
    Score_CenterConc        INT DEFAULT 0,
    Score_StaffConc         INT DEFAULT 0,
    Score_DAWriteOff        INT DEFAULT 0,
    SubScore_PortfolioQuality     INT DEFAULT 0,
    SubScore_TrendVelocity        INT DEFAULT 0,
    SubScore_CollectionEfficiency INT DEFAULT 0,
    SubScore_CustomerRisk         INT DEFAULT 0,
    SubScore_ConcentrationRisk    INT DEFAULT 0,
    
    -- Historical Previous Audit Score
    Prev_Score              DECIMAL(5,2) DEFAULT 50.00,
    
    CreatedAt               DATETIME DEFAULT GETDATE(),
    CONSTRAINT PK_TBL_Monthly_Branch_Feature_Staging PRIMARY KEY (AsOnDate, Branch_ID)
);


-- 2. ACTIVE PREDICTIONS TABLE (Stores latest month predictions for Dashboard UI)
IF OBJECT_ID('dbo.TBL_Monthly_Branch_Risk_Predictions', 'U') IS NOT NULL 
    DROP TABLE dbo.TBL_Monthly_Branch_Risk_Predictions;

CREATE TABLE dbo.TBL_Monthly_Branch_Risk_Predictions (
    Branch_ID                          INT           NOT NULL,
    BranchName                         VARCHAR(255)  NOT NULL,
    Zone                               VARCHAR(100)  NULL,
    Division                           VARCHAR(100)  NULL,
    Region                             VARCHAR(100)  NULL,
    AsOnDate                           DATE          NOT NULL,
    
    -- Model Output Predictions
    Predicted_Score                    DECIMAL(5,2)  NOT NULL,
    Predicted_Grade_From_Score         VARCHAR(10)   NOT NULL,
    Predicted_Grade_Direct_Classifier  VARCHAR(10)   NOT NULL,
    Final_Recommended_Grade            VARCHAR(10)   NOT NULL,
    Risk_Level                         VARCHAR(20)   NOT NULL, -- 'HIGH' or 'NORMAL'
    Risk_Warnings                      NVARCHAR(MAX) NULL,     -- JSON array or comma-separated warnings
    
    -- Metadata
    Model_Version                      VARCHAR(50)   DEFAULT 'XGBoost_v1.0',
    ScoredAt                           DATETIME      DEFAULT GETDATE(),
    CONSTRAINT PK_TBL_Monthly_Branch_Risk_Predictions PRIMARY KEY (Branch_ID)
);


-- 3. HISTORICAL PREDICTION ARCHIVE TABLE (Append-Only MoM Risk Trajectory)
IF OBJECT_ID('dbo.TBL_Branch_Risk_Prediction_History', 'U') IS NOT NULL 
    DROP TABLE dbo.TBL_Branch_Risk_Prediction_History;

CREATE TABLE dbo.TBL_Branch_Risk_Prediction_History (
    PredictionID                       BIGINT IDENTITY(1,1) NOT NULL,
    AsOnDate                           DATE          NOT NULL,
    Branch_ID                          INT           NOT NULL,
    BranchName                         VARCHAR(255)  NOT NULL,
    Zone                               VARCHAR(100)  NULL,
    Division                           VARCHAR(100)  NULL,
    Region                             VARCHAR(100)  NULL,
    
    -- Model Predictions
    Predicted_Score                    DECIMAL(5,2)  NOT NULL,
    Predicted_Grade                    VARCHAR(10)   NOT NULL,
    Risk_Level                         VARCHAR(20)   NOT NULL,
    Risk_Warnings                      NVARCHAR(MAX) NULL,
    
    -- Portfolio Metrics Snapshot at Scoring Time
    Cur_NPA_Amt                        DECIMAL(18,2) DEFAULT 0.00,
    TotalPrincipalOS                   DECIMAL(18,2) DEFAULT 0.00,
    CollectionRate_Pct                 DECIMAL(10,2) DEFAULT 100.00,
    
    -- Actual Field Audit Ground Truth (Updated when Auditor completes field audit)
    Actual_Field_Score                 DECIMAL(5,2)  NULL,
    Actual_Field_Grade                 VARCHAR(10)   NULL,
    Actual_Audit_Date                  DATE          NULL,
    
    ScoredAt                           DATETIME DEFAULT GETDATE(),
    CONSTRAINT PK_TBL_Branch_Risk_Prediction_History PRIMARY KEY (PredictionID),
    CONSTRAINT UQ_Branch_Month_History UNIQUE (AsOnDate, Branch_ID)
);

CREATE INDEX IX_PredictionHistory_Branch_Date ON dbo.TBL_Branch_Risk_Prediction_History (Branch_ID, AsOnDate DESC);
CREATE INDEX IX_PredictionHistory_RiskLevel ON dbo.TBL_Branch_Risk_Prediction_History (AsOnDate, Risk_Level);
