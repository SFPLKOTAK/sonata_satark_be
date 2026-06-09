import os
import base64
import logging
from pathlib import Path
from dotenv import load_dotenv
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

# Ensure .env variables are loaded with override
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env', override=True)

# 16-byte Key and IV for AES-128-CBC
# Strictly loaded from environment variables (.env)
raw_key = os.environ.get('SATARK_ENCRYPTION_KEY')
if not raw_key:
    raise ValueError("SATARK_ENCRYPTION_KEY not found in environment variables (.env)")
ENCRYPTION_KEY = raw_key.encode('utf-8')[:16]

raw_iv = os.environ.get('SATARK_ENCRYPTION_IV')
if not raw_iv:
    raise ValueError("SATARK_ENCRYPTION_IV not found in environment variables (.env)")
IV = raw_iv.encode('utf-8')[:16]

# --- SAFE LOGGING CONFIGURATION ---
logger = logging.getLogger('satark_auth')
logger.setLevel(logging.INFO)

log_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(log_dir, 'auth.log')

try:
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


# --- AES ENCRYPTION / DECRYPTION ---
def encrypt_data(plaintext_str: str) -> str:
    try:
        # PKCS7 padding to make plaintext block-aligned (128-bit block size = 16 bytes)
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext_str.encode('utf-8')) + padder.finalize()
        
        cipher = Cipher(algorithms.AES(ENCRYPTION_KEY), modes.CBC(IV), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        
        return base64.b64encode(ciphertext).decode('utf-8')
    except Exception as e:
        log_error(f"Encryption failed: {str(e)}")
        raise e

def decrypt_data(ciphertext_str: str) -> str:
    try:
        ciphertext = base64.b64decode(ciphertext_str.encode('utf-8'))
        
        cipher = Cipher(algorithms.AES(ENCRYPTION_KEY), modes.CBC(IV), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()
        
        # Remove PKCS7 padding
        unpadder = padding.PKCS7(128).unpadder()
        data = unpadder.update(padded_data) + unpadder.finalize()
        
        return data.decode('utf-8')
    except Exception as e:
        log_error(f"Decryption failed: {str(e)}")
        raise e
