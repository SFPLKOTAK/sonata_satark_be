import os
import pyodbc
import logging
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / '.env'
logger = logging.getLogger("loan_opportunity.db")


def _load_env():
    load_dotenv(ENV_PATH, override=True)


def _get_connection(host_env, user_env, pwd_env, db_env):
    _load_env()
    host = os.getenv(host_env)
    user = os.getenv(user_env)
    password = os.getenv(pwd_env)
    db = os.getenv(db_env)

    available_drivers = pyodbc.drivers()
    preferred_drivers = [
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 18 for SQL Server",
        "SQL Server"
    ]
    
    driver = None
    for d in preferred_drivers:
        if d in available_drivers:
            driver = d
            break
            
    if not driver and available_drivers:
        driver = available_drivers[0]

    last_error = None
    for drv in [driver, "ODBC Driver 17 for SQL Server", "SQL Server"]:
        if not drv:
            continue
        try:
            conn_str = (
                f"DRIVER={{{drv}}};"
                f"SERVER={host};"
                f"DATABASE={db};"
                f"UID={user};"
                f"PWD={password};"
                "TrustServerCertificate=yes;"
                "Connection Timeout=15;"
            )
            conn = pyodbc.connect(conn_str)
            return conn
        except Exception as e:
            last_error = e

    raise ConnectionError(f"Failed to connect to database ({host}/{db}): {last_error}")


def get_read_connection():
    """Returns a pyodbc connection to the Read DB (172.17.130.232 / sonata_connect)."""
    return _get_connection("READ_DB_HOST", "READ_DB_USER", "READ_DB_PASSWORD", "READ_DB_NAME")


def get_write_connection():
    """Returns a pyodbc connection to the Write DB (172.17.130.164 / sonata_satark)."""
    return _get_connection("WRITE_DB_HOST", "WRITE_DB_USER", "WRITE_DB_PASSWORD", "WRITE_DB_NAME")


def ensure_loan_opportunity_tables_exist():
    """
    Ensures that loan_opportunity_call_analysis has referral and fallback columns added.
    """
    try:
        conn = get_write_connection()
        try:
            cursor = conn.cursor()
            alter_queries = [
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'referral_interest') ALTER TABLE loan_opportunity_call_analysis ADD referral_interest INT DEFAULT 0;",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'referred_customer_details') ALTER TABLE loan_opportunity_call_analysis ADD referred_customer_details NVARCHAR(500);",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'is_fallback') ALTER TABLE loan_opportunity_call_analysis ADD is_fallback INT DEFAULT 0;",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'fallback_reason') ALTER TABLE loan_opportunity_call_analysis ADD fallback_reason NVARCHAR(500) DEFAULT '';",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'stt_transcript_confidence') ALTER TABLE loan_opportunity_call_analysis ADD stt_transcript_confidence INT DEFAULT 80;",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'ready_to_pay_confidence') ALTER TABLE loan_opportunity_call_analysis ADD ready_to_pay_confidence INT DEFAULT 85;",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'new_loan_confidence') ALTER TABLE loan_opportunity_call_analysis ADD new_loan_confidence INT DEFAULT 60;",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'referral_confidence') ALTER TABLE loan_opportunity_call_analysis ADD referral_confidence INT DEFAULT 95;",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'overall_call_confidence') ALTER TABLE loan_opportunity_call_analysis ADD overall_call_confidence INT DEFAULT 75;",
                "IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('loan_opportunity_call_analysis') AND name = 'confidence_grade') ALTER TABLE loan_opportunity_call_analysis ADD confidence_grade NVARCHAR(50) DEFAULT 'MEDIUM';"
            ]
            for q in alter_queries:
                try:
                    cursor.execute(q)
                    conn.commit()
                except Exception as ex_alt:
                    logger.debug(f"Column alter notice: {ex_alt}")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Error ensuring loan opportunity columns exist: {e}")


