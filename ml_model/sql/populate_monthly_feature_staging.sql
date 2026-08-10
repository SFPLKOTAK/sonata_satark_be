begin 
      declare @asondate date = '2026-08-01'

      while @asondate < '2026-08-02'
      begin 
            print @asondate

            RAISERROR('date taken from here', 0, 1) WITH NOWAIT;


            DECLARE @PriorDate  DATE     = DATEADD(DAY, -30, @AsOnDate);
            DECLARE @Msg        NVARCHAR(200);
            DECLARE @StartTime  DATETIME = GETDATE();
            DECLARE @StepTime   DATETIME;

            -- ─────────────────────────────────────────────────────────
            -- HELPER MACRO: prints message + elapsed seconds
            -- ─────────────────────────────────────────────────────────
            -- We use RAISERROR severity 0 WITH NOWAIT so messages flush
            -- immediately to the client (PRINT buffers until SP ends).
            -- ─────────────────────────────────────────────────────────

            RAISERROR('====================================================', 0, 1) WITH NOWAIT;
            SET @Msg = '  SP_BranchRiskScore START | Division: ' +
                         + ' | AsOnDate: ' + CONVERT(VARCHAR,@AsOnDate,23)
                         + ' | PriorDate: ' + CONVERT(VARCHAR,@PriorDate,23);
            RAISERROR(@Msg, 0, 1) WITH NOWAIT;
            RAISERROR('====================================================', 0, 1) WITH NOWAIT;

            -- =========================================================
            -- STEP 1 : Base snapshot — single scan, 2 date slices
            -- =========================================================
            SET @StepTime = GETDATE();
            RAISERROR('  [Step 1/6] Reading base snapshot from source table...', 0, 1) WITH NOWAIT;

            IF OBJECT_ID('tempdb..#Base') IS NOT NULL DROP TABLE #Base;

            SELECT
                  BRANCH,
                  BRANCHID,
                  ASONDATE,
                  CASE WHEN ASONDATE = @AsOnDate  THEN 1 ELSE 0 END AS IsCurrentDate,
                  CASE WHEN ASONDATE = @PriorDate THEN 1 ELSE 0 END AS IsPriorDate,
                  DISBURSEMENTID,
                  CUSTSTATUS,
                  DeathDate,
                  ISWRITEOFF,
                  WRITEOFFAMT,
                  LOANITERATIONNO,
                  GOODLOANCUSTOMER,
                  PINCIPALOS,
                  DISBURSEDAMT,
                  PRINCIPLECOLLECTED,
                  INTERESTCOLLECTED,
                  TOTALINSTALLMENT,
                  INSTALLMENTSINARREAR,
                  ARREARDAYS,
                  PRINCIPALARREAR,
                  INTERESTARREAR,
                  ARREARAMOUNT,
                  DEFAULTAMOUNT,
                  RISK,
                  [1 - 30 DAYS],
                  [31 - 60 DAYS],
                  [61 - 90 DAYS],
                  [91 - 120 DAYS],
                  [121 - 180 DAYS],
                  [181 - 365 DAYS],
                  [MORE THAN365 DAYS],
                  LASTCOLLECTIONDATE,
                  CenterID,
                  StaffID,
                  PRODUCTNAME,
                  FUNDERTYPE
            INTO #Base
            FROM Active_Loan_Performance..TBL_ActiveLoansPerformanceData act
            join sonata_connect..audit_branch_grade_history abgh on abgh.Branch_ID = act.BRANCHID
            WHERE  ASONDATE IN (@AsOnDate, @PriorDate);

            SET @Msg = '  [Step 1/6] DONE — ' + CAST(@@ROWCOUNT AS VARCHAR)
                         + ' rows loaded | Elapsed: '
                         + CAST(DATEDIFF(SECOND, @StepTime, GETDATE()) AS VARCHAR) + 's';
            RAISERROR(@Msg, 0, 1) WITH NOWAIT;

            -- =========================================================
            -- STEP 2 : Portfolio quality metrics  (current date only)
            -- =========================================================
            SET @StepTime = GETDATE();
            RAISERROR('  [Step 2/6] Calculating portfolio quality metrics...', 0, 1) WITH NOWAIT;

            IF OBJECT_ID('tempdb..#PortfolioQuality') IS NOT NULL DROP TABLE #PortfolioQuality;

            SELECT
                  BRANCH,
                  BRANCHID,
                  --Division,
                  COUNT(DISTINCT DISBURSEMENTID)                                         AS TotalLoans,
                  SUM(CASE WHEN ISWRITEOFF = 1 THEN 1 ELSE 0 END)                       AS WriteOffCount,
                  SUM(CASE WHEN ARREARDAYS > 0  THEN 1 ELSE 0 END)                      AS LoansInArrear,
                  SUM(CASE WHEN ARREARDAYS >= 90 AND ISWRITEOFF = 0 THEN 1 ELSE 0 END)  AS NPALoans,
                  SUM(ISNULL(PINCIPALOS, 0))                                             AS TotalPrincipalOS,
                  SUM(CASE WHEN ARREARDAYS BETWEEN 1  AND 30
                               THEN ISNULL(PINCIPALOS,0) ELSE 0 END)                        AS PAR_1_30_Amt,
                  SUM(CASE WHEN ARREARDAYS BETWEEN 31 AND 60
                               THEN ISNULL(PINCIPALOS,0) ELSE 0 END)                        AS PAR_31_60_Amt,
                  SUM(CASE WHEN ARREARDAYS BETWEEN 61 AND 90
                               THEN ISNULL(PINCIPALOS,0) ELSE 0 END)                        AS PAR_61_90_Amt,
                  SUM(CASE WHEN ARREARDAYS > 90 AND ISWRITEOFF = 0
                               THEN ISNULL(PINCIPALOS,0) ELSE 0 END)                        AS PAR_90Plus_Amt,
                  SUM(CASE WHEN ISWRITEOFF = 1
                               THEN COALESCE(WRITEOFFAMT, PINCIPALOS, 0) ELSE 0 END)        AS WriteOffAmt,
                  SUM(ISNULL(ARREARAMOUNT, 0))                                           AS TotalArrearAmt,
                  SUM(CASE WHEN DeathDate IS NOT NULL THEN 1 ELSE 0 END)                AS DeceasedCount,
                  SUM(CASE WHEN GOODLOANCUSTOMER = 1  THEN 1 ELSE 0 END)                AS GoodLoanCount,
                  SUM(
                        ISNULL([1 - 30 DAYS],      0) * 1 +
                        ISNULL([31 - 60 DAYS],     0) * 2 +
                        ISNULL([61 - 90 DAYS],     0) * 3 +
                        ISNULL([91 - 120 DAYS],    0) * 4 +
                        ISNULL([121 - 180 DAYS],   0) * 5 +
                        ISNULL([181 - 365 DAYS],   0) * 6 +
                        ISNULL([MORE THAN365 DAYS],0) * 7 +
                        ISNULL(ISWRITEOFF,         0) * 8
                  )                                                                      AS WeightedBucketScore
            INTO #PortfolioQuality
            FROM #Base
            WHERE IsCurrentDate = 1
            GROUP BY BRANCH, BRANCHID;

            SET @Msg = '  [Step 2/6] DONE — ' + CAST(@@ROWCOUNT AS VARCHAR)
                         + ' branches | Elapsed: '
                         + CAST(DATEDIFF(SECOND, @StepTime, GETDATE()) AS VARCHAR) + 's';
            RAISERROR(@Msg, 0, 1) WITH NOWAIT;

            -- =========================================================
            -- STEP 3 : Trend / velocity metrics  (current vs prior)
            -- =========================================================
            SET @StepTime = GETDATE();
            RAISERROR('  [Step 3/6] Calculating trend and velocity metrics (MoM)...', 0, 1) WITH NOWAIT;

            IF OBJECT_ID('tempdb..#TrendMetrics') IS NOT NULL DROP TABLE #TrendMetrics;

            SELECT
                  BRANCH,
                  BRANCHID,
                  SUM(CASE WHEN IsCurrentDate=1
                               THEN ISNULL(PINCIPALOS,0)    ELSE 0 END)                     AS Cur_PrincipalOS,
                  SUM(CASE WHEN IsCurrentDate=1 AND ARREARDAYS > 0
                               THEN ISNULL(PINCIPALOS,0)    ELSE 0 END)                     AS Cur_PAR0_Amt,
                  SUM(CASE WHEN IsCurrentDate=1 AND ARREARDAYS >= 90 AND ISWRITEOFF=0
                               THEN ISNULL(PINCIPALOS,0)    ELSE 0 END)                     AS Cur_NPA_Amt,
                  SUM(CASE WHEN IsCurrentDate=1
                               THEN ISNULL(ARREARAMOUNT,0)  ELSE 0 END)                     AS Cur_ArrearAmt,
                  SUM(CASE WHEN IsCurrentDate=1 AND ISWRITEOFF=1
                               THEN ISNULL(WRITEOFFAMT,0)   ELSE 0 END)                     AS Cur_WriteOffAmt,
                  COUNT(DISTINCT CASE WHEN IsCurrentDate=1 AND ISWRITEOFF=1
                               THEN DISBURSEMENTID END)                                      AS Cur_WriteOffCount,
                  SUM(CASE WHEN IsPriorDate=1
                               THEN ISNULL(PINCIPALOS,0)    ELSE 0 END)                     AS Pri_PrincipalOS,
                  SUM(CASE WHEN IsPriorDate=1 AND ARREARDAYS > 0
                               THEN ISNULL(PINCIPALOS,0)    ELSE 0 END)                     AS Pri_PAR0_Amt,
                  SUM(CASE WHEN IsPriorDate=1 AND ARREARDAYS >= 90 AND ISWRITEOFF=0
                               THEN ISNULL(PINCIPALOS,0)    ELSE 0 END)                     AS Pri_NPA_Amt,
                  SUM(CASE WHEN IsPriorDate=1
                               THEN ISNULL(ARREARAMOUNT,0)  ELSE 0 END)                     AS Pri_ArrearAmt,
                  SUM(CASE WHEN IsPriorDate=1 AND ISWRITEOFF=1
                               THEN ISNULL(WRITEOFFAMT,0)   ELSE 0 END)                     AS Pri_WriteOffAmt,
                  COUNT(DISTINCT CASE WHEN IsPriorDate=1 AND ISWRITEOFF=1
                               THEN DISBURSEMENTID END)                                      AS Pri_WriteOffCount,
                  COUNT(DISTINCT CASE WHEN IsCurrentDate=1 AND ARREARDAYS BETWEEN 1 AND 30
                               THEN DISBURSEMENTID END)                                      AS NewDefaultsThisMonth,
                  COUNT(DISTINCT CASE WHEN IsCurrentDate=1 AND ARREARDAYS BETWEEN 31 AND 90
                               THEN DISBURSEMENTID END)                                      AS Cur_MidBucketCount,
                  COUNT(DISTINCT CASE WHEN IsPriorDate=1  AND ARREARDAYS BETWEEN 1  AND 30
                               THEN DISBURSEMENTID END)                                      AS Pri_EarlyBucketCount
            INTO #TrendMetrics
            FROM #Base
            GROUP BY BRANCH, BRANCHID;

            SET @Msg = '  [Step 3/6] DONE — ' + CAST(@@ROWCOUNT AS VARCHAR)
                         + ' branches | Elapsed: '
                         + CAST(DATEDIFF(SECOND, @StepTime, GETDATE()) AS VARCHAR) + 's';
            RAISERROR(@Msg, 0, 1) WITH NOWAIT;

            -- =========================================================
            -- STEP 4 : Collection efficiency metrics  (current only)
            -- =========================================================
            SET @StepTime = GETDATE();
            RAISERROR('  [Step 4/6] Calculating collection efficiency metrics...', 0, 1) WITH NOWAIT;

            IF OBJECT_ID('tempdb..#CollectionMetrics') IS NOT NULL DROP TABLE #CollectionMetrics;

            SELECT
                  BRANCH,
                  BRANCHID,
                  SUM(ISNULL(TOTALINSTALLMENT, 0))                                       AS TotalDue,
                  SUM(ISNULL(PRINCIPLECOLLECTED,0) + ISNULL(INTERESTCOLLECTED,0))        AS TotalCollected,
                  SUM(ISNULL(INSTALLMENTSINARREAR,0))                                    AS TotalInstInArrear,
                  COUNT(DISTINCT CASE WHEN INSTALLMENTSINARREAR > 0
                               THEN DISBURSEMENTID END)                                      AS LoansWithMissedInst,
                  COUNT(DISTINCT DISBURSEMENTID)                                         AS TotalLoansForColl,
                  AVG(DATEDIFF(DAY, LASTCOLLECTIONDATE, @AsOnDate))                     AS AvgDaysSinceCollection,
                  MAX(DATEDIFF(DAY, LASTCOLLECTIONDATE, @AsOnDate))                     AS MaxDaysSinceCollection,
                  AVG(CASE WHEN ARREARDAYS > 0
                               THEN CAST(ARREARDAYS AS FLOAT) END)                          AS AvgArrearDays,
                  AVG(CAST(ISNULL(INSTALLMENTSINARREAR,0) AS FLOAT))                   AS AvgInstallmentsInArrear
            INTO #CollectionMetrics
            FROM #Base
            WHERE IsCurrentDate = 1
            GROUP BY BRANCH, BRANCHID;

            SET @Msg = '  [Step 4/6] DONE — ' + CAST(@@ROWCOUNT AS VARCHAR)
                         + ' branches | Elapsed: '
                         + CAST(DATEDIFF(SECOND, @StepTime, GETDATE()) AS VARCHAR) + 's';
            RAISERROR(@Msg, 0, 1) WITH NOWAIT;

            -- =========================================================
            -- STEP 5 : Customer & concentration risk  (current only)
            --   Uses RANK() window function instead of OUTER APPLY
            --   to avoid re-scanning #Base multiple times.
            -- =========================================================
            SET @StepTime = GETDATE();
            RAISERROR('  [Step 5/6] Calculating concentration and customer risk...', 0, 1) WITH NOWAIT;

            IF OBJECT_ID('tempdb..#ConcentrationRisk') IS NOT NULL DROP TABLE #ConcentrationRisk;

            -- Pre-aggregate NPA counts by branch + center / staff / product
            -- using RANK() so we can pick the top-1 without OUTER APPLY
            WITH NPA_Current AS (
                  SELECT
                        BRANCH, BRANCHID,
                        CenterID, StaffID, PRODUCTNAME,
                        ISWRITEOFF, FUNDERTYPE,
                        LOANITERATIONNO, ARREARDAYS,
                        DISBURSEMENTID
                  FROM #Base
                  WHERE IsCurrentDate = 1
            ),
            CenterCounts AS (
                  SELECT BRANCH, BRANCHID, CenterID,
                           COUNT(*) AS CenterNPACount,
                           RANK() OVER (PARTITION BY BRANCH, BRANCHID ORDER BY COUNT(*) DESC) AS Rnk
                  FROM NPA_Current WHERE ARREARDAYS >= 90
                  GROUP BY BRANCH, BRANCHID, CenterID
            ),
            StaffCounts AS (
                  SELECT BRANCH, BRANCHID, StaffID,
                           COUNT(*) AS StaffNPACount,
                           RANK() OVER (PARTITION BY BRANCH, BRANCHID ORDER BY COUNT(*) DESC) AS Rnk
                  FROM NPA_Current WHERE ARREARDAYS >= 90
                  GROUP BY BRANCH, BRANCHID, StaffID
            ),
            ProductCounts AS (
                  SELECT BRANCH, BRANCHID, PRODUCTNAME,
                           COUNT(*) AS ProdNPACount,
                           RANK() OVER (PARTITION BY BRANCH, BRANCHID ORDER BY COUNT(*) DESC) AS Rnk
                  FROM NPA_Current WHERE ARREARDAYS >= 90
                  GROUP BY BRANCH, BRANCHID, PRODUCTNAME
            ),
            TopCenter  AS (SELECT BRANCH, BRANCHID, CenterNPACount FROM CenterCounts  WHERE Rnk = 1),
            TopStaff   AS (SELECT BRANCH, BRANCHID, StaffNPACount  FROM StaffCounts   WHERE Rnk = 1),
            TopProduct AS (SELECT BRANCH, BRANCHID, ProdNPACount   FROM ProductCounts WHERE Rnk = 1),
            BranchTotals AS (
                  SELECT
                        BRANCH, act.BRANCHID,
                        COUNT(DISTINCT DISBURSEMENTID)                                     AS TotalForConc,
                        COUNT(DISTINCT StaffID)                                            AS ActiveStaffCount,
                  COUNT(DISTINCT CenterID)                                           AS ActiveCenterCount,
                        SUM(CASE WHEN ARREARDAYS >= 90 THEN 1 ELSE 0 END)                 AS TotalNPALoans,
                        SUM(CASE WHEN LOANITERATIONNO >= 3 AND ARREARDAYS >= 90
                                     THEN 1 ELSE 0 END)                                       AS RepeatBorrowerNPA,
                        SUM(CASE WHEN ISWRITEOFF = 1
                                           AND FUNDERTYPE LIKE '%Direct Assignment%'
                                     THEN 1 ELSE 0 END)                                       AS DAWriteOffCount,
                  COUNT(DISTINCT CASE WHEN u.BranchJoinDate IS NOT NULL AND DATEDIFF(DAY, u.BranchJoinDate, @AsOnDate) > 365 THEN act.StaffID END) AS StaffOverstayCount,
                  COUNT(DISTINCT CASE WHEN u.BranchJoinDate IS NOT NULL AND DATEDIFF(DAY, u.BranchJoinDate, @AsOnDate) < 90 THEN act.StaffID END) AS StaffNewTenureCount
                  FROM NPA_Current act
                  LEFT JOIN sonata_Dec..mst_usertbl u ON act.StaffID = u.UserID
                  GROUP BY act.BRANCH, act.BRANCHID
            )
            SELECT
                  bt.BRANCH,
                  bt.BRANCHID,
                  bt.TotalForConc,
                  bt.TotalNPALoans,
                  bt.RepeatBorrowerNPA,
                  bt.DAWriteOffCount,
                  bt.ActiveStaffCount,
                  CAST(bt.TotalForConc * 1.0 / NULLIF(bt.ActiveStaffCount, 0) AS DECIMAL(10,2)) AS Staff_Caseload_Ratio,
                  CAST(ISNULL(bt.StaffOverstayCount, 0) * 100.0 / NULLIF(bt.ActiveStaffCount, 0) AS DECIMAL(10,2)) AS Staff_Overstay_12M_Pct,
                  CAST(ISNULL(bt.StaffNewTenureCount, 0) * 100.0 / NULLIF(bt.ActiveStaffCount, 0) AS DECIMAL(10,2)) AS Staff_Tenure_Under3M_Pct,
                  bt.ActiveCenterCount,
                  CAST(bt.TotalForConc * 1.0 / NULLIF(bt.ActiveCenterCount, 0) AS DECIMAL(10,2)) AS Avg_Center_Size,
                  ISNULL(tc.CenterNPACount,0) * 1.0
                        / NULLIF(bt.TotalNPALoans,0)                                      AS TopCenterNPAConc,
                  ISNULL(ts.StaffNPACount, 0) * 1.0
                        / NULLIF(bt.TotalNPALoans,0)                                      AS TopStaffNPAConc,
                  ISNULL(tp.ProdNPACount,  0) * 1.0
                        / NULLIF(bt.TotalNPALoans,0)                                      AS TopProductNPAConc
            INTO #ConcentrationRisk
            FROM BranchTotals bt
            LEFT JOIN TopCenter  tc ON bt.BRANCH = tc.BRANCH AND bt.BRANCHID = tc.BRANCHID
            LEFT JOIN TopStaff   ts ON bt.BRANCH = ts.BRANCH AND bt.BRANCHID = ts.BRANCHID
            LEFT JOIN TopProduct tp ON bt.BRANCH = tp.BRANCH AND bt.BRANCHID = tp.BRANCHID;

            SET @Msg = '  [Step 5/6] DONE — ' + CAST(@@ROWCOUNT AS VARCHAR)
                         + ' branches | Elapsed: '
                         + CAST(DATEDIFF(SECOND, @StepTime, GETDATE()) AS VARCHAR) + 's';
            RAISERROR(@Msg, 0, 1) WITH NOWAIT;

            -- =========================================================
            -- STEP 6 : Final score assembly + output
            -- =========================================================
            SET @StepTime = GETDATE();
            RAISERROR('  [Step 6/6] Assembling scores and producing final output...', 0, 1) WITH NOWAIT;

            IF OBJECT_ID('tempdb..#final_table_for_ml_parameters') IS NULL
            BEGIN
                  CREATE TABLE #final_table_for_ml_parameters
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
                        ComparedToDate                  DATE,
						zone varchar(50),
						division varchar(50),
						region varchar(50)
                  );
            END;


            INSERT INTO #final_table_for_ml_parameters
            (
                  
                  BRANCHID,
                  BranchName,
                  TotalLoans,
                  TotalPrincipalOS,


				  PAR_1_30_Amt,
				  PAR_31_60_Amt,
				  PAR_61_90_Amt,
				  
                  Score_NPARate,
                  Score_PAR0Rate,
                  Score_WriteOffRate,
                  Score_BucketDist,
                  Score_NPADrift,
                  Score_ArrearVelocity,
                  Score_WriteOffGrowth,
                  Score_NewDefaults,
                  Score_CollectionGap,
                  Score_CollectionRecency,
                  Score_MissedInst,
                  Score_GoodLoanInverse,
                  Score_DeceasedRate,
                  Score_RepeatBorrowerNPA,
                  Score_CenterConc,
                  Score_StaffConc,
                  Score_DAWriteOff,
                  RiskScore,
                  RiskGrade,
                  SubScore_PortfolioQuality,
                  SubScore_TrendVelocity,
                  SubScore_CollectionEfficiency,
                  SubScore_CustomerRisk,
                  SubScore_ConcentrationRisk,
                  NPALoans,
                  WriteOffCount,
                  GoodLoanCount,
                  DeceasedCount,
                  TotalArrearAmt,
                  Cur_NPA_Amt,
                  Pri_NPA_Amt,
                  NPA_Amt_Change_Pct,
                  Cur_ArrearAmt,
                  Pri_ArrearAmt,
                  Arrear_Amt_Change_Pct,
                  NewDefaultsThisMonth,
                  CollectionRate_Pct,
                  AvgDaysSinceCollection,
                  AvgArrearDays,
                  RepeatBorrowerNPA,
                  TopCenter_NPAConc_Pct,
                  TopStaff_NPAConc_Pct,
                  ActiveStaffCount,
                  Staff_Caseload_Ratio,
                  Staff_Overstay_12M_Pct,
                  Staff_Tenure_Under3M_Pct,
                  ActiveCenterCount,
                  Avg_Center_Size,
                  AsOnDate,
                  ComparedToDate,
				zone,
				division,
				region
            )
            SELECT
                  pq.BRANCHID,
                  pq.BRANCH                                                              AS BranchName,
                  --pq.Division                                                                                               as Division,
                  pq.TotalLoans,
                  pq.TotalPrincipalOS,

				  pq.PAR_1_30_Amt,
				  pq.PAR_31_60_Amt,
				  pq.PAR_61_90_Amt,


				  
	
                  -- ── Individual metric scores ─────────────────────────

                  -- Portfolio Quality (max 300)
                  CASE WHEN pq.TotalLoans = 0 THEN 0
                         ELSE CASE WHEN CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) > 100
                                       THEN 100
                                       ELSE CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) END
                  END                                                                    AS Score_NPARate,

                  CASE WHEN pq.TotalLoans = 0 THEN 0
                         ELSE CASE WHEN CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) > 60
                                       THEN 60
                                       ELSE CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) END
                  END                                                                    AS Score_PAR0Rate,

                  CASE WHEN pq.TotalPrincipalOS = 0 THEN 0
                         ELSE CASE WHEN CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) > 80
                                       THEN 80
                                       ELSE CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) END
                  END                                                                    AS Score_WriteOffRate,

                  CASE WHEN pq.TotalLoans = 0 THEN 0
                         ELSE CASE WHEN CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) > 60
                                       THEN 60
                                       ELSE CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) END
                  END                                                                    AS Score_BucketDist,

                  -- Trend / Velocity (max 250)
                  CASE WHEN tm.Pri_NPA_Amt = 0 AND tm.Cur_NPA_Amt > 0 THEN 100
                         WHEN tm.Pri_NPA_Amt = 0 THEN 0
                         ELSE CASE WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) > 100
                                       THEN 100
                                       WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) < 0
                                       THEN 0
                                       ELSE CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) END
                  END                                                                    AS Score_NPADrift,

                  CASE WHEN tm.Pri_ArrearAmt = 0 AND tm.Cur_ArrearAmt > 0 THEN 75
                         WHEN tm.Pri_ArrearAmt = 0 THEN 0
                         ELSE CASE WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) > 75
                                       THEN 75
                                       WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) < 0
                                       THEN 0
                                       ELSE CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) END
                  END                                                                    AS Score_ArrearVelocity,

                  CASE WHEN tm.Pri_WriteOffCount = 0 AND tm.Cur_WriteOffCount > 0 THEN 50
                         WHEN tm.Pri_WriteOffCount = 0 THEN 0
                         ELSE CASE WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) > 50
                                       THEN 50
                                       WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) < 0
                                       THEN 0
                                       ELSE CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) END
                  END                                                                    AS Score_WriteOffGrowth,

                  CASE WHEN pq.TotalLoans = 0 THEN 0
                         ELSE CASE WHEN CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) > 25
                                       THEN 25
                                       ELSE CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) END
                  END                                                                    AS Score_NewDefaults,

                  -- Collection Efficiency (max 200)
                  CASE WHEN cm.TotalDue = 0 THEN 0
                         ELSE CASE WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) > 100
                                       THEN 100
                                       WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) < 0
                                       THEN 0
                                       ELSE (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) END
                  END                                                                    AS Score_CollectionGap,

                  CASE WHEN ISNULL(cm.AvgDaysSinceCollection,0) > 60 THEN 60
                         ELSE ISNULL(cm.AvgDaysSinceCollection,0) END                     AS Score_CollectionRecency,

                  CASE WHEN cm.TotalLoansForColl = 0 THEN 0
                         ELSE CASE WHEN CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) > 40
                                       THEN 40
                                       ELSE CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) END
                  END                                                                    AS Score_MissedInst,

                  -- Customer Risk (max 150)
                  CASE WHEN pq.TotalLoans = 0 THEN 60
                         ELSE CASE WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) > 60
                                       THEN 60
                                       WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) < 0
                                       THEN 0
                                       ELSE (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) END
                  END                                                                    AS Score_GoodLoanInverse,

                  CASE WHEN pq.TotalLoans = 0 THEN 0
                         ELSE CASE WHEN CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) > 50
                                       THEN 50
                                       ELSE CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) END
                  END                                                                    AS Score_DeceasedRate,

                  CASE WHEN cr.TotalForConc = 0 THEN 0
                         ELSE CASE WHEN CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) > 40
                                       THEN 40
                                       ELSE CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) END
                  END                                                                    AS Score_RepeatBorrowerNPA,

                  -- Concentration Risk (max 100)
                  CASE WHEN CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) > 40
                         THEN 40
                         ELSE CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) END        AS Score_CenterConc,

                  CASE WHEN CAST(ISNULL(cr.TopStaffNPAConc,0) * 35 AS INT) > 35
                         THEN 35
                         ELSE CAST(ISNULL(cr.TopStaffNPAConc,0) * 35 AS INT) END         AS Score_StaffConc,

                  CASE WHEN cr.TotalForConc = 0 THEN 0
                         ELSE CASE WHEN CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) > 25
                                       THEN 25
                                       ELSE CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) END
                  END                                                                    AS Score_DAWriteOff,

                  -- ── Total Risk Score (0–1000) ────────────────────────
                  -- Portfolio Quality sub-total
                    CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) > 100 THEN 100 ELSE CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) END END
                  + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) > 60 THEN 60 ELSE CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) END END
                  + CASE WHEN pq.TotalPrincipalOS = 0 THEN 0 ELSE CASE WHEN CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) > 80 THEN 80 ELSE CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) END END
                  + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) > 60 THEN 60 ELSE CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) END END
                  -- Trend / Velocity sub-total
                  + CASE WHEN tm.Pri_NPA_Amt = 0 AND tm.Cur_NPA_Amt > 0 THEN 100 WHEN tm.Pri_NPA_Amt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) > 100 THEN 100 WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) END END
                  + CASE WHEN tm.Pri_ArrearAmt = 0 AND tm.Cur_ArrearAmt > 0 THEN 75 WHEN tm.Pri_ArrearAmt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) > 75 THEN 75 WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) END END
                  + CASE WHEN tm.Pri_WriteOffCount = 0 AND tm.Cur_WriteOffCount > 0 THEN 50 WHEN tm.Pri_WriteOffCount = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) > 50 THEN 50 WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) END END
                  + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) > 25 THEN 25 ELSE CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                  -- Collection sub-total
                  + CASE WHEN cm.TotalDue = 0 THEN 0 ELSE CASE WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) > 100 THEN 100 WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) < 0 THEN 0 ELSE (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) END END
                  + CASE WHEN ISNULL(cm.AvgDaysSinceCollection,0) > 60 THEN 60 ELSE ISNULL(cm.AvgDaysSinceCollection,0) END
                  + CASE WHEN cm.TotalLoansForColl = 0 THEN 0 ELSE CASE WHEN CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) > 40 THEN 40 ELSE CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) END END
                  -- Customer risk sub-total
                  + CASE WHEN pq.TotalLoans = 0 THEN 60 ELSE CASE WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) > 60 THEN 60 WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) < 0 THEN 0 ELSE (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) END END
                  + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) > 50 THEN 50 ELSE CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                  + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) > 40 THEN 40 ELSE CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                  -- Concentration sub-total
                  + CASE WHEN CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) > 40 THEN 40 ELSE CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) END
                  + CASE WHEN CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) > 35 THEN 35 ELSE CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) END
                  + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) > 25 THEN 25 ELSE CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                                                                                                                           AS RiskScore,

                  -- ── Risk Grade ───────────────────────────────────────
                  CASE
                        WHEN (
                                CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) > 100 THEN 100 ELSE CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) > 60 THEN 60 ELSE CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) END END
                              + CASE WHEN pq.TotalPrincipalOS = 0 THEN 0 ELSE CASE WHEN CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) > 80 THEN 80 ELSE CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) > 60 THEN 60 ELSE CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) END END
                              + CASE WHEN tm.Pri_NPA_Amt = 0 AND tm.Cur_NPA_Amt > 0 THEN 100 WHEN tm.Pri_NPA_Amt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) > 100 THEN 100 WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) END END
                              + CASE WHEN tm.Pri_ArrearAmt = 0 AND tm.Cur_ArrearAmt > 0 THEN 75 WHEN tm.Pri_ArrearAmt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) > 75 THEN 75 WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) END END
                              + CASE WHEN tm.Pri_WriteOffCount = 0 AND tm.Cur_WriteOffCount > 0 THEN 50 WHEN tm.Pri_WriteOffCount = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) > 50 THEN 50 WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) > 25 THEN 25 ELSE CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                              + CASE WHEN cm.TotalDue = 0 THEN 0 ELSE CASE WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) > 100 THEN 100 WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) < 0 THEN 0 ELSE (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) END END
                              + CASE WHEN ISNULL(cm.AvgDaysSinceCollection,0) > 60 THEN 60 ELSE ISNULL(cm.AvgDaysSinceCollection,0) END
                              + CASE WHEN cm.TotalLoansForColl = 0 THEN 0 ELSE CASE WHEN CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) > 40 THEN 40 ELSE CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 60 ELSE CASE WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) > 60 THEN 60 WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) < 0 THEN 0 ELSE (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) > 50 THEN 50 ELSE CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                              + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) > 40 THEN 40 ELSE CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                              + CASE WHEN CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) > 40 THEN 40 ELSE CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) END
                              + CASE WHEN CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) > 35 THEN 35 ELSE CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) END
                              + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) > 25 THEN 25 ELSE CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                        ) <= 200 THEN 'LOW'
                        WHEN (
                                CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) > 100 THEN 100 ELSE CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) > 60 THEN 60 ELSE CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) END END
                              + CASE WHEN pq.TotalPrincipalOS = 0 THEN 0 ELSE CASE WHEN CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) > 80 THEN 80 ELSE CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) > 60 THEN 60 ELSE CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) END END
                              + CASE WHEN tm.Pri_NPA_Amt = 0 AND tm.Cur_NPA_Amt > 0 THEN 100 WHEN tm.Pri_NPA_Amt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) > 100 THEN 100 WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) END END
                              + CASE WHEN tm.Pri_ArrearAmt = 0 AND tm.Cur_ArrearAmt > 0 THEN 75 WHEN tm.Pri_ArrearAmt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) > 75 THEN 75 WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) END END
                              + CASE WHEN tm.Pri_WriteOffCount = 0 AND tm.Cur_WriteOffCount > 0 THEN 50 WHEN tm.Pri_WriteOffCount = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) > 50 THEN 50 WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) > 25 THEN 25 ELSE CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                              + CASE WHEN cm.TotalDue = 0 THEN 0 ELSE CASE WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) > 100 THEN 100 WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) < 0 THEN 0 ELSE (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) END END
                              + CASE WHEN ISNULL(cm.AvgDaysSinceCollection,0) > 60 THEN 60 ELSE ISNULL(cm.AvgDaysSinceCollection,0) END
                              + CASE WHEN cm.TotalLoansForColl = 0 THEN 0 ELSE CASE WHEN CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) > 40 THEN 40 ELSE CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 60 ELSE CASE WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) > 60 THEN 60 WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) < 0 THEN 0 ELSE (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) > 50 THEN 50 ELSE CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                              + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) > 40 THEN 40 ELSE CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                              + CASE WHEN CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) > 40 THEN 40 ELSE CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) END
                              + CASE WHEN CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) > 35 THEN 35 ELSE CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) END
                              + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) > 25 THEN 25 ELSE CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                        ) <= 400 THEN 'MODERATE'
                        WHEN (
                                CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) > 100 THEN 100 ELSE CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) > 60 THEN 60 ELSE CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) END END
                              + CASE WHEN pq.TotalPrincipalOS = 0 THEN 0 ELSE CASE WHEN CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) > 80 THEN 80 ELSE CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) > 60 THEN 60 ELSE CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) END END
                              + CASE WHEN tm.Pri_NPA_Amt = 0 AND tm.Cur_NPA_Amt > 0 THEN 100 WHEN tm.Pri_NPA_Amt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) > 100 THEN 100 WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) END END
                              + CASE WHEN tm.Pri_ArrearAmt = 0 AND tm.Cur_ArrearAmt > 0 THEN 75 WHEN tm.Pri_ArrearAmt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) > 75 THEN 75 WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) END END
                              + CASE WHEN tm.Pri_WriteOffCount = 0 AND tm.Cur_WriteOffCount > 0 THEN 50 WHEN tm.Pri_WriteOffCount = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) > 50 THEN 50 WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) > 25 THEN 25 ELSE CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                              + CASE WHEN cm.TotalDue = 0 THEN 0 ELSE CASE WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) > 100 THEN 100 WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) < 0 THEN 0 ELSE (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) END END
                              + CASE WHEN ISNULL(cm.AvgDaysSinceCollection,0) > 60 THEN 60 ELSE ISNULL(cm.AvgDaysSinceCollection,0) END
                              + CASE WHEN cm.TotalLoansForColl = 0 THEN 0 ELSE CASE WHEN CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) > 40 THEN 40 ELSE CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 60 ELSE CASE WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) > 60 THEN 60 WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) < 0 THEN 0 ELSE (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) > 50 THEN 50 ELSE CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                              + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) > 40 THEN 40 ELSE CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                              + CASE WHEN CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) > 40 THEN 40 ELSE CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) END
                              + CASE WHEN CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) > 35 THEN 35 ELSE CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) END
                              + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) > 25 THEN 25 ELSE CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                        ) <= 600 THEN 'HIGH'
                        WHEN (
                                CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) > 100 THEN 100 ELSE CAST(pq.NPALoans * 100.0 / pq.TotalLoans AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) > 60 THEN 60 ELSE CAST(pq.LoansInArrear * 60.0 / pq.TotalLoans AS INT) END END
                              + CASE WHEN pq.TotalPrincipalOS = 0 THEN 0 ELSE CASE WHEN CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) > 80 THEN 80 ELSE CAST(pq.WriteOffAmt * 80.0 / NULLIF(pq.TotalPrincipalOS,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) > 60 THEN 60 ELSE CAST(pq.WeightedBucketScore * 60.0 / NULLIF(pq.TotalLoans * 8.0,0) AS INT) END END
                              + CASE WHEN tm.Pri_NPA_Amt = 0 AND tm.Cur_NPA_Amt > 0 THEN 100 WHEN tm.Pri_NPA_Amt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) > 100 THEN 100 WHEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS INT) END END
                              + CASE WHEN tm.Pri_ArrearAmt = 0 AND tm.Cur_ArrearAmt > 0 THEN 75 WHEN tm.Pri_ArrearAmt = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) > 75 THEN 75 WHEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 75.0 / NULLIF(tm.Pri_ArrearAmt,0) AS INT) END END
                              + CASE WHEN tm.Pri_WriteOffCount = 0 AND tm.Cur_WriteOffCount > 0 THEN 50 WHEN tm.Pri_WriteOffCount = 0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) > 50 THEN 50 WHEN CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) < 0 THEN 0 ELSE CAST((tm.Cur_WriteOffCount - tm.Pri_WriteOffCount) * 50.0 / NULLIF(tm.Pri_WriteOffCount,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) > 25 THEN 25 ELSE CAST(tm.NewDefaultsThisMonth * 25.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                              + CASE WHEN cm.TotalDue = 0 THEN 0 ELSE CASE WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) > 100 THEN 100 WHEN (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) < 0 THEN 0 ELSE (100 - CAST(cm.TotalCollected * 100.0 / NULLIF(cm.TotalDue,0) AS INT)) END END
                              + CASE WHEN ISNULL(cm.AvgDaysSinceCollection,0) > 60 THEN 60 ELSE ISNULL(cm.AvgDaysSinceCollection,0) END
                              + CASE WHEN cm.TotalLoansForColl = 0 THEN 0 ELSE CASE WHEN CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) > 40 THEN 40 ELSE CAST(cm.LoansWithMissedInst * 40.0 / NULLIF(cm.TotalLoansForColl,0) AS INT) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 60 ELSE CASE WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) > 60 THEN 60 WHEN (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) < 0 THEN 0 ELSE (60 - CAST(pq.GoodLoanCount * 60.0 / NULLIF(pq.TotalLoans,0) AS INT)) END END
                              + CASE WHEN pq.TotalLoans = 0 THEN 0 ELSE CASE WHEN CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) > 50 THEN 50 ELSE CAST(pq.DeceasedCount * 50.0 / NULLIF(pq.TotalLoans,0) AS INT) END END
                              + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) > 40 THEN 40 ELSE CAST(cr.RepeatBorrowerNPA * 40.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                              + CASE WHEN CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) > 40 THEN 40 ELSE CAST(ISNULL(cr.TopCenterNPAConc,0) * 40 AS INT) END
                              + CASE WHEN CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) > 35 THEN 35 ELSE CAST(ISNULL(cr.TopStaffNPAConc, 0) * 35 AS INT) END
                              + CASE WHEN cr.TotalForConc = 0 THEN 0 ELSE CASE WHEN CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) > 25 THEN 25 ELSE CAST(cr.DAWriteOffCount * 25.0 / NULLIF(cr.TotalForConc,0) AS INT) END END
                        ) <= 800 THEN 'CRITICAL'
                        ELSE 'SEVERE'
                  END                                                                    AS RiskGrade,

                  -- ── Category sub-scores ──────────────────────────────
                  (   CASE WHEN pq.TotalLoans=0 THEN 0 ELSE CASE WHEN CAST(pq.NPALoans*100.0/pq.TotalLoans AS INT)>100 THEN 100 ELSE CAST(pq.NPALoans*100.0/pq.TotalLoans AS INT) END END
                    + CASE WHEN pq.TotalLoans=0 THEN 0 ELSE CASE WHEN CAST(pq.LoansInArrear*60.0/pq.TotalLoans AS INT)>60 THEN 60 ELSE CAST(pq.LoansInArrear*60.0/pq.TotalLoans AS INT) END END
                    + CASE WHEN pq.TotalPrincipalOS=0 THEN 0 ELSE CASE WHEN CAST(pq.WriteOffAmt*80.0/NULLIF(pq.TotalPrincipalOS,0) AS INT)>80 THEN 80 ELSE CAST(pq.WriteOffAmt*80.0/NULLIF(pq.TotalPrincipalOS,0) AS INT) END END
                    + CASE WHEN pq.TotalLoans=0 THEN 0 ELSE CASE WHEN CAST(pq.WeightedBucketScore*60.0/NULLIF(pq.TotalLoans*8.0,0) AS INT)>60 THEN 60 ELSE CAST(pq.WeightedBucketScore*60.0/NULLIF(pq.TotalLoans*8.0,0) AS INT) END END
                  )                                                                      AS SubScore_PortfolioQuality,

                  (   CASE WHEN tm.Pri_NPA_Amt=0 AND tm.Cur_NPA_Amt>0 THEN 100 WHEN tm.Pri_NPA_Amt=0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_NPA_Amt-tm.Pri_NPA_Amt)*100.0/tm.Pri_NPA_Amt AS INT)>100 THEN 100 WHEN CAST((tm.Cur_NPA_Amt-tm.Pri_NPA_Amt)*100.0/tm.Pri_NPA_Amt AS INT)<0 THEN 0 ELSE CAST((tm.Cur_NPA_Amt-tm.Pri_NPA_Amt)*100.0/tm.Pri_NPA_Amt AS INT) END END
                    + CASE WHEN tm.Pri_ArrearAmt=0 AND tm.Cur_ArrearAmt>0 THEN 75 WHEN tm.Pri_ArrearAmt=0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_ArrearAmt-tm.Pri_ArrearAmt)*75.0/NULLIF(tm.Pri_ArrearAmt,0) AS INT)>75 THEN 75 WHEN CAST((tm.Cur_ArrearAmt-tm.Pri_ArrearAmt)*75.0/NULLIF(tm.Pri_ArrearAmt,0) AS INT)<0 THEN 0 ELSE CAST((tm.Cur_ArrearAmt-tm.Pri_ArrearAmt)*75.0/NULLIF(tm.Pri_ArrearAmt,0) AS INT) END END
                    + CASE WHEN tm.Pri_WriteOffCount=0 AND tm.Cur_WriteOffCount>0 THEN 50 WHEN tm.Pri_WriteOffCount=0 THEN 0 ELSE CASE WHEN CAST((tm.Cur_WriteOffCount-tm.Pri_WriteOffCount)*50.0/NULLIF(tm.Pri_WriteOffCount,0) AS INT)>50 THEN 50 WHEN CAST((tm.Cur_WriteOffCount-tm.Pri_WriteOffCount)*50.0/NULLIF(tm.Pri_WriteOffCount,0) AS INT)<0 THEN 0 ELSE CAST((tm.Cur_WriteOffCount-tm.Pri_WriteOffCount)*50.0/NULLIF(tm.Pri_WriteOffCount,0) AS INT) END END
                    + CASE WHEN pq.TotalLoans=0 THEN 0 ELSE CASE WHEN CAST(tm.NewDefaultsThisMonth*25.0/NULLIF(pq.TotalLoans,0) AS INT)>25 THEN 25 ELSE CAST(tm.NewDefaultsThisMonth*25.0/NULLIF(pq.TotalLoans,0) AS INT) END END
                  )                                                                      AS SubScore_TrendVelocity,

                  (   CASE WHEN cm.TotalDue=0 THEN 0 ELSE CASE WHEN (100-CAST(cm.TotalCollected*100.0/NULLIF(cm.TotalDue,0) AS INT))>100 THEN 100 WHEN (100-CAST(cm.TotalCollected*100.0/NULLIF(cm.TotalDue,0) AS INT))<0 THEN 0 ELSE (100-CAST(cm.TotalCollected*100.0/NULLIF(cm.TotalDue,0) AS INT)) END END
                    + CASE WHEN ISNULL(cm.AvgDaysSinceCollection,0)>60 THEN 60 ELSE ISNULL(cm.AvgDaysSinceCollection,0) END
                    + CASE WHEN cm.TotalLoansForColl=0 THEN 0 ELSE CASE WHEN CAST(cm.LoansWithMissedInst*40.0/NULLIF(cm.TotalLoansForColl,0) AS INT)>40 THEN 40 ELSE CAST(cm.LoansWithMissedInst*40.0/NULLIF(cm.TotalLoansForColl,0) AS INT) END END
                  )                                                                      AS SubScore_CollectionEfficiency,

                  (   CASE WHEN pq.TotalLoans=0 THEN 60 ELSE CASE WHEN (60-CAST(pq.GoodLoanCount*60.0/NULLIF(pq.TotalLoans,0) AS INT))>60 THEN 60 WHEN (60-CAST(pq.GoodLoanCount*60.0/NULLIF(pq.TotalLoans,0) AS INT))<0 THEN 0 ELSE (60-CAST(pq.GoodLoanCount*60.0/NULLIF(pq.TotalLoans,0) AS INT)) END END
                    + CASE WHEN pq.TotalLoans=0 THEN 0 ELSE CASE WHEN CAST(pq.DeceasedCount*50.0/NULLIF(pq.TotalLoans,0) AS INT)>50 THEN 50 ELSE CAST(pq.DeceasedCount*50.0/NULLIF(pq.TotalLoans,0) AS INT) END END
                    + CASE WHEN cr.TotalForConc=0 THEN 0 ELSE CASE WHEN CAST(cr.RepeatBorrowerNPA*40.0/NULLIF(cr.TotalForConc,0) AS INT)>40 THEN 40 ELSE CAST(cr.RepeatBorrowerNPA*40.0/NULLIF(cr.TotalForConc,0) AS INT) END END
                  )                                                                      AS SubScore_CustomerRisk,

                  (   CASE WHEN CAST(ISNULL(cr.TopCenterNPAConc,0)*40 AS INT)>40 THEN 40 ELSE CAST(ISNULL(cr.TopCenterNPAConc,0)*40 AS INT) END
                    + CASE WHEN CAST(ISNULL(cr.TopStaffNPAConc, 0)*35 AS INT)>35 THEN 35 ELSE CAST(ISNULL(cr.TopStaffNPAConc, 0)*35 AS INT) END
                    + CASE WHEN cr.TotalForConc=0 THEN 0 ELSE CASE WHEN CAST(cr.DAWriteOffCount*25.0/NULLIF(cr.TotalForConc,0) AS INT)>25 THEN 25 ELSE CAST(cr.DAWriteOffCount*25.0/NULLIF(cr.TotalForConc,0) AS INT) END END
                  )                                                                      AS SubScore_ConcentrationRisk,

                  -- ── Raw supporting metrics ───────────────────────────
                  pq.NPALoans,
                  pq.WriteOffCount,
                  pq.GoodLoanCount,
                  pq.DeceasedCount,
                  pq.TotalArrearAmt,
                  tm.Cur_NPA_Amt,
                  tm.Pri_NPA_Amt,
                  CASE WHEN tm.Pri_NPA_Amt > 0
                         THEN CAST((tm.Cur_NPA_Amt - tm.Pri_NPA_Amt) * 100.0 / tm.Pri_NPA_Amt AS DECIMAL(10,2))
                         ELSE NULL END                                                     AS NPA_Amt_Change_Pct,
                  tm.Cur_ArrearAmt,
                  tm.Pri_ArrearAmt,
                  CASE WHEN tm.Pri_ArrearAmt > 0
                         THEN CAST((tm.Cur_ArrearAmt - tm.Pri_ArrearAmt) * 100.0 / tm.Pri_ArrearAmt AS DECIMAL(10,2))
                         ELSE NULL END                                                     AS Arrear_Amt_Change_Pct,
                  tm.NewDefaultsThisMonth,
                  CASE WHEN cm.TotalDue > 0
                         THEN CAST(cm.TotalCollected * 100.0 / cm.TotalDue AS DECIMAL(10,2))
                         ELSE NULL END                                                     AS CollectionRate_Pct,
                  cm.AvgDaysSinceCollection,
                  cm.AvgArrearDays,
                  cr.RepeatBorrowerNPA,
                  CAST(ISNULL(cr.TopCenterNPAConc, 0) * 100 AS DECIMAL(10,2))          AS TopCenter_NPAConc_Pct,
                  CAST(ISNULL(cr.TopStaffNPAConc,  0) * 100 AS DECIMAL(10,2))          AS TopStaff_NPAConc_Pct,
                  cr.ActiveStaffCount,
                  cr.Staff_Caseload_Ratio,
                  cr.Staff_Overstay_12M_Pct,
                  cr.Staff_Tenure_Under3M_Pct,
                  cr.ActiveCenterCount,
                  cr.Avg_Center_Size,
                  @AsOnDate                                                              AS AsOnDate,
                  @PriorDate                                                             AS ComparedToDate,
				  vgh.zone,
				  vgh.Division,
				  vgh.region
            
            FROM #PortfolioQuality  pq
            LEFT JOIN #TrendMetrics      tm ON pq.BRANCH = tm.BRANCH AND pq.BRANCHID = tm.BRANCHID
            LEFT JOIN #CollectionMetrics cm ON pq.BRANCH = cm.BRANCH AND pq.BRANCHID = cm.BRANCHID
            LEFT JOIN #ConcentrationRisk cr ON pq.BRANCH = cr.BRANCH AND pq.BRANCHID = cr.BRANCHID
			left join VW_Branch_To_GeographiclHierarchy_26june26 vgh on pq.BRANCHID = vgh.BranchID
            ORDER BY RiskScore DESC;

            SET @Msg = '  [Step 6/6] DONE | Elapsed: '
                         + CAST(DATEDIFF(SECOND, @StepTime, GETDATE()) AS VARCHAR) + 's';
            RAISERROR(@Msg, 0, 1) WITH NOWAIT;


            -- ── Total elapsed ────────────────────────────────────────
            RAISERROR('====================================================', 0, 1) WITH NOWAIT;
            SET @Msg = '  SP_BranchRiskScore COMPLETE | Total elapsed: '
                         + CAST(DATEDIFF(SECOND, @StartTime, GETDATE()) AS VARCHAR) + 's';
            RAISERROR(@Msg, 0, 1) WITH NOWAIT;
            RAISERROR('====================================================', 0, 1) WITH NOWAIT;

            -- ── Cleanup temp tables ──────────────────────────────────
            DROP TABLE IF EXISTS #Base;
            DROP TABLE IF EXISTS #PortfolioQuality;
            DROP TABLE IF EXISTS #TrendMetrics;
            DROP TABLE IF EXISTS #CollectionMetrics;
            DROP TABLE IF EXISTS #ConcentrationRisk;
            set @asondate = dateadd(month, 1, @asondate)
      end


end 



select * from #final_table_for_ml_parameters
ORDER BY BRANCHID , ASONDATE DESC