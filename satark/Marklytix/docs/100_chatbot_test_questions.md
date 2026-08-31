# 100 Production Evaluation & Test Questions for Marklytix Chatbot
**Sonata Satark — Out-of-Distribution Test Suite**

---

## Overview

This benchmark contains **100 diverse test questions** derived from your production database schemas and stored procedures (`accounts_mst_usertbl`, `audit_branch_score_summary`, `branchriskscore`, `compliance_tickets`, `map_userRole`, `mst_role`, etc.). 

These questions are **held-out and distinct** from the training dataset to evaluate your chatbot's ability to handle novel phrasing, multi-table JOINs, aggregations, Hinglish conversational queries, and edge cases.

---

## Category 1: User & Auditor Account Inquiries (Questions 1 – 15)

1. Show me all active system users along with their email addresses and employee IDs.
2. List all users assigned to BranchID '2158' who joined after January 1, 2023.
3. Retrieve user name, employee DOB, and date joined for all users with BUType 2.0.
4. Count the total number of active users in each RegionID.
5. Find all dropout users whose DropoutDate is within the year 2024.
6. Display user code, full name, and contact number for users associated with HubID '102'.
7. List all users created by user ID 1001 along with their created dates.
8. Show the total count of active vs inactive users in `dbo.[accounts_mst_usertbl]`.
9. Retrieve employee ID, user name, and branch join date for users in DivisionID 5.0.
10. Find users who have an official email ending with '@sonataindia.com'.
11. Show all user accounts where `IsActive` is '1' but `IsDropout` is also marked '1'.
12. Retrieve user code, branch ID, and contact number for users created after June 2022.
13. List the top 10 most recently updated user accounts with their updated dates.
14. Count how many users are registered under each unique DivisionID.
15. Display user name, comment notes, and branch exit date for all former employees.

---

## Category 2: Branch Performance & Risk Scoring (Questions 16 – 35)

16. List all branches in Patna region along with their overall risk score.
17. Show top 5 branches with the highest risk score percentage in division 10.
18. Find branches where the collection rate is less than 85%.
19. What is the average risk score across all branches in RegionID '1003'?
20. Display branch name, region, and risk grade for branches marked with high risk grade 'HIGH'.
21. Count the number of branches in each risk grade category ('LOW', 'MODERATE', 'HIGH').
22. Show branches where the audit grade is 'A' but the risk score is above 75.
23. Retrieve branch name, collection rate percentage, and total audit score for Patna division.
24. List all branches whose audit date is within the last quarter.
25. Find branches where the actual audit score percentage is lower than the target threshold of 80%.
26. Show top 10 branches sorted by collection rate in descending order.
27. Count total branches grouped by region and division.
28. Display branch name, division ID, and audit start date for branches audited in August 2024.
29. List branches that have zero recorded compliance violations in the current fiscal year.
30. What is the maximum and minimum risk score recorded across all branches in Patna?
31. Retrieve branch code, branch name, and risk score for all branches in HubID '50'.
32. Show branches where the risk score increased compared to the previous audit cycle.
33. List all branches in division 4.0 that have an active status.
34. Calculate the average collection rate percentage for each division.
35. Find all branches where both risk grade is 'MODERATE' and collection rate is above 90%.

---

## Category 3: Audit Execution & Score Summaries (Questions 36 – 55)

36. Show total audit score, percentage, and audit grade for branch ID '2082'.
37. List all completed audits conducted by auditor with UserID 27775.
38. Retrieve audit start date, end date, and assigned auditor ID for all audits in Patna region.
39. What is the overall average audit score percentage across all completed branch audits?
40. Count how many audits were completed by each field auditor in the year 2024.
41. Display audit summary details for audits conducted between January and March 2024.
42. List all audit center records where the audit score is below 70%.
43. Retrieve auditor user code, branch name, and final audit grade for all 'C' grade audits.
44. Find the auditor who conducted the highest number of branch audits in Patna division.
45. Show all ongoing audit plans that have not yet reached final submission date.
46. Display total audit score and grade for all audits where the auditor was 'AUDIT_USER_101'.
47. List audit records where the end date is earlier than the start date (data validation check).
48. What is the total count of audits categorized by final audit grade ('A', 'B', 'C', 'D')?
49. Retrieve branch name, audit date, and auditor name for the 5 most recent branch audits.
50. Show all center checklist audit items marked with non-compliance ('No').
51. Calculate average audit score percentage per auditor role across all branches.
52. List all audit records where confidential remarks were recorded by the auditor.
53. Show audit plan IDs, branch names, and scheduled audit dates for next month.
54. Count total completed vs pending audits in RegionID '1024'.
55. Retrieve branch ID, audit score, and auditor comments for audits with grade 'B'.

