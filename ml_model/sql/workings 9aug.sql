select *  into audit_branch_parameter_grade_training_data from  audit_branch_grade_history_final abgh
join audit_branch_parameter_training_data_9aug26 abpt on abpt.branchid = abgh.Branch_ID and abpt.asondate = abgh.month

select * from  audit_branch_parameter_grade_training_data


select * into ML_TBL_Monthly_Branch_Feature_Staging FROM audit_branch_parameter_training_data_9aug26 WHERE 1 = 0;

select * from ML_TBL_Monthly_Branch_Feature_Staging

alter table ML_TBL_Monthly_Branch_Feature_Staging
add zone varchar(50), division varchar(50), region varchar(50)

select * from ML_TBL_Monthly_Branch_Risk_Predictions where Predicted_Grade_From_Score = 'C'


select * from audit_branch_grade_history_final order by Branch_ID , month desc


EXEC sp_rename 
    'ML_TBL_Monthly_Branch_Feature_Staging.region',
    'Region',
    'COLUMN';

truncate table ML_TBL_Monthly_Branch_Feature_Staging


select * from audit_branch_grade_history_final

alter table audit_branch_grade_history_final
add isactual bit 

update audit_branch_grade_history_final set isactual = 1



select * from audit_branch_grade_history_final

;WITH BranchRange AS
(
    SELECT
        Branch_ID,
        MIN(Month) AS MinMonth,
        MAX(Month) AS MaxMonth
    FROM audit_branch_grade_history_final
    GROUP BY Branch_ID
),
Months AS
(
    SELECT
        Branch_ID,
        MinMonth AS Month,
        MaxMonth
    FROM BranchRange

    UNION ALL

    SELECT
        Branch_ID,
        DATEADD(MONTH, 1, Month),
        MaxMonth
    FROM Months
    WHERE Month < MaxMonth
),
MissingMonths AS
(
    SELECT
        m.Branch_ID,
        m.Month
    FROM Months m
    LEFT JOIN audit_branch_grade_history_final a
        ON a.Branch_ID = m.Branch_ID
        AND a.Month = m.Month
    WHERE a.Branch_ID IS NULL
),
FilledData AS
(
    SELECT
        mm.Branch_ID,
        mm.Month,

        p.Zone,
        p.Division,
        p.Region,
        p.Branch_Name,
        p.Grade,
        p.Score

    FROM MissingMonths mm

    OUTER APPLY
    (
        SELECT TOP 1
            a.Zone,
            a.Division,
            a.Region,
            a.Branch_Name,
            a.Grade,
            a.Score
        FROM audit_branch_grade_history_final a
        WHERE a.Branch_ID = mm.Branch_ID
          AND a.Month < mm.Month
        ORDER BY a.Month DESC
    ) p
)
INSERT INTO audit_branch_grade_history_final
(
    Zone,
    Division,
    Region,
    Branch_Name,
    Branch_ID,
    Month,
    Grade,
    Score,
    isactual
)
SELECT
    Zone,
    Division,
    Region,
    Branch_Name,
    Branch_ID,
    Month,
    Grade,
    Score,
    0
FROM FilledData
WHERE Grade IS NOT NULL
OPTION (MAXRECURSION 0);









CREATE TABLE audit_branch_parameter_training_data_9aug26
                  (
                        BRANCHID                        INT,
                        BranchName                      VARCHAR(255),

                        TotalLoans                      INT,
                        TotalPrincipalOS                DECIMAL(18,2),

						PAR_1_30_Amt        DECIMAL(18,2),
						PAR_31_60_Amt       DECIMAL(18,2),
						PAR_61_90_Amt       DECIMAL(18,2),


                        Score_NPARate                   INT,
                        Score_PAR0Rate                  INT,
                        Score_WriteOffRate              INT,
                        Score_BucketDist                INT,

                        Score_NPADrift                  INT,
                        Score_ArrearVelocity            INT,
                        Score_WriteOffGrowth            INT,
                        Score_NewDefaults               INT,

                        Score_CollectionGap             INT,
                        Score_CollectionRecency         INT,
                        Score_MissedInst                INT,

                        Score_GoodLoanInverse           INT,
                        Score_DeceasedRate              INT,
                        Score_RepeatBorrowerNPA         INT,

                        Score_CenterConc                INT,
                        Score_StaffConc                 INT,
                        Score_DAWriteOff                INT,

                        RiskScore                       INT,
                        RiskGrade                       VARCHAR(20),

                        SubScore_PortfolioQuality       INT,
                        SubScore_TrendVelocity          INT,
                        SubScore_CollectionEfficiency   INT,
                        SubScore_CustomerRisk           INT,
                        SubScore_ConcentrationRisk      INT,

                        NPALoans                        INT,
                        WriteOffCount                   INT,
                        GoodLoanCount                   INT,
                        DeceasedCount                   INT,

                        TotalArrearAmt                  DECIMAL(18,2),

                        Cur_NPA_Amt                     DECIMAL(18,2),
                        Pri_NPA_Amt                     DECIMAL(18,2),
                        NPA_Amt_Change_Pct              DECIMAL(10,2),

                        Cur_ArrearAmt                   DECIMAL(18,2),
                        Pri_ArrearAmt                   DECIMAL(18,2),
                        Arrear_Amt_Change_Pct           DECIMAL(10,2),

                        NewDefaultsThisMonth            INT,

                        CollectionRate_Pct              DECIMAL(10,2),
                        AvgDaysSinceCollection          INT,
                        AvgArrearDays                   INT,

                        RepeatBorrowerNPA               INT,

                        TopCenter_NPAConc_Pct           DECIMAL(10,2),
                        TopStaff_NPAConc_Pct            DECIMAL(10,2),
                  ActiveStaffCount                INT,
                  Staff_Caseload_Ratio            DECIMAL(10,2),
                  Staff_Overstay_12M_Pct          DECIMAL(10,2),
                  Staff_Tenure_Under3M_Pct        DECIMAL(10,2),
                  ActiveCenterCount               INT,
                  Avg_Center_Size                 DECIMAL(10,2),

                        AsOnDate                        DATE,
                        ComparedToDate                  DATE
                  );