select [BRANCHID], [BranchName],  [TotalLoans], [TotalPrincipalOS], [Score_NPARate], [Score_PAR0Rate], [Score_WriteOffRate], [Score_BucketDist], [Score_NPADrift], [Score_ArrearVelocity], [Score_WriteOffGrowth], [Score_NewDefaults], [Score_CollectionGap], [Score_CollectionRecency], [Score_MissedInst], [Score_GoodLoanInverse], [Score_DeceasedRate], [Score_RepeatBorrowerNPA], [Score_CenterConc], [Score_StaffConc], [Score_DAWriteOff], [RiskScore], [RiskGrade], [SubScore_PortfolioQuality], [SubScore_TrendVelocity], [SubScore_CollectionEfficiency], [SubScore_CustomerRisk], [SubScore_ConcentrationRisk], [NPALoans], [WriteOffCount], [GoodLoanCount], [DeceasedCount], [TotalArrearAmt], [Cur_NPA_Amt], [Pri_NPA_Amt], [NPA_Amt_Change_Pct], [Cur_ArrearAmt], [Pri_ArrearAmt], [Arrear_Amt_Change_Pct], [NewDefaultsThisMonth], [CollectionRate_Pct], [AvgDaysSinceCollection], [AvgArrearDays], [RepeatBorrowerNPA], [TopCenter_NPAConc_Pct], [TopStaff_NPAConc_Pct], [AsOnDate], [ComparedToDate] 
into audit_branch_parameter_training_data
from branchRiskScore where 1 = 0


select abgh.*, abpt.* 
into audit_branch_parameter_grade_training_data from audit_branch_parameter_training_data abpt
join audit_branch_grade_history_final abgh on abpt.BRANCHID = abgh.Branch_ID and abpt.AsOnDate = abgh.Month

TRUNCATE TABLE audit_branch_parameter_training_data

SELECT * FROM audit_branch_parameter_training_data

DROP TABLE audit_branch_parameter_grade_training_data



select * from audit_branch_parameter_grade_training_data


select * from audit_branch_checklist_master



select *, from audit_branch_grade_history_final


alter table audit_branch_grade_history_final
add asondate date


update audit_branch_grade_history_final set asondate = convert(date, month, 103)
from audit_branch_grade_history_final



select * from audit_branch_grade_history_final



alter table audit_branch_grade_history_final
drop column asondate