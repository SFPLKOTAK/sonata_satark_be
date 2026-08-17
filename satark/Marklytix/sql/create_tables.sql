-- ============================================================
-- UC_6892: Marklytix Chatbot Tables
-- Run in your target SQL Server DB (Sonata_Satark)
-- ============================================================

-- 1. Main Hierarchy Prompts (SBot system prompts)
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_ChatbotHierarchyPrompts' AND xtype='U')
CREATE TABLE dbo.Marklytix_ChatbotHierarchyPrompts (
    Id           INT IDENTITY(1,1) PRIMARY KEY,
    PromptName   VARCHAR(100)   NOT NULL UNIQUE,
    PromptContent NVARCHAR(MAX) NOT NULL,
    IsActive     BIT            NOT NULL DEFAULT 1,
    CreatedBy    VARCHAR(100),
    ModifiedBy   VARCHAR(100),
    CreatedDate  DATETIME       DEFAULT GETDATE(),
    ModifiedDate DATETIME       DEFAULT GETDATE()
);
GO

-- 2. Subcategory Prompts (Category -> Subcategory -> Tables -> Specialized Prompt)
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_SubcategoryPrompts' AND xtype='U')
CREATE TABLE dbo.Marklytix_SubcategoryPrompts (
    Id              INT IDENTITY(1,1) PRIMARY KEY,
    Category        VARCHAR(200)  NOT NULL,
    Subcategory     VARCHAR(200)  NOT NULL,
    Table_List      NVARCHAR(MAX),          -- comma-separated table names
    PromptContent   NVARCHAR(MAX),          -- specialized T-SQL generator prompt
    Query_Patterns  NVARCHAR(MAX),          -- example NL->SQL patterns
    IsActive        BIT           NOT NULL DEFAULT 1,
    CreatedBy       VARCHAR(100),
    ModifiedBy      VARCHAR(100),
    CreatedDate     DATETIME      DEFAULT GETDATE(),
    ModifiedDate    DATETIME      DEFAULT GETDATE()
);
GO

-- 3. Categories (keyword routing)
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_Categories' AND xtype='U')
CREATE TABLE dbo.Marklytix_Categories (
    Id           INT IDENTITY(1,1) PRIMARY KEY,
    CategoryName VARCHAR(200)   NOT NULL,
    Keywords     NVARCHAR(MAX),   -- comma-separated keywords
    Description  NVARCHAR(MAX),
    IsActive     BIT            NOT NULL DEFAULT 1,
    CreatedDate  DATETIME       DEFAULT GETDATE(),
    ModifiedDate DATETIME       DEFAULT GETDATE()
);
GO

-- 4. Subcategories (keyword routing)
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_Subcategories' AND xtype='U')
CREATE TABLE dbo.Marklytix_Subcategories (
    Id              INT IDENTITY(1,1) PRIMARY KEY,
    CategoryName    VARCHAR(200)   NOT NULL,
    SubcategoryName VARCHAR(200)   NOT NULL,
    Keywords        NVARCHAR(MAX),
    Description     NVARCHAR(MAX),
    IsActive        BIT            NOT NULL DEFAULT 1,
    CreatedDate     DATETIME       DEFAULT GETDATE(),
    ModifiedDate    DATETIME       DEFAULT GETDATE()
);
GO

-- 5. Chat History
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Marklytix_ChatHistory' AND xtype='U')
CREATE TABLE dbo.Marklytix_ChatHistory (
    Id                  INT IDENTITY(1,1) PRIMARY KEY,
    ChatID              INT            NOT NULL,
    UserID              INT            NOT NULL DEFAULT 1,
    Username            VARCHAR(200),
    Sender              VARCHAR(20)    NOT NULL,   -- 'user' or 'bot'
    Question            NVARCHAR(MAX),
    Generated_Query     NVARCHAR(MAX),
    Result_Generated    NVARCHAR(MAX),
    Response_Table      NVARCHAR(MAX),
    Query_Creation_Time FLOAT,
    Query_Execution_Time FLOAT,
    Created_At          DATETIME       DEFAULT GETDATE()
);
GO

-- ============================================================
-- Seed: Default SBot prompt (MarklytixChat)
-- ============================================================
IF NOT EXISTS (SELECT 1 FROM dbo.Marklytix_ChatbotHierarchyPrompts WHERE PromptName = 'MarklytixChat')
INSERT INTO dbo.Marklytix_ChatbotHierarchyPrompts (PromptName, PromptContent, IsActive, CreatedBy)
VALUES (
    'MarklytixChat',
    N'You are an expert T-SQL query generator for SQL Server.
Your task is to generate accurate T-SQL queries based on the user question and the provided schema context.

Guidelines:
- Generate proper T-SQL syntax for SQL Server 2016+
- Always wrap SQL in ```sql``` code blocks
- If aggregation is needed, use appropriate GROUP BY
- Use TOP N instead of LIMIT N (T-SQL syntax)
- Handle NULLs gracefully with ISNULL() or COALESCE()
- Consider date filtering using BETWEEN or DATEADD()
- If the question is conversational (greeting/general), respond naturally without SQL',
    1,
    'system'
);
GO
