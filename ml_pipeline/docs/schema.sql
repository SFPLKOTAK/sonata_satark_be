-- =========================================================================
-- MACHINE LEARNING PIPELINE SCHEMA
-- Purpose: Tables to support the Random Forest Risk Score Prediction Model
-- Location: d:\Sonata_satark\sonata_satark_be\satark\ml_model_docs\schema.sql
-- =========================================================================

-- -------------------------------------------------------------------------
-- 1. TBL_ML_TrainingData
-- Purpose: Stores the historical feature vectors used to TRAIN the Random Forest model.
--          (Schema updated to perfectly match the raw CSV extract).
-- -------------------------------------------------------------------------
CREATE TABLE [dbo].[TBL_ML_TrainingData] (
    [TrainingRowID] INT IDENTITY(1,1) PRIMARY KEY,
    
    -- Metadata / Identifiers
    [Zone] NVARCHAR(100),
    [Division] NVARCHAR(100),
    [Region] NVARCHAR(100),
    [Branch_Name] NVARCHAR(100),
    [Branch_ID] INT,
    [Month] DATE,
    [BRANCHID_2] INT,
    [BranchName_2] NVARCHAR(100),
    [AsOnDate] DATE,
    [ComparedToDate] DATE,

    -- Target Variables (Y)
    [Grade] NVARCHAR(10),
    [Score] FLOAT,
    [RiskScore] FLOAT,
    [RiskGrade] NVARCHAR(20),

    -- Feature Variables (X)
    [TotalLoans] INT,
    [TotalPrincipalOS] FLOAT,
    [Score_NPARate] FLOAT,
    [Score_PAR0Rate] FLOAT,
    [Score_WriteOffRate] FLOAT,
    [Score_BucketDist] FLOAT,
    [Score_NPADrift] FLOAT,
    [Score_ArrearVelocity] FLOAT,
    [Score_WriteOffGrowth] FLOAT,
    [Score_NewDefaults] FLOAT,
    [Score_CollectionGap] FLOAT,
    [Score_CollectionRecency] FLOAT,
    [Score_MissedInst] FLOAT,
    [Score_GoodLoanInverse] FLOAT,
    [Score_DeceasedRate] FLOAT,
    [Score_RepeatBorrowerNPA] FLOAT,
    [Score_CenterConc] FLOAT,
    [Score_StaffConc] FLOAT,
    [Score_DAWriteOff] FLOAT,
    [SubScore_PortfolioQuality] FLOAT,
    [SubScore_TrendVelocity] FLOAT,
    [SubScore_CollectionEfficiency] FLOAT,
    [SubScore_CustomerRisk] FLOAT,
    [SubScore_ConcentrationRisk] FLOAT,
    [NPALoans] INT,
    [WriteOffCount] INT,
    [GoodLoanCount] INT,
    [DeceasedCount] INT,
    [TotalArrearAmt] FLOAT,
    [Cur_NPA_Amt] FLOAT,
    [Pri_NPA_Amt] FLOAT,
    [NPA_Amt_Change_Pct] FLOAT,
    [Cur_ArrearAmt] FLOAT,
    [Pri_ArrearAmt] FLOAT,
    [Arrear_Amt_Change_Pct] FLOAT,
    [NewDefaultsThisMonth] INT,
    [CollectionRate_Pct] FLOAT,
    [AvgDaysSinceCollection] FLOAT,
    [AvgArrearDays] FLOAT,
    [RepeatBorrowerNPA] INT, 
    [TopCenter_NPAConc_Pct] FLOAT,
    [TopStaff_NPAConc_Pct] FLOAT,

    [CreatedAt] DATETIME DEFAULT GETDATE()
);
GO
CREATE INDEX IX_ML_TrainingData_DateBranch ON [dbo].[TBL_ML_TrainingData]([Month], [Branch_ID]);
GO

