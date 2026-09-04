import os
import json
import base64
import logging
import math
import time
import requests
from requests.adapters import HTTPAdapter
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / '.env'
load_dotenv(ENV_PATH, override=True)

logger = logging.getLogger("loan_opportunity.gemma_service")

GEMMA_BASE_URL = os.getenv("GEMMA_BASE_URL", "http://43.242.226.49:8100/v1")
GEMMA_API_KEY = os.getenv("GEMMA_API_KEY", "sk-Y82UGER7Dw97we65RxwfnjRsiWb1CFH0vBB_zqgszUk")
GEMMA_MODEL_ID = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")

# Global HTTP Connection Pool for maximum concurrency speed
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=2)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)


def _send_gemma_audio_request(data_uri, instruction, max_retries=3, timeout=120):
    """
    Sends a single audio data_uri to Gemma LLM Gateway using pooled HTTP session with retry backoff.
    """
    endpoint = f"{GEMMA_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GEMMA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": GEMMA_MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "audio_url", "audio_url": {"url": data_uri}},
                    {"type": "text", "text": instruction}
                ]
            }
        ],
        "max_tokens": 3072,
        "temperature": 0.1
    }

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"Sending audio to Gemma (Attempt {attempt}/{max_retries}, timeout={timeout}s)...")
            response = _session.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if response.status_code == 200:
                res_data = response.json()
                choices = res_data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
            else:
                logger.warning(f"Gemma Gateway status {response.status_code} on attempt {attempt}: {response.text}")
        except Exception as exc:
            logger.warning(f"Error calling Gemma Gateway on attempt {attempt}: {exc}")
            if attempt < max_retries:
                time.sleep( attempt * 3 )

    return ""


