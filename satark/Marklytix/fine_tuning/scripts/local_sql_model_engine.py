import os
import sys
import time
import re
import json

class LocalSqlModelEngine:
    """
    Dedicated Local SQL Model Engine for Sonata Satark.
    Runs ONNX Runtime neural network inference on CPU when a valid fine-tuned ONNX model file
    is loaded, with clean fallback to LLM Gateway when uninitialized.
    """
    _instance = None

    def __init__(self):
        self.model_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
        self.onnx_model_path = os.path.join(self.model_dir, "dedicated_sql_model.onnx")
        self.is_onnx_loaded = False
        self.session = None
        self.tokenizer = None
        self.input_name = None
        self.output_name = None
        self._init_local_model()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LocalSqlModelEngine()
        return cls._instance

    def _init_local_model(self):
        """
        Initializes ONNX Runtime session for local CPU neural inference.
        Sets is_onnx_loaded = True ONLY IF the ONNX model file loads valid protobuf
        and passes session initialization.
        """
        if os.path.exists(self.onnx_model_path):
            try:
                import onnxruntime as ort
                print(f"[LOCAL SQL MODEL ENGINE] Loading fine-tuned ONNX model from '{self.onnx_model_path}'...")
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 4
                self.session = ort.InferenceSession(self.onnx_model_path, opts, providers=['CPUExecutionProvider'])
                self.input_name = self.session.get_inputs()[0].name
                self.output_name = self.session.get_outputs()[0].name

                # Attempt to initialize HuggingFace tokenizer
                try:
                    from transformers import AutoTokenizer
                    self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-Coder-0.5B-Instruct")
                except Exception:
                    self.tokenizer = None

                self.is_onnx_loaded = True
                print(f"[LOCAL SQL MODEL ENGINE] Fine-tuned ONNX neural model loaded successfully on CPU! (Input: {self.input_name}, Output: {self.output_name})")
            except Exception as e:
                self.is_onnx_loaded = False
                self.session = None
                print(f"[LOCAL SQL MODEL ENGINE] ONNX model load failed ({e}). Fallback to Gateway activated.")
        else:
            self.is_onnx_loaded = False
            print(f"[LOCAL SQL MODEL ENGINE] No ONNX model file found at '{self.onnx_model_path}'. Local CPU inference inactive.")

    def _run_onnx_inference(self, prompt):
        """
        Executes real autoregressive neural network tensor inference via ONNX Runtime self.session.run(...).
        Generates clean, executable T-SQL query tokens autoregressively on CPU.
        """
        if not self.is_onnx_loaded or not self.session:
            return None

        try:
            import numpy as np
            if self.tokenizer:
                formatted_prompt = f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
                inputs = self.tokenizer(formatted_prompt, return_tensors="np")
                input_ids = list(inputs["input_ids"][0])
                prompt_len = len(input_ids)

                eos_tokens = {self.tokenizer.eos_token_id, 151645, 151643}

                # Autoregressive generation loop
                for _ in range(80):
                    cur_ids = np.array([input_ids], dtype=np.int64)
                    seq_len = cur_ids.shape[1]

                    input_feed = {}
                    for input_meta in self.session.get_inputs():
                        name = input_meta.name
                        shape = input_meta.shape

                        if name == "input_ids":
                            input_feed[name] = cur_ids
                        elif name == "attention_mask":
                            input_feed[name] = np.ones((1, seq_len), dtype=np.int64)
                        elif name == "position_ids":
                            input_feed[name] = np.arange(0, seq_len, dtype=np.int64).reshape(1, seq_len)
                        elif name.startswith("past_key_values"):
                            batch_size = 1
                            num_heads = shape[1] if (len(shape) > 1 and isinstance(shape[1], int)) else 2
                            head_dim = shape[3] if (len(shape) > 3 and isinstance(shape[3], int)) else 64
                            dtype = np.float16 if "float16" in str(input_meta.type) else np.float32
                            input_feed[name] = np.zeros((batch_size, num_heads, 0, head_dim), dtype=dtype)

                    outputs = self.session.run(None, input_feed)
                    logits = outputs[0]
                    next_token_id = int(np.argmax(logits[0, -1, :]))

                    if next_token_id in eos_tokens:
                        break
                    input_ids.append(next_token_id)

                # Decode only the newly generated T-SQL token IDs
                generated_tokens = input_ids[prompt_len:]
                sql_out = self.tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()

                # Extract SQL block if present
                sql_match = re.search(r'```sql\s*(.*?)\s*```', sql_out, re.DOTALL | re.IGNORECASE)
                if sql_match:
                    return sql_match.group(1).strip()
                return sql_out if sql_out else None
            else:
                return None
        except Exception as e:
            print(f"[LOCAL SQL MODEL ENGINE] ONNX session.run() execution notice: {e}")
            return None

    def generate_sql(self, prompt, user_query=""):
        """
        Generates T-SQL query using real local ONNX neural model inference if loaded.
        Returns None if local model is uninitialized (routing execution to Gemma Gateway).
        """
        if not self.is_onnx_loaded:
            return None

        start_t = time.time()
        neural_sql = self._run_onnx_inference(user_query or prompt)
        if neural_sql:
            latency = (time.time() - start_t) * 1000
            print(f"[LOCAL CPU ENGINE] ONNX neural inference executed in {latency:.2f}ms on CPU.")
            return neural_sql

        return None
