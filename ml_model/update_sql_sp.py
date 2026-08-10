import os

sql_path = os.path.join(os.path.dirname(__file__), 'sql', 'data prep for ml looped for 10 months.sql')

with open(sql_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update BranchTotals CTE
target1 = "COUNT(DISTINCT DISBURSEMENTID)                                     AS TotalForConc,"
replace1 = "COUNT(DISTINCT DISBURSEMENTID)                                     AS TotalForConc,\n\t\t\t\t\t\tCOUNT(DISTINCT StaffID)                                            AS ActiveStaffCount,"

if target1 in content:
    content = content.replace(target1, replace1, 1)
    print("Step 1 replacement success")
else:
    print("Step 1 target not found")

# 2. Update #ConcentrationRisk SELECT clause
target2 = "bt.DAWriteOffCount,"
replace2 = "bt.DAWriteOffCount,\n\t\t\t\t\t\tbt.ActiveStaffCount,\n\t\t\t\t\t\tCAST(bt.TotalForConc * 1.0 / NULLIF(bt.ActiveStaffCount, 0) AS DECIMAL(10,2)) AS Staff_Caseload_Ratio,"

if target2 in content:
    content = content.replace(target2, replace2, 1)
    print("Step 2 replacement success")
else:
    print("Step 2 target not found")

# 3. Update CREATE TABLE #final_table_for_ml_parameters
target3 = "TopStaff_NPAConc_Pct            DECIMAL(10,2),"
replace3 = "TopStaff_NPAConc_Pct            DECIMAL(10,2),\n\t\t\t\t\t\tActiveStaffCount                INT,\n\t\t\t\t\t\tStaff_Caseload_Ratio            DECIMAL(10,2),"

if target3 in content:
    content = content.replace(target3, replace3, 1)
    print("Step 3 replacement success")
else:
    print("Step 3 target not found")

# 4. Update INSERT INTO #final_table_for_ml_parameters
target4 = "TopStaff_NPAConc_Pct,"
replace4 = "TopStaff_NPAConc_Pct,\n\t\t\t\t\t\tActiveStaffCount,\n\t\t\t\t\t\tStaff_Caseload_Ratio,"

if target4 in content:
    content = content.replace(target4, replace4, 1)
    print("Step 4 replacement success")
else:
    print("Step 4 target not found")

# 5. Update final SELECT clause
target5 = "CAST(ISNULL(cr.TopStaffNPAConc,  0) * 100 AS DECIMAL(10,2))          AS TopStaff_NPAConc_Pct,"
replace5 = "CAST(ISNULL(cr.TopStaffNPAConc,  0) * 100 AS DECIMAL(10,2))          AS TopStaff_NPAConc_Pct,\n\t\t\t\t\t\tcr.ActiveStaffCount,\n\t\t\t\t\t\tcr.Staff_Caseload_Ratio,"

if target5 in content:
    content = content.replace(target5, replace5, 1)
    print("Step 5 replacement success")
else:
    print("Step 5 target not found")

with open(sql_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated SQL file saved successfully!")