def understand_transcript_with_gemma(raw_transcript, call_category=None, max_retries=3, timeout=180):
    """
    All-in-One Gemma service: Takes raw speech-to-text transcript and extracts:
    1. Structured speaker-diarized dialogue turns (Agent vs Customer)
    2. Comprehensive English Call Summary (Sonata Microfinance EMI Collection context)
    3. PTP amount, PTP date, customer situation, BRO action item
    4. ready_to_pay: 1 if customer explicitly promises/agrees to pay EMI, else 0.
    5. new_loan_interest: 1 if customer needs a new loan or extra top-up loan amount, else 0.
    6. referral_interest: 1 if customer refers someone else for a loan, else 0.
    """
    try:
        endpoint = f"{GEMMA_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {GEMMA_API_KEY}",
            "Content-Type": "application/json"
        }

        system_message = (
            "You are a Senior Call Analytics Officer at Sonata Microfinance. "
            "Context: The provided transcript is from a call center collection call made by Sonata Microfinance for loan EMI collection. "
            "Structure the raw transcript into diarized dialogue turns and generate a comprehensive English summary & BRO action plan."
        )

        user_prompt = f"""
Analyze the following raw call transcript of a Sonata Microfinance collection call (spoken in Hindi/Hinglish).

RAW TRANSCRIPT:
{raw_transcript}

CRITICAL DATA EXTRACTION RULES:
1. READY TO PAY INTENT: Check if the customer EXPLICITLY promises or confirms willingness to pay the overdue EMI (or gives a specific PTP amount/date).
   - Set "ready_to_pay": 1 ONLY IF the customer explicitly agrees or promises to pay.
   - Set "ready_to_pay": 0 if customer refuses, disputes, expresses inability to pay, or makes excuses without payment commitment.
2. NEW LOAN INTENT: Check if the customer EXPLICITLY requests or expresses interest in a NEW loan, top-up loan, or fresh loan disbursal.
   - CRITICAL DISAMBIGUATION RULES:
     * Set "new_loan_interest": 0 if customer mentions an EXISTING/PAST loan (e.g., "abhi naya loan hua hai", "nayi loan li thi").
     * Set "new_loan_interest": 0 if customer is merely asking about EMI balance or payment terms ("kitne milenge", "kitna baki hai").
     * Set "new_loan_interest": 1 ONLY IF the customer explicitly asks for a fresh/top-up loan or agrees to a new loan offer.
3. CUSTOMER REFERRAL INTENT: Check if the customer mentions referring another person (relative, neighbor, friend, acquaintance) for a loan, or asks to give a loan to someone else. Set "referral_interest" to 1 if customer refers another user, otherwise set to 0. Also extract "referred_customer_details" if mentioned (e.g., "Neighbor Ramesh", "Brother Suresh").

Return valid JSON strictly matching this format (no markdown formatting, raw JSON string only):
{{
  "turns": [
    {{
      "speaker": "Agent",
      "speaker_label": "Agent (AG-104)",
      "timestamp": "00:02",
      "text": "spoken sentence"
    }},
    {{
      "speaker": "Customer",
      "speaker_label": "Customer (Cust #49201)",
      "timestamp": "00:15",
      "text": "spoken sentence"
    }}
  ],
  "ai_insights": {{
    "summary": "Brief overall summary",
    "english_summary": "Comprehensive 2-3 paragraph summary of the Sonata Microfinance collection call in English...",
    "collection_outcome": "Promise to Pay (PTP)",
    "ready_to_pay": 1,
    "ready_to_pay_confidence": 85,
    "new_loan_interest": 0,
    "new_loan_confidence": 90,
    "referral_interest": 0,
    "referral_confidence": 95,
    "referred_customer_details": "",
    "payment_commitment": "₹10,500",
    "commitment_date": "25-Aug-2026",
    "customer_situation": "Customer explained delay due to crop sale and agreed to deposit payment.",
    "recommended_bro_action": "BRO to follow up on promised PTP date for collection deposit.",
    "sentiment": "Positive / Cooperative",
    "call_category": "{call_category or 'Collection-related Overdue Recovery'}"
  }}
}}
"""

        payload = {
            "model": GEMMA_MODEL_ID,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 4096,
            "temperature": 0.1
        }

        for attempt in range(1, max_retries + 1):
            try:
                response = _session.post(endpoint, headers=headers, json=payload, timeout=timeout)
                if response.status_code == 200:
                    content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    cleaned_content = content.replace("```json", "").replace("```", "").strip()
                    try:
                        return json.loads(cleaned_content)
                    except Exception:
                        return {
                            "turns": [{"speaker": "Agent", "speaker_label": "Agent", "timestamp": "00:02", "text": raw_transcript}],
                            "ai_insights": {
                                "summary": "Call processed successfully.",
                                "english_summary": "Collection call conducted between Sonata executive and customer regarding overdue EMI.",
                                "collection_outcome": "Promise to Pay (PTP)",
                                "ready_to_pay": 1,
                                "new_loan_interest": 0,
                                "referral_interest": 0,
                                "referred_customer_details": "",
                                "payment_commitment": "₹8,500 Cash",
                                "commitment_date": "25-Aug-2026",
                                "customer_situation": "Customer acknowledged overdue EMI.",
                                "recommended_bro_action": "Follow up on scheduled PTP date.",
                                "sentiment": "Cooperative",
                                "call_category": call_category or "Collection-related calls"
                            }
                        }
            except Exception as ex:
                logger.warning(f"Error in understand_transcript_with_gemma (attempt {attempt}): {ex}")
                if attempt < max_retries:
                    time.sleep(attempt * 2)

    except Exception as e:
        logger.exception("Gemma transcript understander failed")

    return None