def get_cached_analysis(recording_url):
    """
    Checks if an analysis record for recording_url already exists in 
    sonata_satark.dbo.loan_opportunity_call_analysis.
    Returns row dict if found, else None.
    """
    if not recording_url:
        return None
    try:
        conn = get_write_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TOP 1 
                    call_date, client_number, agent_number, customerinfoid, 
                    disbursementid, userid, branchhid, circle_operator, circle_circle, 
                    ready_to_pay, new_loan_interest, referral_interest, referred_customer_details,
                    promised_amount, promised_date, reason_for_non_payment, customer_situation, 
                    collection_outcome, recommended_bro_action, raw_transcript, staff_user_interaction, 
                    english_summary, recording_url, is_fallback, fallback_reason,
                    stt_transcript_confidence, ready_to_pay_confidence, new_loan_confidence,
                    referral_confidence, overall_call_confidence, confidence_grade
                FROM loan_opportunity_call_analysis
                WHERE recording_url = ?
            """, (recording_url,))
            row = cursor.fetchone()
            if row:
                cols = [column[0] for column in cursor.description]
                res = dict(zip(cols, row))
                # Map call_date back to date key
                res["date"] = res.pop("call_date", "")
                return res
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"Cache lookup exception for {recording_url}: {e}")
    return None


def save_analysis_record(r):
    """
    Saves or updates an analyzed call record in Write DB (172.17.130.164 / sonata_satark)
    in loan_opportunity_call_analysis.
    """
    if not r or not r.get("recording_url"):
        return
    try:
        ensure_loan_opportunity_tables_exist()
        conn = get_write_connection()
        try:
            cursor = conn.cursor()
            recording_url = r.get("recording_url")
            
            cursor.execute("SELECT id FROM loan_opportunity_call_analysis WHERE recording_url = ?", (recording_url,))
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute("""
                    UPDATE loan_opportunity_call_analysis SET
                        call_date = ?, client_number = ?, agent_number = ?, customerinfoid = ?,
                        disbursementid = ?, userid = ?, branchhid = ?, circle_operator = ?,
                        circle_circle = ?, ready_to_pay = ?, new_loan_interest = ?,
                        referral_interest = ?, referred_customer_details = ?,
                        promised_amount = ?, promised_date = ?, reason_for_non_payment = ?,
                        customer_situation = ?, collection_outcome = ?, recommended_bro_action = ?,
                        raw_transcript = ?, staff_user_interaction = ?, english_summary = ?,
                        is_fallback = ?, fallback_reason = ?,
                        stt_transcript_confidence = ?, ready_to_pay_confidence = ?,
                        new_loan_confidence = ?, referral_confidence = ?,
                        overall_call_confidence = ?, confidence_grade = ?
                    WHERE recording_url = ?
                """, (
                    r.get("date", ""), r.get("client_number", ""), r.get("agent_number", ""), r.get("customerinfoid", ""),
                    r.get("disbursementid", ""), r.get("userid", ""), r.get("branchhid", ""), r.get("circle_operator", ""),
                    r.get("circle_circle", ""), int(r.get("ready_to_pay", 1)), int(r.get("new_loan_interest", 0)),
                    int(r.get("referral_interest", 0)), r.get("referred_customer_details", ""),
                    r.get("promised_amount", ""), r.get("promised_date", ""), r.get("reason_for_non_payment", ""),
                    r.get("customer_situation", ""), r.get("collection_outcome", ""), r.get("recommended_bro_action", ""),
                    r.get("raw_transcript", ""), r.get("staff_user_interaction", ""), r.get("english_summary", ""),
                    int(r.get("is_fallback", 0)), r.get("fallback_reason", ""),
                    int(r.get("stt_transcript_confidence", 80)), int(r.get("ready_to_pay_confidence", 85)),
                    int(r.get("new_loan_confidence", 60)), int(r.get("referral_confidence", 95)),
                    int(r.get("overall_call_confidence", 75)), str(r.get("confidence_grade", "MEDIUM")),
                    recording_url
                ))
            else:
                cursor.execute("""
                    INSERT INTO loan_opportunity_call_analysis (
                        recording_url, call_date, client_number, agent_number, customerinfoid,
                        disbursementid, userid, branchhid, circle_operator, circle_circle,
                        ready_to_pay, new_loan_interest, referral_interest, referred_customer_details,
                        promised_amount, promised_date, reason_for_non_payment, customer_situation,
                        collection_outcome, recommended_bro_action, raw_transcript, staff_user_interaction, english_summary,
                        is_fallback, fallback_reason,
                        stt_transcript_confidence, ready_to_pay_confidence, new_loan_confidence,
                        referral_confidence, overall_call_confidence, confidence_grade
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    recording_url, r.get("date", ""), r.get("client_number", ""), r.get("agent_number", ""),
                    r.get("customerinfoid", ""), r.get("disbursementid", ""), r.get("userid", ""), r.get("branchhid", ""),
                    r.get("circle_operator", ""), r.get("circle_circle", ""), int(r.get("ready_to_pay", 1)),
                    int(r.get("new_loan_interest", 0)), int(r.get("referral_interest", 0)), r.get("referred_customer_details", ""),
                    r.get("promised_amount", ""), r.get("promised_date", ""), r.get("reason_for_non_payment", ""),
                    r.get("customer_situation", ""), r.get("collection_outcome", ""), r.get("recommended_bro_action", ""),
                    r.get("raw_transcript", ""), r.get("staff_user_interaction", ""), r.get("english_summary", ""),
                    int(r.get("is_fallback", 0)), r.get("fallback_reason", ""),
                    int(r.get("stt_transcript_confidence", 80)), int(r.get("ready_to_pay_confidence", 85)),
                    int(r.get("new_loan_confidence", 60)), int(r.get("referral_confidence", 95)),
                    int(r.get("overall_call_confidence", 75)), str(r.get("confidence_grade", "MEDIUM"))
                ))

            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Failed to save analysis record for {r.get('recording_url')}: {e}")