---

## Category 4: Compliance Tickets & Ticket Responses (Questions 56 – 70)

56. List all open compliance tickets along with their creation date and branch ID.
57. Show total compliance tickets grouped by ticket status ('Open', 'In Progress', 'Resolved', 'Closed').
58. Retrieve ticket ID, query text, and response text for compliance ticket 501.
59. Count how many compliance tickets were created for each branch in Patna region.
60. Show all high-priority compliance tickets that have been pending for more than 7 days.
61. Display ticket ID, branch ID, created by user, and assigned user for open tickets.
62. List all compliance ticket responses submitted by user ID 105.
63. Show compliance tickets linked to feedback ID 3022 along with file attachment names.
64. Find branches with more than 5 open compliance tickets.
65. What is the average resolution time in hours for closed compliance tickets?
66. List all compliance tickets created during the month of July 2024.
67. Show ticket status, resolution summary, and closing date for ticket ID 789.
68. Count compliance tickets categorized by issue type or category.
69. Display compliance tickets where no official response has been recorded yet.
70. Show ticket ID, feedback ID, and creation timestamp for tickets created in HubID '10'.

---

## Category 5: Multi-Hop Complex Joins (Questions 71 – 85)

71. Retrieve user full name, role title, branch name, and audit score percentage for all audits conducted in Patna.
72. List all compliance tickets along with the assigned auditor's full name, role name, and branch collection rate.
73. Show branch name, region, total audit score, auditor user code, and auditor email for grade 'A' audits.
74. Display user code, user name, role description, and total API request count from user API logs.
75. Retrieve branch name, risk score, audit score, and the full name of the auditor who conducted the audit for branch 105.
76. List all normal uploaded files along with the branch name, checklist question, and uploader's full name.
77. Show all auditors who conducted audits in branches with a risk grade of 'HIGH', including their designation and contact number.
78. Retrieve compliance ticket ID, branch name, division, auditor role name, and response text for open tickets in Patna.
79. Show top 5 auditors by total number of completed audits, along with their assigned region and average audit score.
80. List branch name, risk score, audit grade, auditor name, and auditor role title for all branches in division 2.0.
81. Retrieve user name, role title, branch name, and total uploaded normal files count for each auditor.
82. Display compliance ticket details, associated branch risk score, and assigned user's email address.
83. Show all branches where the auditor's role is 'Senior Field Auditor' and the final audit grade is 'A'.
84. Count total API log requests per user role title across all active users.
85. List branch name, region, audit score, risk grade, and auditor's DOB for all audits conducted in 2024.

---

## Category 6: Conversational & Hinglish User Queries (Questions 86 – 100)

86. *Patna region ke sabhi branches ka current risk score aur collection rate percentage dikhao.*
87. *Branch 105 ka audit score percentage aur final audit grade kya h batao.*
88. *Branch 105 ka audit jis auditor ne kiya h uska user code aur full name kya h?*
89. *Patna division mein kitne total compliance tickets open hain aur kiske paas assigned hain?*
90. *Kaun-kaun se auditors ne Patna region mein grade 'A' audit complete kiya h list do.*
91. *Top 5 high risk branches kaun se hain unka risk score aur auditor name batao.*
92. *User 27775 ne kitne total audits perform kiye hain aur unka average score kya h?*
93. *Branch 2082 ke sabhi uploaded files aur checklist answers ki detail dikhao.*
94. *Mujhe Patna region ke sabhi active field auditors ka contact number aur email ID chahiye.*
95. *Kitne branches ka collection rate 80% se kam h unka branch name aur division batao.*
96. *Branch 105 mein jo non-compliance checklist questions mile hain unki detail aur auditor role batao.*
97. *Recent 10 completed audits ka branch name, audit date, aur score percentage dikhao.*
98. *Kaun si branches mein risk grade 'HIGH' h lekin audit score 80% se jyada h?*
99. *Patna region ke sabhi open compliance tickets ka ticket ID, branch name, aur created date batao.*
100. *System mein kitne active users hain aur unka division-wise count kitna h summary do.*