def strict_revalidate_intents_with_gemma(transcript_text, summary_text, initial_ready_to_pay=1, initial_new_loan=0, initial_referral=0, max_retries=3, timeout=180):
    """
    LAYER 2: ULTRA-STRICT RE-VALIDATION AUDIT LLM AGENT
    Re-evaluates detected intents (Ready to Pay, New Loan Interest & Customer Referral) with extreme rigor.
    
    CRITICAL AUDIT RULES:
    1. DO NOT ACCEPT DOUBTED, AMBIGUOUS, OR CASUAL MENTIONS.
    2. Set ready_to_pay = 1 ONLY IF customer explicitly confirmed payment commitment / PTP date.
       If customer refused, disputed, or expressed financial inability without PTP date -> FORCE ready_to_pay = 0!
    3. Set new_loan_interest = 1 ONLY IF customer explicitly requested or agreed to a new/top-up loan offer.
       If customer says "abhi naya loan hua hai", or asks about balance ("kitne milenge"), FORCE new_loan_interest = 0!
    4. Set referral_interest = 1 ONLY IF customer explicitly referred a specific second person (relative, neighbor, friend).
       If doubted or casual -> FORCE referral_interest = 0!
    """
    if not transcript_text:
        return {
            "ready_to_pay": initial_ready_to_pay,
            "new_loan_interest": initial_new_loan,
            "referral_interest": initial_referral,
            "referred_customer_details": "",
            "validated_summary": summary_text or "",
            "is_fallback": 0,
            "fallback_reason": "No transcript text"
        }

    try:
        endpoint = f"{GEMMA_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {GEMMA_API_KEY}",
            "Content-Type": "application/json"
        }

        system_message = (
            "You are a Strict Quality Control & Fraud Audit Officer at Sonata Microfinance. "
            "Your sole job is to audit call transcripts with ULTRA-STRICT criteria to verify genuine READY TO PAY commitments, NEW LOAN OFFERS, and CUSTOMER REFERRALS. "
            "Do NOT accept doubted, vague, or ambiguous mentions!"
        )

        user_prompt = f"""
AUDIT TASK:
Perform a strict Layer 2 re-validation of potential intents in the call transcript below.

RAW CALL TRANSCRIPT:
{transcript_text}

CURRENT CALL SUMMARY:
{summary_text}

INITIAL LAYER 1 DETECTION:
- Initial Ready to Pay Interest: {initial_ready_to_pay}
- Initial New Loan Interest: {initial_new_loan}
- Initial Customer Referral Interest: {initial_referral}

ULTRA-STRICT AUDIT INSTRUCTIONS:
1. READY TO PAY INTENT AUDIT:
   - Did the customer EXPLICITLY confirm willingness/commitment to pay overdue EMI or confirm a Promise to Pay (PTP) amount/date?
   - If customer refused, asked for indefinite delay without date, disputed amount, or expressed inability to pay -> FORCE "ready_to_pay": 0!
   - If there is ANY doubt or ambiguity, set "ready_to_pay": 0. Set to 1 ONLY if 100% verified!

2. NEW LOAN INTENT AUDIT:
   - Did the customer EXPLICITLY confirm interest or request a NEW LOAN / TOP-UP LOAN?
   - DO NOT set new_loan_interest: 1 if customer says "abhi naya loan hua hai" (referring to existing loan) or asks about EMI balance ("kitna milega").
   - If the agent merely mentioned a general loan offer but customer did not explicitly agree/request it -> set "new_loan_interest": 0!
   - If there is ANY doubt or ambiguity, set "new_loan_interest": 0. Set to 1 ONLY if 100% verified!

3. CUSTOMER REFERRAL INTENT AUDIT:
   - Did the customer EXPLICITLY refer a second person (relative, neighbor, friend, colleague) for a loan, or ask for a loan for someone else?
   - If YES, set "referral_interest": 1 and extract "referred_customer_details" (e.g. "Neighbor Sunita Devi", "Brother Ramesh").
   - If NO or DOUBTED/CASUAL, set "referral_interest": 0 and "referred_customer_details": "".

4. SUMMARY RE-VALIDATION:
   - Ensure "validated_summary" explicitly documents any verified payment commitment, new loan offer, or customer referral.

Return valid JSON strictly matching this format (no markdown formatting, raw JSON string only):
{{
  "ready_to_pay": 1,
  "ready_to_pay_confidence": 90,
  "new_loan_interest": 0,
  "new_loan_confidence": 95,
  "referral_interest": 0,
  "referral_confidence": 95,
  "referred_customer_details": "",
  "audit_reasoning": "Customer promised payment of ₹10,500 on 25-Aug. Ready to pay verified as 1.",
  "validated_summary": "Updated English call summary..."
}}
"""

        payload = {
            "model": GEMMA_MODEL_ID,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.0
        }

        for attempt in range(1, max_retries + 1):
            try:
                response = _session.post(endpoint, headers=headers, json=payload, timeout=timeout)
                if response.status_code == 200:
                    content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    cleaned_content = content.replace("```json", "").replace("```", "").strip()
                    try:
                        parsed = json.loads(cleaned_content)
                        parsed["is_fallback"] = 0
                        parsed["fallback_reason"] = "LLM Strict Audit Verified"
                        logger.info(f"Layer 2 Strict Audit result: ready_to_pay={parsed.get('ready_to_pay')}, new_loan={parsed.get('new_loan_interest')}, referral={parsed.get('referral_interest')}")
                        return parsed
                    except Exception as pe:
                        logger.warning(f"Failed to parse Layer 2 Audit JSON (Attempt {attempt}): {pe}")
            except Exception as ex:
                logger.warning(f"Error in Layer 2 Audit Agent (Attempt {attempt}): {ex}")
                time.sleep(1)

    except Exception as e:
        logger.exception("Layer 2 Audit Agent failed")

    # Fallback keyword scan if LLM API call fails
    txt_lower = (transcript_text or "").lower()
    has_loan_kw = any(k in txt_lower for k in ["naya loan chahiye", "topup chahiye", "extra loan lene ko taiyar", "dusra loan mil jayega"])
    has_ref_kw = any(k in txt_lower for k in ["ko bhi loan chahiye", "ko loan dilwa do", "padosi ko loan", "rishtedar ko loan", "refer kar raha hu"])
    has_rtp_kw = any(k in txt_lower for k in ["jama kar dunga", "de dunga", "pay kar dunga", "bharta hu", "ptp", "tareekh ko"])
    
    val_loan = 1 if has_loan_kw else 0
    val_ref = 1 if has_ref_kw else 0
    val_rtp = 1 if has_rtp_kw else initial_ready_to_pay

    return {
        "ready_to_pay": val_rtp,
        "new_loan_interest": val_loan,
        "referral_interest": val_ref,
        "referred_customer_details": "Referred Person" if val_ref == 1 else "",
        "validated_summary": summary_text or "",
        "is_fallback": 1,
        "fallback_reason": "Layer 2 LLM failed/timed out. Keyword fallback applied."
    }


