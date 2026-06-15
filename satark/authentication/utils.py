import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env variables are loaded with override
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env', override=True)

# --- SAFE LOGGING CONFIGURATION ---
logger = logging.getLogger('satark_auth')
logger.setLevel(logging.INFO)

# --- UPDATED PATH ---
# Define the specific directory where you want the logs to go
log_dir = r"C:\Users\morev\sonata_satark_be\satark\logs"
log_file = os.path.join(log_dir, 'satark.log') # Named the file 'satark.log'

try:
    # Automatically create the directory if it doesn't exist yet
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception as e:
    print(f"Warning: Failed to initialize log file handler: {e}")

def log_info(message):
    try:
        logger.info(message)
    except Exception as e:
        print(f"[Log Info Error]: {e} | Original Message: {message}")

def log_error(message):
    try:
        logger.error(message)
    except Exception as e:
        print(f"[Log Error Error]: {e} | Original Error: {message}")


# --- PASS-THROUGH ENCRYPTION / DECRYPTION (NO CRYPTOGRAPHY) ---
def encrypt_data(plaintext_str: str) -> str:
    """Pass-through string (unencrypted plain text)."""
    return plaintext_str

def decrypt_data(ciphertext_str: str) -> str:
    """Pass-through string (unencrypted plain text)."""
    return ciphertext_str