"""Optional, aggregate-only SQL Server telemetry (no case data or prompts)."""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

from services.batch_service import BatchResult

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=True)


def log_batch_aggregate(result: BatchResult) -> bool:
    """Best-effort: SQL outages must never prevent ZIP download.

    Defaults to OFF. Run sql/schema.sql before enabling it.
    """
    if os.getenv('SQL_LOGGING_ENABLED', 'false').strip().lower() != 'true':
        return False
    try:
        import pyodbc
        driver = os.getenv('SQL_DRIVER', 'ODBC Driver 17 for SQL Server').strip()
        server = os.getenv('SQL_SERVER', r'.\SQLEXPRESS').strip()
        database = os.getenv('SQL_DATABASE', 'LegalDocumentEngineDB').strip()
        if not driver or not server or not database:
            return False
        # Integrated Windows credentials; no secrets stored in code.
        connection = pyodbc.connect(
            f'DRIVER={{{driver}}};SERVER={server};DATABASE={database};'
            'Trusted_Connection=yes;TrustServerCertificate=yes;',
            timeout=5,
        )
        try:
            cursor = connection.cursor()
            cursor.execute(
                '''INSERT INTO dbo.DocumentBatchRun
                   (GenerationMode, InputCount, CreatedCount, RejectedCount,
                    APICallCount, DurationMs, ModelName, TotalTokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                result.mode,
                len(result.rows),
                result.created_count,
                result.rejected_count,
                result.api_calls,
                result.duration_ms,
                result.model_name,
                result.total_tokens,
            )
            connection.commit()
        finally:
            connection.close()
        return True
    except Exception:
        # Deliberately no exception/raw data logging.
        return False