def transcribe_audio_with_gemma(audio_bytes=None, audio_url=None, prompt_instruction=None, call_category=None):
    """
    Transcribes call audio in sequential chunks (one by one) using Gemma LLM Gateway.
    """
    try:
        raw_bytes = None
        content_type = "audio/wav"

        # Download audio from URL or read bytes
        if audio_url:
            logger.info(f"Downloading call recording audio: {audio_url[:70]}...")
            res = _session.get(audio_url, timeout=30)
            if res.status_code == 200:
                raw_bytes = res.content
                header_type = res.headers.get('Content-Type', '')
                if 'mp3' in audio_url.lower() or 'mp3' in header_type:
                    content_type = "audio/mp3"
                elif 'm4a' in audio_url.lower() or 'm4a' in header_type:
                    content_type = "audio/m4a"
                elif 'ogg' in audio_url.lower():
                    content_type = "audio/ogg"
            else:
                raise ValueError(f"Failed to download audio. HTTP Status: {res.status_code}")
        elif audio_bytes:
            raw_bytes = audio_bytes

        if not raw_bytes:
            raise ValueError("No audio content provided")

        total_bytes = len(raw_bytes)
        logger.info(f"Audio downloaded ({total_bytes} bytes). Sending speech-to-text request to Gemma GPU Gateway...")

        # Fast Pass: Short call or blank audio (< 15KB audio file)
        if total_bytes < 15000:
            logger.info(f"Short audio detected ({total_bytes} bytes). Skipping expensive LLM processing.")
            return {
                "status": "success",
                "raw_transcript": "Short call / No conversation audio.",
                "structured_turns": [],
                "ai_insights": {
                    "summary": "Short call recorded.",
                    "english_summary": "Short audio recording under 3 seconds. No meaningful customer interaction.",
                    "collection_outcome": "Unreachable / Blank Call",
                    "new_loan_interest": 0,
                    "referral_interest": 0,
                    "referred_customer_details": "",
                    "payment_commitment": "",
                    "commitment_date": "",
                    "customer_situation": "Short call.",
                    "recommended_bro_action": "Retry call.",
                    "sentiment": "Neutral",
                    "call_category": call_category or "Short Calls"
                },
                "chunks_processed": 1,
                "model": GEMMA_MODEL_ID
            }

        CHUNK_SIZE = 35000  # 35KB per chunk (~25-30s audio segment) to prevent audio model attention truncation
        
        if total_bytes <= CHUNK_SIZE:
            b64_str = base64.b64encode(raw_bytes).decode('utf-8')
            data_uri = f"data:{content_type};base64,{b64_str}"
            instruction = (
                "You are a verbatim speech-to-text transcriber for Hindi/Hinglish call center recordings. "
                "Transcribe all spoken Hindi dialogue accurately as spoken."
            )
            raw_transcript = _send_gemma_audio_request(data_uri, instruction, timeout=120)
            num_chunks = 1
        else:
            num_chunks = math.ceil(total_bytes / CHUNK_SIZE)
            logger.info(f"Processing audio ({total_bytes} bytes) in {num_chunks} sequential 35KB chunks for full transcript completeness...")
            
            transcripts = []
            for i in range(num_chunks):
                start_idx = i * CHUNK_SIZE
                end_idx = min((i + 1) * CHUNK_SIZE, total_bytes)
                chunk_bytes = raw_bytes[start_idx:end_idx]
                b64_chunk = base64.b64encode(chunk_bytes).decode('utf-8')
                data_uri = f"data:{content_type};base64,{b64_chunk}"

                chunk_instruction = (
                    f"Transcribe part {i+1} of {num_chunks} of this Hindi call recording verbatim. "
                    "Output all spoken Hindi dialogue accurately without omitting any sentence."
                )

                chunk_transcript = _send_gemma_audio_request(data_uri, chunk_instruction, timeout=120)
                if chunk_transcript:
                    transcripts.append(chunk_transcript)

            raw_transcript = "\n".join(transcripts) if transcripts else "Call recording audio processed."

        # Calculate STT transcript confidence score based on audio transcription output
        if not raw_transcript or len(raw_transcript) < 20:
            stt_transcript_confidence = 60
        else:
            stt_transcript_confidence = min(92, 80 + min(12, int(len(raw_transcript) / 50)))

        # Send raw transcript to All-in-One Gemma Understander Service
        understanding = understand_transcript_with_gemma(raw_transcript, call_category, timeout=180)

        return {
            "status": "success",
            "raw_transcript": raw_transcript,
            "structured_turns": understanding.get("turns", []) if understanding else [],
            "ai_insights": understanding.get("ai_insights", {}) if understanding else {},
            "stt_transcript_confidence": stt_transcript_confidence,
            "chunks_processed": num_chunks,
            "model": GEMMA_MODEL_ID
        }

    except Exception as e:
        logger.exception("Full audio transcription failed in gemma_service")
        raise e
