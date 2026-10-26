-- Optional aggregate-only telemetry. Execute once in SSMS (database of your choice).
-- The script creates the standalone demo database if needed.
IF DB_ID(N'LegalDocumentEngineDB') IS NULL
    CREATE DATABASE LegalDocumentEngineDB;
GO
USE LegalDocumentEngineDB;
GO
IF OBJECT_ID(N'dbo.DocumentBatchRun', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.DocumentBatchRun (
        BatchRunID BIGINT IDENTITY(1,1) PRIMARY KEY,
        CreatedAtUtc DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
        GenerationMode VARCHAR(16) NOT NULL
            CHECK (GenerationMode IN ('offline','gemini')),
        InputCount INT NOT NULL CHECK (InputCount BETWEEN 1 AND 50),
        CreatedCount INT NOT NULL CHECK (CreatedCount BETWEEN 0 AND 50),
        RejectedCount INT NOT NULL CHECK (RejectedCount BETWEEN 0 AND 50),
        APICallCount INT NOT NULL CHECK (APICallCount BETWEEN 0 AND 1),
        DurationMs INT NOT NULL CHECK (DurationMs >= 0),
        ModelName VARCHAR(100) NULL,
        TotalTokens INT NULL CHECK (TotalTokens >= 0),
        CONSTRAINT CK_LDE_BatchCounts CHECK (CreatedCount + RejectedCount = InputCount)
    );
END;
GO
SELECT TOP (10) * FROM dbo.DocumentBatchRun ORDER BY BatchRunID DESC;
