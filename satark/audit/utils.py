import io
import os
import lzma
import base64
import uuid
import tempfile
import subprocess
import decimal
import json
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from authentication.utils import log_info, log_error

COMPRESS_MAGIC = b'\x43\x4D\x50\x56\x31'  # "CMPV1"
IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'bmp', 'webp', 'tiff', 'gif'}
MAX_IMAGE_DIM = 2400
JPEG_QUALITY = 88

# Custom JSON encoder to handle decimals in JSON serialization
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


def save_base64_file(filename, base64_str):
    try:
        if not base64_str:
            return None
        if ';base64,' in base64_str:
            format, imgstr = base64_str.split(';base64,')
        else:
            imgstr = base64_str
        
        data = ContentFile(base64.b64decode(imgstr))
        ext = filename.split('.')[-1] if '.' in filename else 'bin'
        unique_name = f"audit_files/{uuid.uuid4()}.{ext}"
        path = default_storage.save(unique_name, data)
        return path
    except Exception as e:
        log_error(f"save_base64_file: failed: {str(e)}")
        return None


def _compress_image(file_bytes, filename):
    # pyrefly: ignore [missing-import]
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(file_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')

        w, h = img.size
        if w > MAX_IMAGE_DIM or h > MAX_IMAGE_DIM:
            ratio = min(MAX_IMAGE_DIM / w, MAX_IMAGE_DIM / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True)
        jpeg_bytes = buf.getvalue()

        if len(jpeg_bytes) < len(file_bytes):
            base = filename.rsplit('.', 1)[0]
            return jpeg_bytes, f"{base}.jpg"
    except Exception as e:
        log_error(f"_compress_image failed for {filename}: {e}")
    return None, filename


def _compress_pdf_ghostscript(file_bytes):
    inp = out = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(file_bytes)
            inp = f.name
        out = inp + '_gs_out.pdf'

        result = subprocess.run(
            [
                'gs', '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.4',
                '-dPDFSETTINGS=/ebook',
                '-dNOPAUSE', '-dQUIET', '-dBATCH',
                f'-sOutputFile={out}', inp,
            ],
            capture_output=True, timeout=30
        )

        if result.returncode == 0 and os.path.exists(out):
            with open(out, 'rb') as f:
                compressed = f.read()
            return compressed if len(compressed) < len(file_bytes) else None
    except FileNotFoundError:
        pass
    except Exception as e:
        log_error(f"_compress_pdf_ghostscript failed: {e}")
    finally:
        for path in (inp, out):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass
    return None


def _compress_pdf_pikepdf(file_bytes):
    try:
        # pyrefly: ignore [missing-import]
        import pikepdf
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(file_bytes)
            inp = f.name
        out = inp + '_pk_out.pdf'

        with pikepdf.open(inp) as pdf:
            pdf.save(out, compress_streams=True, recompress_flate=True)

        with open(out, 'rb') as f:
            compressed = f.read()
        return compressed if len(compressed) < len(file_bytes) else None
    except ImportError:
        pass
    except Exception as e:
        log_error(f"_compress_pdf_pikepdf failed: {e}")
    finally:
        for path in (inp, out):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass
    return None


def _compress_pdf_pypdf(file_bytes):
    # pyrefly: ignore [missing-import]
    from PIL import Image
    try:
        # pyrefly: ignore [missing-import]
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(io.BytesIO(file_bytes))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
            
        for page in writer.pages:
            for img in page.images:
                try:
                    original_img_size = len(img.data)
                    if original_img_size > 50 * 1024:
                        pil_img = img.image
                        w, h = pil_img.size
                        if w > 1200 or h > 1200:
                            ratio = min(1200 / w, 1200 / h)
                            new_w, new_h = int(w * ratio), int(h * ratio)
                            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        if pil_img.mode in ("RGBA", "LA", "P"):
                            pil_img = pil_img.convert("RGB")
                        img.replace(pil_img, quality=40)
                except Exception as e:
                    log_error(f"_compress_pdf_pypdf: failed to replace image: {e}")
        
        for page in writer.pages:
            try:
                page.compress_content_streams()
            except Exception:
                pass
        try:
            writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        except Exception:
            try:
                writer.compress_identical_objects()
            except Exception:
                pass
            
        out_buf = io.BytesIO()
        writer.write(out_buf)
        compressed = out_buf.getvalue()
        out_buf.close()
        
        if len(compressed) < len(file_bytes):
            return compressed
    except Exception as e:
        log_error(f"_compress_pdf_pypdf failed: {e}")
    return None


def _compress_pdf(file_bytes):
    compressed = _compress_pdf_pypdf(file_bytes)
    if compressed:
        return compressed
    compressed = _compress_pdf_pikepdf(file_bytes)
    if compressed:
        return compressed
    return file_bytes


def _apply_lzma(data):
    try:
        lzma_bytes = lzma.compress(data, preset=9)
        if len(lzma_bytes) < len(data):
            return lzma_bytes, b'\x01'
    except Exception as e:
        log_error(f"_apply_lzma failed: {e}")
    return data, b'\x00'


def compress_file_backend(file_bytes, filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    original_size = len(file_bytes)
    payload = file_bytes
    if ext in IMAGE_EXTS:
        compressed, filename = _compress_image(file_bytes, filename)
        if compressed:
            payload = compressed
    elif ext == 'pdf':
        payload = _compress_pdf(file_bytes)

    payload, lzma_flag = _apply_lzma(payload)
    result = COMPRESS_MAGIC + lzma_flag + payload
    ratio = (1 - len(result) / original_size) * 100 if original_size else 0
    print(f"[compress] {filename}: {original_size:,}B -> {len(result):,}B ({ratio:.1f}% reduction)")
    return result, filename


def decompress_file_backend(stored_bytes, filename):
    if not stored_bytes:
        return stored_bytes

    if stored_bytes[:5] == COMPRESS_MAGIC:
        compression_flag = stored_bytes[5:6]
        data = stored_bytes[6:]
        if compression_flag == b'\x01':
            return lzma.decompress(data)
        else:
            return data

    try:
        return lzma.decompress(stored_bytes)
    except Exception:
        pass

    try:
        import zlib
        return zlib.decompress(stored_bytes)
    except Exception:
        pass

    return stored_bytes