-- -------------------------------------------------------------------------
-- 2. TBL_ML_CurrentMonth_Features
-- Purpose: Stores the *current* month's features ready for inference.
-- -------------------------------------------------------------------------
CREATE TABLE [dbo].[TBL_ML_CurrentMonth_Features] (
    [Branch_ID] INT PRIMARY KEY,
    
    [Zone] NVARCHAR(100),
    [Division] NVARCHAR(100),
    [Region] NVARCHAR(100),
    [Branch_Name] NVARCHAR(100),
    [Month] DATE,
    [AsOnDate] DATE,
    [ComparedToDate] DATE,

    -- Feature Variables (X)
    [TotalLoans] INT,
    [TotalPrincipalOS] FLOAT,
    [Score_NPARate] FLOAT,
    [Score_PAR0Rate] FLOAT,
    [Score_WriteOffRate] FLOAT,
    [Score_BucketDist] FLOAT,
    [Score_NPADrift] FLOAT,
    [Score_ArrearVelocity] FLOAT,
    [Score_WriteOffGrowth] FLOAT,
    [Score_NewDefaults] FLOAT,
    [Score_CollectionGap] FLOAT,
    [Score_CollectionRecency] FLOAT,
    [Score_MissedInst] FLOAT,
    [Score_GoodLoanInverse] FLOAT,
    [Score_DeceasedRate] FLOAT,
    [Score_RepeatBorrowerNPA] FLOAT,
    [Score_CenterConc] FLOAT,
    [Score_StaffConc] FLOAT,
    [Score_DAWriteOff] FLOAT,
    [SubScore_PortfolioQuality] FLOAT,
    [SubScore_TrendVelocity] FLOAT,
    [SubScore_CollectionEfficiency] FLOAT,
    [SubScore_CustomerRisk] FLOAT,
    [SubScore_ConcentrationRisk] FLOAT,
    [NPALoans] INT,
    [WriteOffCount] INT,
    [GoodLoanCount] INT,
    [DeceasedCount] INT,
    [TotalArrearAmt] FLOAT,
    [Cur_NPA_Amt] FLOAT,
    [Pri_NPA_Amt] FLOAT,
    [NPA_Amt_Change_Pct] FLOAT,
    [Cur_ArrearAmt] FLOAT,
    [Pri_ArrearAmt] FLOAT,
    [Arrear_Amt_Change_Pct] FLOAT,
    [NewDefaultsThisMonth] INT,
    [CollectionRate_Pct] FLOAT,
    [AvgDaysSinceCollection] FLOAT,
    [AvgArrearDays] FLOAT,
    [RepeatBorrowerNPA] INT,
    [TopCenter_NPAConc_Pct] FLOAT,
    [TopStaff_NPAConc_Pct] FLOAT,

    [UpdatedAt] DATETIME DEFAULT GETDATE()
);
GO

-- -------------------------------------------------------------------------
-- 3. TBL_ML_PredictedValues
-- Purpose: The Python script writes its final predictions here. 
--          The Audit Planner UI reads from this table for the latest scores.
-- -------------------------------------------------------------------------
CREATE TABLE [dbo].[TBL_ML_PredictedValues] (
    [Branch_ID] INT PRIMARY KEY,
    [PredictionDate] DATE NOT NULL,
    
    [Predicted_Risk_Score] FLOAT NOT NULL,
    [Predicted_Risk_Grade] NVARCHAR(20) NOT NULL, -- e.g., 'LOW', 'CRITICAL'
    [Audit_Days_Required] INT,

    [Model_Version] NVARCHAR(50),
    [LastUpdated] DATETIME DEFAULT GETDATE(),

    CONSTRAINT FK_Predicted_Branch FOREIGN KEY ([Branch_ID]) REFERENCES [dbo].[TBL_ML_CurrentMonth_Features]([Branch_ID])
);
GO

-- -------------------------------------------------------------------------
-- 4. TBL_ML_PredictedValues_History
-- Purpose: Audit trail of every prediction ever made for reporting/drift analysis.
-- -------------------------------------------------------------------------
CREATE TABLE [dbo].[TBL_ML_PredictedValues_History] (
    [HistoryID] INT IDENTITY(1,1) PRIMARY KEY,
    [Branch_ID] INT NOT NULL,
    [PredictionDate] DATE NOT NULL,
    
    [Predicted_Risk_Score] FLOAT NOT NULL,
    [Predicted_Risk_Grade] NVARCHAR(20) NOT NULL,
    
    [Actual_Risk_Score_Obtained] FLOAT, 
    
    [Model_Version] NVARCHAR(50),
    [LoggedAt] DATETIME DEFAULT GETDATE()
);
GO
CREATE INDEX IX_ML_PredHistory_Branch ON [dbo].[TBL_ML_PredictedValues_History]([Branch_ID], [PredictionDate]);
GO
