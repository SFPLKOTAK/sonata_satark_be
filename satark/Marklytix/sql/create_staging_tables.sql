-- ============================================================
-- UC_6892: Marklytix Chatbot Staging Tables for Step 1 & Step 2 Scanning
-- Run in target SQL Server DB (Sonata_Satark)
-- Stores raw candidate categories & subcategories per table prior to Step 3 Reconciliation
-- ============================================================

-- 1. Staging Categories
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_Staging_Categories' AND xtype='U')
CREATE TABLE dbo.Marklytix_Staging_Categories (
    Id           INT IDENTITY(1,1) PRIMARY KEY,
    TableName    VARCHAR(200)   NOT NULL,
    CategoryName VARCHAR(200)   NOT NULL,
    Keywords     NVARCHAR(MAX),   -- comma-separated keywords
    Description  NVARCHAR(MAX),
    ScanStatus   VARCHAR(50)    DEFAULT 'STAGED', -- STAGED, RECONCILED, PROMOTED
    CreatedDate  DATETIME       DEFAULT GETDATE()
);

-- 2. Staging Subcategories
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_Staging_Subcategories' AND xtype='U')
CREATE TABLE dbo.Marklytix_Staging_Subcategories (
    Id              INT IDENTITY(1,1) PRIMARY KEY,
    TableName       VARCHAR(200)   NOT NULL,
    CategoryName    VARCHAR(200)   NOT NULL,
    SubcategoryName VARCHAR(200)   NOT NULL,
    Keywords        NVARCHAR(MAX),   -- comma-separated keywords
    Description     NVARCHAR(MAX),
    ScanStatus      VARCHAR(50)    DEFAULT 'STAGED', -- STAGED, RECONCILED, PROMOTED
    CreatedDate     DATETIME       DEFAULT GETDATE()
);
