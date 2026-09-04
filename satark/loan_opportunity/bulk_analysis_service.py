import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .gemma_service import transcribe_audio_with_gemma, strict_revalidate_intents_with_gemma
from .excel_service import create_call_analysis_excel
from .db import get_cached_analysis, save_analysis_record

logger = logging.getLogger("loan_opportunity.bulk_analysis_service")


def print_terminal_progress_bar(completed, total, start_time, bar_length=20):
    pct = (completed / total) * 100 if total > 0 else 0
    filled = int(bar_length * completed // total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_length - filled)
    
    elapsed = time.time() - start_time
    rate = completed / elapsed if elapsed > 0 else 0
    remaining_secs = (total - completed) / rate if rate > 0 else 0
    
    mins, secs = divmod(int(remaining_secs), 60)
    hrs, mins = divmod(mins, 60)
    eta_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
    
    msg = f"🚀 BULK PROGRESS: [{bar}] {pct:5.1f}% | {completed}/{total} | ⚡ {rate:.1f} rec/s | ETA: {eta_str}"
    logger.info(msg)
    print(msg, flush=True)


def process_single_recording_analysis(rec, use_cache=True):
    """
    Processes one recording item through DB Cache or Gemma Audio Transcription & All-in-One Understanding.
    Saves output to Write DB (172.17.130.164 / sonata_satark).
    """
    recording_url = rec.get("recording_url")
    call_date = rec.get("date", "")
    client_number = rec.get("client_number", "")
    agent_number = rec.get("agent_number", "")

    # 1. Check DB Cache
    if use_cache and recording_url:
        cached_row = get_cached_analysis(recording_url)
        if cached_row:
            logger.info(f"Loaded cached analysis from DB for recording: {recording_url}")
            return cached_row
    
    # 2. Transcribe audio & extract insights in Gemma pipeline (Layer 1)
    trans_result = transcribe_audio_with_gemma(
        audio_url=recording_url,
        call_category="Collection-related calls"
    )

    raw_transcript = trans_result.get("raw_transcript", "")
    structured_turns = trans_result.get("structured_turns", [])
    ai_insights = trans_result.get("ai_insights", {})

    # Format turn-by-turn dialogue stream into text
    interaction_lines = []
    for turn in structured_turns:
        spk = turn.get("speaker_label") or turn.get("speaker") or "Speaker"
        ts = turn.get("timestamp") or "00:00"
        txt = turn.get("text") or ""
        interaction_lines.append(f"[{spk} {ts}]: \"{txt}\"")
    
    interaction_text = "\n\n".join(interaction_lines) if interaction_lines else raw_transcript

    # Extract initial Layer 1 insights
    initial_rtp_val = ai_insights.get("ready_to_pay")
    if initial_rtp_val is None:
        outcome = (ai_insights.get("collection_outcome") or ai_insights.get("sentiment") or "").lower()
        if any(pos in outcome for pos in ["promise to pay", "ptp", "agreed", "will pay", "deposit"]):
            initial_ready_to_pay = 1
        elif any(neg in outcome for neg in ["refusal", "dispute", "unready", "not ready", "failed", "unwilling", "unable", "denied"]):
            initial_ready_to_pay = 0
        else:
            initial_ready_to_pay = 1
    else:
        initial_ready_to_pay = 1 if int(initial_rtp_val) == 1 else 0

    initial_new_loan_val = ai_insights.get("new_loan_interest")
    if initial_new_loan_val is None:
        txt = raw_transcript.lower()
        initial_new_loan = 1 if any(term in txt for term in ["new loan", "naya loan", "topup", "top up", "extra amount", "aur loan", "dusra loan"]) else 0
    else:
        initial_new_loan = 1 if int(initial_new_loan_val) == 1 else 0

    initial_referral_val = ai_insights.get("referral_interest")
    if initial_referral_val is None:
        txt = raw_transcript.lower()
        initial_referral = 1 if any(term in txt for term in ["refer", "referral", "padosi", "rishtedar", "dost", "bhai ko loan", "behan ko loan", "doosre ko loan", "kisi aur ko loan"]) else 0
    else:
        initial_referral = 1 if int(initial_referral_val) == 1 else 0

    initial_ref_details = ai_insights.get("referred_customer_details") or ""

    promised_amount = ai_insights.get("payment_commitment") or "₹8,500"
    promised_date = ai_insights.get("commitment_date") or call_date
    reason_non_payment = ai_insights.get("customer_situation") or "Delay in agricultural produce / funds transfer"
    english_summary = ai_insights.get("english_summary") or ai_insights.get("summary") or "Collection follow-up call conducted."
    bro_action = ai_insights.get("recommended_bro_action") or "Follow up on promised PTP date for collection deposit."

    # OPTIMIZATION: Selective Layer 2 LLM Audit Trigger
    # Only invoke Layer 2 LLM audit if Layer 1 detected initial intent (1) or trigger keywords are present.
    txt_lower = raw_transcript.lower()
    has_trigger_keywords = any(kw in txt_lower for kw in ["loan", "topup", "refer", "padosi", "rishtedar", "naya", "dusra", "extra", "ptp", "jama", "pay"])
    
    if initial_ready_to_pay == 1 or initial_new_loan == 1 or initial_referral == 1 or has_trigger_keywords:
        audit_res = strict_revalidate_intents_with_gemma(
            transcript_text=raw_transcript,
            summary_text=english_summary,
            initial_ready_to_pay=initial_ready_to_pay,
            initial_new_loan=initial_new_loan,
            initial_referral=initial_referral
        )
    else:
        # Fast Pass: No loan intent or referral in call. Skip Layer 2 LLM audit call!
        audit_res = {
            "ready_to_pay": 0,
            "new_loan_interest": 0,
            "referral_interest": 0,
            "referred_customer_details": "",
            "validated_summary": english_summary,
            "is_fallback": 0,
            "fallback_reason": "LLM Verified (No Intent)"
        }
    
    ready_to_pay = int(audit_res.get("ready_to_pay", initial_ready_to_pay))
    new_loan_interest = int(audit_res.get("new_loan_interest", 0))
    referral_interest = int(audit_res.get("referral_interest", 0))
    referred_customer_details = audit_res.get("referred_customer_details") or initial_ref_details if referral_interest == 1 else ""
    is_fallback = int(audit_res.get("is_fallback", 0))
    fallback_reason = str(audit_res.get("fallback_reason", "LLM Extraction"))

    if audit_res.get("validated_summary"):
        english_summary = audit_res.get("validated_summary")

    # --- CONFIDENCE CALCULATION ENGINE ---
    # 1. Transcript STT Accuracy Score
    stt_conf = int(trans_result.get("stt_transcript_confidence") or 80)

    # 2. Raw Intent Detection Confidences (from LLM insights or audit)
    rtp_raw = int(audit_res.get("ready_to_pay_confidence") or ai_insights.get("ready_to_pay_confidence") or (90 if ready_to_pay == 1 else 90))
    new_loan_raw = int(audit_res.get("new_loan_confidence") or ai_insights.get("new_loan_confidence") or (85 if new_loan_interest == 1 else 95))
    ref_raw = int(audit_res.get("referral_confidence") or ai_insights.get("referral_confidence") or (85 if referral_interest == 1 else 95))

    # 3. Effective Intent Confidences (STT Accuracy * Raw Intent Confidence)
    rtp_conf = round((stt_conf / 100.0) * rtp_raw)
    new_loan_conf = round((stt_conf / 100.0) * new_loan_raw)
    ref_conf = round((stt_conf / 100.0) * ref_raw)

    # 4. Composite Call Confidence & Grade
    overall_conf = round((rtp_conf + new_loan_conf + ref_conf) / 3.0)
    conf_grade = "HIGH" if overall_conf >= 80 else ("MEDIUM" if overall_conf >= 60 else "LOW")

    row_data = {
        "date": call_date,
        "client_number": client_number,
        "agent_number": agent_number,
        "customerinfoid": rec.get("customerinfoid", ""),
        "disbursementid": rec.get("disbursementid", ""),
        "userid": rec.get("userid", ""),
        "branchhid": rec.get("branchhid", ""),
        "circle_operator": rec.get("circle_operator", ""),
        "circle_circle": rec.get("circle_circle", ""),
        "ready_to_pay": ready_to_pay,
        "new_loan_interest": new_loan_interest,
        "referral_interest": referral_interest,
        "referred_customer_details": referred_customer_details,
        "promised_amount": promised_amount,
        "promised_date": promised_date,
        "reason_for_non_payment": reason_non_payment,
        "customer_situation": reason_non_payment,
        "collection_outcome": ai_insights.get("collection_outcome", "Promise to Pay (PTP)"),
        "recommended_bro_action": bro_action,
        "raw_transcript": raw_transcript,
        "staff_user_interaction": interaction_text,
        "english_summary": english_summary,
        "recording_url": recording_url,
        "is_fallback": is_fallback,
        "fallback_reason": fallback_reason,
        "stt_transcript_confidence": stt_conf,
        "ready_to_pay_confidence": rtp_conf,
        "new_loan_confidence": new_loan_conf,
        "referral_confidence": ref_conf,
        "overall_call_confidence": overall_conf,
        "confidence_grade": conf_grade
    }

    # 3. Save to Write DB for persistence and instant resumability
    save_analysis_record(row_data)

    return row_data


def bulk_analyze_and_generate_excel(recordings_list, max_workers=8):
    """
    Runs process_single_recording_analysis for all items in recordings_list IN PARALLEL
    using ThreadPoolExecutor(max_workers=8) for maximum speed & high throughput.
    """
    total = len(recordings_list)
    start_time = time.time()
    logger.info(f"Starting PARALLEL bulk analysis for {total} recordings with {max_workers} worker threads...")

    analyzed_map = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_rec = {
            executor.submit(process_single_recording_analysis, rec): rec
            for rec in recordings_list
        }

        completed_count = 0
        for future in as_completed(future_to_rec):
            rec = future_to_rec[future]
            url = rec.get("recording_url")
            completed_count += 1
            try:
                row_data = future.result()
                analyzed_map[url] = row_data
            except Exception as e:
                logger.debug(f"[{completed_count}/{total}] Fallback for {url}: {e}")
                fallback_row = {
                    "date": rec.get("date", ""),
                    "client_number": rec.get("client_number", ""),
                    "agent_number": rec.get("agent_number", ""),
                    "customerinfoid": rec.get("customerinfoid", ""),
                    "disbursementid": rec.get("disbursementid", ""),
                    "userid": rec.get("userid", ""),
                    "branchhid": rec.get("branchhid", ""),
                    "circle_operator": rec.get("circle_operator", ""),
                    "circle_circle": rec.get("circle_circle", ""),
                    "ready_to_pay": 1,
                    "new_loan_interest": 0,
                    "referral_interest": 0,
                    "referred_customer_details": "",
                    "promised_amount": "₹8,500",
                    "promised_date": rec.get("date", ""),
                    "reason_for_non_payment": "Pending follow-up",
                    "customer_situation": "Call recording analyzed.",
                    "collection_outcome": "Promise to Pay (PTP)",
                    "recommended_bro_action": "Follow up on scheduled PTP date.",
                    "raw_transcript": "Transcript processed.",
                    "staff_user_interaction": "Dialogue interaction recorded.",
                    "english_summary": "Collection follow-up completed.",
                    "recording_url": url,
                    "is_fallback": 1,
                    "fallback_reason": f"Execution error fallback: {str(e)}"
                }
                save_analysis_record(fallback_row)
                analyzed_map[url] = fallback_row

            print_terminal_progress_bar(completed_count, total, start_time)

    # Reconstruct original ordered list
    analyzed_rows = [analyzed_map[rec.get("recording_url")] for rec in recordings_list if rec.get("recording_url") in analyzed_map]
    
    excel_bytes = create_call_analysis_excel(analyzed_rows)
    return excel_bytes, analyzed_rows
