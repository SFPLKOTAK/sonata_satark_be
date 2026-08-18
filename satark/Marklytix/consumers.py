import json
import uuid
import os
import re
import csv
import io
import time
import base64
import hashlib
import logging
import threading
import pandas as pd
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from dotenv import load_dotenv
from pathlib import Path

base_dir = Path(__file__).resolve().parent.parent
load_dotenv(base_dir / '.env', override=True)
load_dotenv(base_dir.parent / '.env', override=True)

# Vector Database imports (Chroma DB)
try:
    import chromadb
    from chromadb.utils import embedding_functions
    HAS_CHROMADB = True
except Exception as _e_chroma:
    HAS_CHROMADB = False
    logging.warning(f"ChromaDB not available: {_e_chroma}")

from channels.generic.websocket import WebsocketConsumer, AsyncWebsocketConsumer
from channels.exceptions import DenyConnection
from asgiref.sync import sync_to_async

from sqlalchemy import create_engine, text
from openai import OpenAI
from django.conf import settings
import builtins

# Thread-local storage for tracking active HierarchicalSearchConsumer execution
_marklytix_search_local = threading.local()
_original_print = builtins.print

def _custom_print(*args, **kwargs):
    # Call standard console print safely to avoid Unicode encoding crashes on Windows console
    try:
        _original_print(*args, **kwargs)
    except UnicodeEncodeError:
        try:
            # Fallback to printing ascii-safe representations
            safe_args = [str(arg).encode('ascii', 'backslashreplace').decode('ascii') for arg in args]
            _original_print(*safe_args, **kwargs)
        except Exception:
            pass
    except Exception:
        pass
        
    # Check if there is an active consumer in the current thread
    consumer = getattr(_marklytix_search_local, 'active_consumer', None)
    if consumer:
        msg = " ".join(str(arg) for arg in args)
        try:
            # Temporarily clear active consumer to avoid recursion if consumer.send triggers print
            _marklytix_search_local.active_consumer = None
            consumer.send(json.dumps({
                'type': 'progress',
                'message': msg
            }))
        except Exception:
            pass
        finally:
            _marklytix_search_local.active_consumer = consumer

builtins.print = _custom_print

# Redis setup with instant failure if Redis server is not running (prevents 15s retry stalls)
try:
    import redis
    from redis.retry import Retry
    from redis.backoff import NoBackoff
    rcache = redis.StrictRedis(
        host='localhost', 
        port=6379, 
        db=0, 
        socket_connect_timeout=0.1, 
        socket_timeout=0.1, 
        retry_on_timeout=False,
        retry=Retry(NoBackoff(), 0)
    )
except Exception:
    try:
        import redis
        rcache = redis.StrictRedis(host='localhost', port=6379, db=0, socket_connect_timeout=0.1, socket_timeout=0.1)
    except Exception:
        rcache = None

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AI Engine Selection ('gateway', 'groq', or 'vertex')
AI_ENGINE = os.getenv("AI_ENGINE", "gateway")  # Default to gateway LLM API

_model_info = os.getenv('GEMMA_MODEL_ID', 'google/gemma-4-E4B-it') if AI_ENGINE in ('gateway', 'gemma', 'llm_gateway') else ('llama-3.3-70b-versatile' if AI_ENGINE == 'groq' else 'LLM Gateway')
print("🤖" + "=" * 58 + "🤖")
print(f"🤖 ACTIVE AI ENGINE: {AI_ENGINE.upper()} | MODEL: {_model_info} 🤖")
print("🤖" + "=" * 58 + "🤖")

class GatewayChatSession:
    def __init__(self, client, model, system_instruction):
        self.client = client
        self.model = model
        self.system_instruction = system_instruction
        self.history = []

    def send_message(self, content):
        if isinstance(content, list):
            user_msg = " ".join([str(c) for c in content])
        else:
            user_msg = str(content)
            
        messages = [{"role": "system", "content": self.system_instruction}]
        for entry in self.history:
            messages.append(entry)
        messages.append({"role": "user", "content": user_msg})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=500
        )
        
        reply = response.choices[0].message.content if (response.choices and response.choices[0].message and response.choices[0].message.content) else ""
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": reply})
        
        class ResponseWrapper:
            def __init__(self, text):
                self.text = text
        return ResponseWrapper(reply)

class GatewayModel:
    def __init__(self, model_name, system_instruction):
        self.model_name = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")
        self.system_instruction = system_instruction
        self.api_key = os.getenv("GEMMA_API_KEY", "sk-Y82UGER7Dw97we65RxwfnjRsiWb1CFH0vBB_zqgszUk")
        self.base_url = os.getenv("GEMMA_BASE_URL", "http://43.242.226.49:8100/v1")
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
    def start_chat(self):
        return GatewayChatSession(self.client, self.model_name, self.system_instruction)

    def generate_content(self, contents, **kwargs):
        if isinstance(contents, list):
            user_msg = " ".join([str(c) for c in contents])
        else:
            user_msg = str(contents)
            
        max_tok = kwargs.get('max_tokens', 500)
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.3,
            max_tokens=max_tok
        )
        reply = response.choices[0].message.content if (response.choices and response.choices[0].message and response.choices[0].message.content) else ""
        class ResponseWrapper:
            def __init__(self, text):
                self.text = text
        return ResponseWrapper(reply)

class GroqChatSession:
    def __init__(self, client, model, system_instruction):
        self.client = client
        self.model = model
        self.system_instruction = system_instruction
        self.history = []

    def send_message(self, content):
        if isinstance(content, list):
            user_msg = " ".join([str(c) for c in content])
        else:
            user_msg = str(content)
            
        messages = [{"role": "system", "content": self.system_instruction}]
        for entry in self.history:
            messages.append(entry)
        messages.append({"role": "user", "content": user_msg})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=4096
        )
        
        reply = response.choices[0].message.content
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": reply})
        
        class ResponseWrapper:
            def __init__(self, text):
                self.text = text
        return ResponseWrapper(reply)

class GroqModel:
    def __init__(self, model_name, system_instruction):
        self.model_name = "llama-3.3-70b-versatile"
        self.system_instruction = system_instruction
        self.client = OpenAI(
            api_key=os.getenv('GROQ_API_KEY'),
            base_url="https://api.groq.com/openai/v1"
        )
        
    def start_chat(self):
        return GroqChatSession(self.client, self.model_name, self.system_instruction)

    def generate_content(self, contents, **kwargs):
        if isinstance(contents, list):
            user_msg = " ".join([str(c) for c in contents])
        else:
            user_msg = str(contents)
            
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.3,
            max_tokens=4096
        )
        reply = response.choices[0].message.content
        class ResponseWrapper:
            def __init__(self, text):
                self.text = text
        return ResponseWrapper(reply)

def AIModel(model_name, system_instruction):
    if AI_ENGINE in ("gateway", "gemma", "llm_gateway"):
        return GatewayModel(model_name, system_instruction)
    elif AI_ENGINE == "groq":
        return GroqModel(model_name, system_instruction)
    return GatewayModel(model_name, system_instruction)


class TreeNode:
    """
    Represents a node in the hierarchical search tree
    Each node can be a category, subcategory, or table group
    """
    def __init__(self, name, level, agent_type, tables=None, children=None):
        self.name = name                    # Node name (e.g., "finance", "budget", "expense_tables")
        self.level = level                  # 1=Category, 2=Subcategory, 3=Table
        self.agent_type = agent_type        # Type of agent handling this node
        self.tables = tables or []          # List of tables for this node
        self.children = children or []      # Child nodes
        self.parent = None                  # Parent node reference
        self.search_keywords = []           # Keywords for AI classification
        self.prompts = {}                   # Different prompts for different scenarios
        self.confidence_threshold = 0.7     # Minimum confidence for selection
        self.is_active = True               # Whether this node is active

    def add_child(self, child_node):
        """Add a child node to this node"""
        child_node.parent = self
        self.children.append(child_node)

    def get_path(self):
        """Get the full path from root to this node"""
        path = []
        current = self
        while current:
            path.insert(0, current.name)
            current = current.parent
        return "->".join(path)

    def find_child_by_name(self, name):
        """Find a child node by name"""
        for child in self.children:
            if child.name == name:
                return child
        return None

    def find_child_by_path(self, path):
        """Find a child node by path"""
        for child in self.children:
            if child.name == path:
                return child
        return None

    def get_all_tables(self):
        """Get all tables in this node and its children"""
        tables = list(self.tables)
        for child in self.children:
            tables.extend(child.get_all_tables())
        return list(set(tables))

class DatabaseSearchTree:
    """
    Manages the hierarchical tree structure for database search
    Handles category -> subcategory -> table selection logic
    """
    def __init__(self):
        self.root = None
        self.categories = {}      # Level 1 nodes
        self.subcategories = {}   # Level 2 nodes  
        self.tables = {}          # Level 3 nodes
        self.total_tables = 0
        self.search_cache = {}    # Cache for search results

    def add_category(self, name, keywords, tables = None):
        """Add a new category to the tree"""
        category = TreeNode(
            name = name,
            level = 1,
            agent_type = "category_agent",
            tables = tables or [],
        )
        category.search_keywords = keywords
        self.categories[name] = category
        if not self.root:
            self.root = category
        return category

    def add_subcategory(self, parent_name, name, keywords, tables = None):
        """Add a new subcategory under a parent category"""
        parent = self.categories.get(parent_name)
        if not parent:
            raise ValueError(f"Parent category {parent_name} not found")
        subcategory = TreeNode(
            name = name,
            level = 2,
            agent_type = "subcategory_agent",
            tables = tables or [],
        )
        subcategory.search_keywords = keywords
        parent.add_child(subcategory)
        return subcategory

    def add_table_group(self, parent_path, name, tables, keywords=None):
        """Add a table group under a subcategory"""
        # parent_path format: "category_subcategory"
        parent = self.subcategories.get(parent_path)
        if not parent:
            raise ValueError(f"Parent subcategory '{parent_path}' not found")
            
        table_group = TreeNode(
            name=name,
            level=3,
            agent_type="table_agent",
            tables=tables,
        )
        table_group.search_keywords = keywords or []
        parent.add_child(table_group)
        self.tables[f"{parent_path}_{name}"] = table_group
        self.total_tables += len(tables)
        return table_group
        
    def get_node_by_path(self, path):
        """Get a node by its path (e.g., 'finance_budget_expense_tables')"""
        parts = path.split('_')
        if len(parts) < 2:
            return None
            
        # Find category
        category = self.categories.get(parts[0])
        if not category:
            return None
            
        if len(parts) == 2:
            return category.find_child_by_name(parts[1])
        elif len(parts) == 3:
            subcategory = category.find_child_by_name(parts[1])
            if subcategory:
                return subcategory.find_child_by_name(parts[2])
        return None
        
    def get_all_categories(self):
        """Get list of all category names"""
        return list(self.categories.keys())
        
    def get_subcategories_for_category(self, category_name):
        """Get all subcategories for a given category"""
        category = self.categories.get(category_name)
        if category:
            return [child.name for child in category.children]
        return []
        
    def get_tables_for_path(self, path):
        """Get all tables for a given path"""
        node = self.get_node_by_path(path)
        if node:
            return node.get_all_tables()
        return []
        
    def search_nodes_by_keywords(self, keywords, level=None):
        """Search for nodes matching given keywords"""
        results = []
        search_terms = [kw.lower() for kw in keywords]
        
        def search_recursive(node):
            if level and node.level != level:
                return
                
            # Check if any search keyword matches node keywords
            node_keywords = [kw.lower() for kw in node.search_keywords]
            matches = sum(1 for term in search_terms if any(term in nk for nk in node_keywords))
            
            if matches > 0:
                results.append({
                    'node': node,
                    'matches': matches,
                    'path': node.get_path(),
                    'confidence': matches / len(search_terms)
                })
                
            # Search children
            for child in node.children:
                search_recursive(child)
        
        if self.root:
            search_recursive(self.root)
            
        # Sort by confidence and matches
        results.sort(key=lambda x: (x['confidence'], x['matches']), reverse=True)
        return results

# -------------------------------------- Hierarchical Search Consumer ------------------------------------- #
class HierarchicalSearchConsumer(WebsocketConsumer):
    """
    Main consumer that uses the three-level agent system for efficient database searching
    Level 1: Category classification
    Level 2: Subcategory classification  
    Level 3: Table selection with specialized prompts
    """
    
    # Class-level cache for database tree, keywords and prompts to avoid repetitive DB hits
    _keywords_loaded = False
    _category_keywords_db = {}
    _subcategory_keywords_db = {}
    _search_tree = None
    _subcategory_prompts_cache = {}
    _main_prompts_cache = {}
    
    # Chroma DB Vector Search Cache
    _chroma_client = None
    _chroma_ef = None
    _cat_collection = None
    _subcat_collection = None
    _chroma_initialized = False
    
    def connect(self):
        self.language = "english"
        self.accept()
        
        # Get prompt_name from URL parameters
        self.prompt_name = self.scope['url_route']['kwargs'].get('prompt_name', 'MarklytixChat')
        
        # SQL Server initialization (same as CommonDynamicConsumer)
        self.sql_user = os.environ.get('DATABASE_USER', '')
        self.sql_password = os.environ.get('DATABASE_PASSWORD', '')
        self.sql_server = os.environ.get('DATABASE_HOST', '')
        self.sql_db = os.environ.get('DATABASE_NAME', '')
        
        connection_url = (
            f"mssql+pyodbc://{self.sql_user}:{quote_plus(self.sql_password)}@{self.sql_server}/{self.sql_db}"
            f'?driver={os.environ.get("DATABASE_DRIVER", "ODBC Driver 17 for SQL Server").replace(" ", "+")}'
        )
        
        self.engine = create_engine(connection_url, fast_executemany=True)
        # Note: self.conn connection setup removed to avoid blocking connect handshake
        self.conn = None
        
        # Defer ChatID generation to run lazily on first query execution
        self.chat_id = None
        self.user_id = 1
        
        # Initialize cache settings
        self.cache_ttl = 3600  # Cache TTL in seconds (1 hour)
        self.cache_prefix = f"marklytix_search_{self.prompt_name.lower()}:"
        
        # Check if already initialized at class level
        if not getattr(HierarchicalSearchConsumer, '_keywords_loaded', False) or getattr(HierarchicalSearchConsumer, '_search_tree', None) is None:
            self.load_keywords_from_database()
            self.search_tree = self.build_database_tree_with_prompts()
            
            HierarchicalSearchConsumer._category_keywords_db = self.category_keywords_db
            HierarchicalSearchConsumer._subcategory_keywords_db = self.subcategory_keywords_db
            HierarchicalSearchConsumer._search_tree = self.search_tree
            HierarchicalSearchConsumer._keywords_loaded = True
            print(f"Loaded hierarchical search configurations from DB ({len(self.category_keywords_db)} categories).")
                
            # Initialize Chroma DB local persistent vector store
            self._init_chroma_vector_store()
        else:
            self.category_keywords_db = getattr(HierarchicalSearchConsumer, '_category_keywords_db', {})
            self.subcategory_keywords_db = getattr(HierarchicalSearchConsumer, '_subcategory_keywords_db', {})
            self.search_tree = getattr(HierarchicalSearchConsumer, '_search_tree', None)
        
        # Initialize AI models
        self.get_model()
        
        print(f"Hierarchical search consumer initialized with {len(self.search_tree.categories)} categories")

    def disconnect(self, close_code):
        # Close SQL connection
        if getattr(self, 'conn', None) is not None:
            self.conn.close()
        if hasattr(self, 'engine'):
            self.engine.dispose()
        print(f"Disconnected from hierarchical search: {self.prompt_name}")

    def receive(self, text_data):
        _marklytix_search_local.active_consumer = self
        try:
            self._receive_internal(text_data)
        finally:
            _marklytix_search_local.active_consumer = None

    def _receive_internal(self, text_data):
        start_time = datetime.now()
        data = json.loads(text_data)
        message = data['message']
        username = data['username']

        # Skip acknowledgment for internal commands
        if message not in ("cache_stats", "clear_cache", "download_csv"):
            # Send immediate acknowledgment so frontend shows activity instantly
            # instead of showing blank 'Thinking...' during Redis cache lookup
            self.send(json.dumps({
                'type': 'progress',
                'message': f'Received query: "{message[:60]}{"..." if len(message) > 60 else ""}"'
            }))

        # Handle conversation history context
        conversation_history = data.get('conversation_history', [])
        is_first_message = data.get('is_first_message', False)
        chat_id = data.get('chat_id', None)

        # If this is a continuation of an existing chat, use the provided chat_id
        if chat_id and is_first_message:
            self.chat_id = chat_id

        # Prepare context for AI models
        context_message = message
        if conversation_history:
            context = self.build_conversation_context(conversation_history)
            context_message = f"Previous conversation context:\n{context}\n\nCurrent question: {message}"

        # Generate cache key for the message
        cache_key = self.generate_cache_key(message)
        
        # Check if response is already cached
        cached_response = self.get_cached_response(cache_key)
        if cached_response:
            cached_response['cache_hit'] = True
            cached_response['cache_key'] = cache_key
            cached_response['cached_at'] = datetime.now().isoformat()
            cached_response['prompt_name'] = self.prompt_name
            self.send(json.dumps(cached_response))
            logger.info(f"Served cached response for message: {message[:50]}...")
            return

        # Cache management commands
        if message.lower() == "cache_stats":
            cache_stats = self.get_cache_stats()
            response = json.dumps({
                'type': 'cache_stats',
                'stats': cache_stats
            })
            self.send(response)
            return
            
        if message.lower() == "clear_cache":
            self.clear_cache()
            response = json.dumps({
                'type': 'cache_cleared',
                'message': 'Cache cleared successfully'
            })
            self.send(response)
            return

        # Download CSV for the last stored question
        global db_results
        if message == "download_csv":
            csv_data = self.generate_csv(db_results.to_dict('records'))
            response = json.dumps({
                'type': 'csv_download',
                'csv_data': csv_data,
                'filename': f'marklytix_search_data_{self.prompt_name}_{start_time.strftime("%Y%m%d_%H%M%S")}.csv'
            })
            self.send(response)
            return 

        # Start the three-level hierarchical search process
        print("🚀" + "=" * 58 + "🚀")
        print("🎯 STARTING HIERARCHICAL SEARCH PROCESS 🎯")
        print("🚀" + "=" * 58 + "🚀")
        print(f"🤖 Active AI Engine: {AI_ENGINE.upper()} | Model: {_model_info}")
        print(f"📝 User Query: {message[:100]}{'...' if len(message) > 100 else ''}")
        print(f"🔍 Context Message Length: {len(context_message)} characters")
        print(f"💾 Cache Key: {cache_key}")
        print("")
        
        # Level 1: Category Classification
        print("🔍" + "-" * 50 + "🔍")
        print("🎯 LEVEL 1: CATEGORY CLASSIFICATION 🎯")
        print("🔍" + "-" * 50 + "🔍")
        start_time_1 = datetime.now()
        category_result = self.classify_category_hybrid(message, self.search_tree)
        end_time_1 = datetime.now()
        
        print(f"✅ Category: {category_result['category']} (confidence: {category_result['confidence']:.2f})")
        print(f"⚙️  Method: {category_result['method']}")
        print(f"💭 Reasoning: {category_result['reasoning']}")
        print(f"⏱️  Time taken: {(end_time_1 - start_time_1).total_seconds():.3f} seconds")
        print("")
        
        # Check if category is 'general'
        if category_result['category'].lower().strip() == 'general':
            print("ℹ️ Category classified as 'general', skipping subcategory classification and table selection.")
            
            subcategory_result = {
                'subcategory': 'general',
                'confidence': 1.0,
                'method': 'general_chitchat',
                'reasoning': 'General chitchat query detected',
                'time_taken': 0.0
            }
            start_time_2 = end_time_2 = datetime.now()
            
            table_result = {
                'method': 'general_chitchat',
                'tables': [],
                'query': 'No query found',
                'confidence': 1.0,
                'reasoning': 'General chitchat query',
                'prompt_used': 'N/A',
                'time_taken': 0.0
            }
            start_time_3 = end_time_3 = datetime.now()
        else:
            # Level 2: Subcategory Classification
            print("🔍" + "-" * 50 + "🔍")
            print("🎯 LEVEL 2: SUBCATEGORY CLASSIFICATION 🎯")
            print("🔍" + "-" * 50 + "🔍")
            start_time_2 = datetime.now()
            subcategory_result = self.classify_subcategory_hybrid(
                message, 
                category_result['category'], 
                self.search_tree
            )
            end_time_2 = datetime.now()
            
            print(f"✅ Subcategory: {subcategory_result['subcategory']} (confidence: {subcategory_result['confidence']:.2f})")
            print(f"⚙️  Method: {subcategory_result['method']}")
            print(f"💭 Reasoning: {subcategory_result['reasoning']}")
            print(f"⏱️  Time taken: {(end_time_2 - start_time_2).total_seconds():.3f} seconds")
            print("")
            
            # Level 3: Table Selection with Specialized Prompts
            print("🔍" + "-" * 50 + "🔍")
            print("🎯 LEVEL 3: TABLE SELECTION & QUERY GENERATION 🎯")
            print("🔍" + "-" * 50 + "🔍")
            start_time_3 = datetime.now()
            table_result = self.select_tables_with_specialized_prompt(
                context_message,
                category_result['category'],
                subcategory_result['subcategory'],
                self.search_tree
            )
            end_time_3 = datetime.now()
            
            print(f"✅ Tables: {table_result['tables']} (confidence: {table_result['confidence']:.2f})")
            print(f"⚙️  Method: {table_result['method']}")
            print(f"💭 Reasoning: {table_result['reasoning']}")
            print(f"📋 Generated Query: {table_result['query'][:100] if table_result['query'] else 'None'}{'...' if table_result['query'] and len(table_result['query']) > 100 else ''}")
            print(f"⏱️  Time taken: {(end_time_3 - start_time_3).total_seconds():.3f} seconds")
            print("")
        
        # Execute the generated SQL query
        print("🔍" + "-" * 50 + "🔍")
        print("🎯 LEVEL 4: SQL QUERY EXECUTION 🎯")
        print("🔍" + "-" * 50 + "🔍")
        start_time_4 = datetime.now()
        end_time_4 = None
        
        query_strip = table_result['query'].strip().upper() if table_result['query'] else ""
        is_sql = query_strip.startswith('SELECT') or query_strip.startswith('EXEC') or query_strip.startswith('WITH')
        
        if table_result['query'] and table_result['query'] != "No query found" and is_sql:
            try:
                print("🚀" + "=" * 48 + "🚀")
                print("⚡ EXECUTING GENERATED SQL QUERY ⚡")
                print("🚀" + "=" * 48 + "🚀")
                print(f"📋 Query to execute: {table_result['query']}")
                print("🔧" + "-" * 48 + "🔧")
                
                # Execute SQL query
                print("🔄 Executing SQL query against database...")
                # Check if it's a stored procedure call
                if table_result['query'].strip().upper().startswith('EXEC') or table_result['query'].strip().upper().startswith('EXECUTE'):
                    # For stored procedures, try multiple approaches
                    print("🔍 Detected stored procedure call, trying multiple execution methods...")
                    db_results = None
                    
                    # Method 1: Try pd.read_sql
                    try:
                        print("🔧 Method 1: Trying pd.read_sql method...")
                        db_results = pd.read_sql(table_result['query'], self.engine)
                        print("✅ pd.read_sql method succeeded!")
                    except Exception as e1:
                        print(f"❌ pd.read_sql failed: {e1}")
                        
                        # Method 2: Try with raw connection
                        try:
                            print("🔧 Method 2: Trying raw connection method...")
                            raw_conn = self.engine.raw_connection()
                            db_results = pd.read_sql(table_result['query'], raw_conn)
                            raw_conn.close()
                            print("✅ Raw connection method succeeded!")
                        except Exception as e2:
                            print(f"❌ Raw connection failed: {e2}")
                            
                            # Method 3: Try with text() wrapper
                            try:
                                print("🔧 Method 3: Trying text() wrapper method...")
                                db_results = pd.read_sql(text(table_result['query']), self.engine)
                                print("✅ Text wrapper method succeeded!")
                            except Exception as e3:
                                print(f"❌ Text wrapper failed: {e3}")
                                raise e3
                    
                    if db_results is None:
                        raise Exception("All stored procedure execution methods failed")
                else:
                    # For regular SELECT queries, use read_sql_query
                    print("🔧 Using robust read_sql_query for Hierarchical Search...")
                    try:
                        db_results = pd.read_sql_query(text(table_result['query']), self.engine)
                    except Exception as e_reg:
                        print(f"🔧 Regular query failed, trying raw connection fallback: {e_reg}")
                        raw_conn = self.engine.raw_connection()
                        try:
                            # Use raw connection directly for maximum compatibility
                            db_results = pd.read_sql(table_result['query'], raw_conn)
                        finally:
                            raw_conn.close()
                
                print(f"🎉 SQL query executed successfully!")
                print(f"📊 Query returned {len(db_results)} rows")
                print(f"📋 Columns: {list(db_results.columns)}")
                print("")
                
                # Prepare HTML table output
                print("🔄 Preparing HTML table output...")
                output = db_results.head(5).to_html(index=False, na_rep="-")
                db_results_1 = db_results.head(5)
                print(f"✅ HTML table prepared with {len(db_results_1)} rows")
                print("")
                
                # Prepare data for AI interpreter
                print("🔄 Preparing data for AI interpreter...")
                interpreter_input = f"Database results: {db_results_1.to_json(orient='records')}"
                print(f"📝 Interpreter input prepared (length: {len(interpreter_input)} characters)")
                print("")
                
                # Send to AI interpreter
                print("🤖 Sending data to AI interpreter...")
                interpreter_response = self.chat1.send_message([interpreter_input, context_message])
                ai_response = interpreter_response.text
                print(f"✅ AI interpreter response received!")
                print(f"📊 Response type: {type(ai_response)}")
                print(f"📏 Response length: {len(ai_response)} characters")
                print("")
                
                # Calculate execution time
                end_time_4 = datetime.now()
                execution_time = (end_time_4 - start_time_4).total_seconds()
                print(f"⏱️  Total execution time: {execution_time:.2f} seconds")
                print("")
                
                # Set final outputs
                table = output
                output = ai_response
                
                print("🎉" + "=" * 48 + "🎉")
                print("✅ SQL QUERY EXECUTION COMPLETED SUCCESSFULLY ✅")
                print("🎉" + "=" * 48 + "🎉")
                print(f"📊 Table data preview: {len(db_results_1)} rows")
                print(f"🤖 AI response preview: {ai_response[:100]}..." if len(ai_response) > 100 else f"🤖 AI response: {ai_response}")
                print("🎉" + "=" * 48 + "🎉")
                print("")
                    
            except Exception as e:
                print("💥" + "=" * 48 + "💥")
                print("❌ SQL QUERY EXECUTION FAILED ❌")
                print("💥" + "=" * 48 + "💥")
                print(f"🚨 Error type: {type(e).__name__}")
                print(f"🚨 Error message: {str(e)}")
                print(f"🔍 Query that failed: {table_result['query']}")
                logger.error(f"Error executing SQL query: {e}")
                output = f"Error executing query: {str(e)}"
                table = ""
                end_time_4 = datetime.now()  # Set end_time_4 even in error case
                print("💥" + "=" * 48 + "💥")
                print("")
        else:
            print("🔄 No SQL query generated or query is not executable, using AI interpreter/response directly...")
            if table_result['query'] and ("no tables available" in table_result['query'].lower() or not is_sql and table_result['query'] != "No query found"):
                output = "I couldn't find any relevant tables in the database to answer your question. Could you please rephrase your request or try another category?"
                table = ""
                end_time_4 = datetime.now()
            else:
                interpreter_input = f"question : {context_message}"
                interpreter_response = self.chat1.send_message([interpreter_input, context_message])
                ai_response = interpreter_response.text
                print(f"🤖 AI Response Type: {type(ai_response)}")
                end_time_4 = datetime.now()
                print(f"⏱️  Time taken for response generation: {(end_time_4 - start_time_4).total_seconds():.3f} seconds")
                output = ai_response
                table = ""
            print("")
       
        # Calculate total execution time
        total_execution_time = (datetime.now() - start_time).total_seconds()
        
        # Prepare response data with hierarchical search details
        response_data = {
            'type': 'marklytix_search_response',
            'message': message,
            'username': username,
            'ai_response': output,
            'generated_query': table_result['query'],
            'ai_response_table': table,
            
            # Overall timing information
            'total_execution_time': total_execution_time,
            
            # Hierarchical search details — omit for general chitchat so the frontend hides the Process Log tab
            'hierarchical_search': None if category_result['category'].lower().strip() == 'general' else {
                'level_1_category': {
                    'category': category_result['category'],
                    'confidence': category_result['confidence'],
                    'method': category_result['method'],
                    'reasoning': category_result['reasoning'],
                    'time_taken': (end_time_1 - start_time_1).total_seconds()
                },
                'level_2_subcategory': {
                    'subcategory': subcategory_result['subcategory'],
                    'confidence': subcategory_result['confidence'],
                    'method': subcategory_result['method'],
                    'reasoning': subcategory_result['reasoning'],
                    'time_taken': (end_time_2 - start_time_2).total_seconds()
                },
                'level_3_tables': {
                    'tables': table_result['tables'],
                    'confidence': table_result['confidence'],
                    'method': table_result['method'],
                    'reasoning': table_result['reasoning'],
                    'prompt_used': table_result.get('prompt_used', 'N/A'),
                    'time_taken': (end_time_3 - start_time_3).total_seconds()
                }
            },
            
            # Individual timing information
            'time_taken_category_classification': (end_time_1 - start_time_1).total_seconds(),
            'time_taken_subcategory_classification': (end_time_2 - start_time_2).total_seconds(),
            'time_taken_table_selection': (end_time_3 - start_time_3).total_seconds(),
            'time_taken_query_execution': (end_time_4 - start_time_4).total_seconds() if end_time_4 else 0,
            
            # Cache information
            'cache_hit': False,
            'cache_key': cache_key,
            'processed_at': datetime.now().isoformat(),
            'prompt_name': self.prompt_name
        }
        
        # Store response in cache
        self.set_cached_response(cache_key, response_data)
        
        # Send response
        print("📤" + "=" * 48 + "📤")
        print("🚀 SENDING RESPONSE TO CLIENT 🚀")
        print("📤" + "=" * 48 + "📤")
        response = json.dumps(response_data)
        self.send(response)
        end_time = datetime.now()
        print(f"⏰ END TIME: {end_time}")
        print(f"⏱️  Total hierarchical search time: {total_execution_time:.3f} seconds")
        print("🎯" + "=" * 48 + "🎯")
        print("✅ HIERARCHICAL SEARCH PROCESS COMPLETED ✅")
        print("🎯" + "=" * 48 + "🎯")
        print("")
        
        # Store in DB with auto-generated ChatID
        try:
            # Generate ChatID lazily if not set
            if self.chat_id is None:
                self.chat_id = self.generate_new_chat_id()
                
            with self.engine.begin() as connection:
                insert_query = """
                    INSERT INTO dbo.Marklytix_ChatHistory
                        (ChatID, UserID, Username, Sender, Question, Generated_Query, Result_Generated, Response_Table, Query_Creation_Time, Query_Execution_Time, Created_At) 
                    VALUES
                        (:chatid, :userid, :username, :sender, :question, :generated_query, :result_generated, :response_table, :query_creation_time, :query_execution_time, GETDATE())
                """

                # Insert user message
                connection.execute(
                    text(insert_query),
                    {
                        "chatid": self.chat_id,
                        "userid": self.user_id,
                        "username": username,
                        "sender": "user",
                        "question": message,
                        "generated_query": None,
                        "result_generated": None,
                        "response_table": None,
                        "query_creation_time": None,
                        "query_execution_time": None,
                    }
                )

                # Insert bot response
                connection.execute(
                    text(insert_query),
                    {
                        "chatid": self.chat_id,
                        "userid": self.user_id,
                        "username": username,
                        "sender": "bot",
                        "question": message,
                        "generated_query": table_result['query'],
                        "result_generated": output,
                        "response_table": table,
                        "query_creation_time": (end_time_3 - start_time_3).total_seconds(),
                        "query_execution_time": (end_time_4 - start_time_4).total_seconds() if end_time_4 else 0,
                    }
                )
        except Exception as e:
            logger.error(f"Error inserting chat history: {e}")

    # Include all the helper methods from CommonDynamicConsumer
    def generate_cache_key(self, message):
        """Generate a unique cache key for the message"""
        normalized_message = message.lower().strip()
        message_hash = hashlib.md5(normalized_message.encode()).hexdigest()
        return f"{self.cache_prefix}{message_hash}"

    def get_cached_response(self, cache_key):
        """Retrieve cached response if it exists"""
        try:
            cached_data = rcache.get(cache_key)
            if cached_data:
                response_data = pickle.loads(cached_data)
                logger.info(f"Cache hit for key: {cache_key}")
                return response_data
        except Exception:
            pass
        return None

    def set_cached_response(self, cache_key, response_data):
        """Store response in cache"""
        try:
            serialized_data = pickle.dumps(response_data)
            rcache.setex(cache_key, self.cache_ttl, serialized_data)
            logger.info(f"Cached response for key: {cache_key}")
        except Exception:
            pass

    def clear_cache(self, pattern=None):
        """Clear cache entries (optional: with pattern matching)"""
        try:
            if pattern:
                keys = rcache.keys(f"{self.cache_prefix}{pattern}*")
            else:
                keys = rcache.keys(f"{self.cache_prefix}*")
            
            if keys:
                rcache.delete(*keys)
                logger.info(f"Cleared {len(keys)} cache entries")
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")

    def get_cache_stats(self):
        """Get cache statistics"""
        try:
            keys = rcache.keys(f"{self.cache_prefix}*")
            return {
                'total_cached_entries': len(keys),
                'cache_prefix': self.cache_prefix,
                'cache_ttl': self.cache_ttl,
                'prompt_name': self.prompt_name
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {'error': str(e)}

    def generate_new_chat_id(self):
        """Generate a new unique ChatID by finding the maximum existing ChatID and incrementing it"""
        try:
            with self.engine.begin() as connection:
                max_chat_id_query = text("SELECT ISNULL(MAX(ChatID), 0) as max_chat_id FROM dbo.Marklytix_ChatHistory")
                result = connection.execute(max_chat_id_query)
                max_chat_id = result.fetchone()[0]
                
                new_chat_id = max_chat_id + 1
                print(f"Generated new ChatID: {new_chat_id}")
                return new_chat_id
        except Exception as e:
            logger.error(f"Error generating new ChatID: {e}")
            import time
            fallback_id = int(time.time())
            print(f"Using fallback ChatID: {fallback_id}")
            return fallback_id

    def build_conversation_context(self, conversation_history):
        """Build a formatted context string from conversation history.
        Handles both formats:
          - Frontend sends: {'role': 'user'/'assistant', 'content': '...'}
          - Legacy format:  {'type': 'user'/'bot', 'text': '...'}
        """
        context_parts = []
        
        for msg in conversation_history:
            try:
                # Frontend format: role/content
                role = msg.get('role') or msg.get('type', '')
                text = msg.get('content') or msg.get('text', '')
                
                if not text:
                    continue
                    
                if role in ('user',):
                    context_parts.append(f"User: {text}")
                elif role in ('assistant', 'bot'):
                    context_parts.append(f"Bot: {text}")
            except Exception:
                continue
        
        return "\n".join(context_parts)


    def generate_csv(self, data):
        output = io.StringIO()
        writer = csv.writer(output)
        if data and len(data) > 0:
            writer.writerow(data[0].keys())
            for row in data:
                writer.writerow(row.values())
        return output.getvalue()

    def get_model(self):
        # Common prompt for all consumers (hardcoded as requested)
        prompt_1 = """
        You are a helpful chatbot designed to process and present data in a clear and friendly manner. When the user provides a dictionary or a DataFrame or a simple text as input, your task is to interpret the data and return it in a well-structured, natural-language format that is easy to read and understand. Follow these guidelines:
        Input Handling:
            Accept input in the form of a dictionary (e.g., {"name": "Alice", "age": 25, "city": "New York"}) or a DataFrame (e.g., a table with columns and rows).
            If the input is unclear or malformed, politely ask the user to clarify or provide the data in a valid format.
            if it is simple text like "Hello, how are you?" then just return the text as is.
        Output Formatting:
            Transform the data into a conversational, narrative-style response rather than a raw or technical dump.
            Use complete sentences and proper grammar to describe the data.
            Organize the information logically, such as grouping related items or summarizing key points.
            Avoid using code syntax, tables, or bullet points unless the user explicitly requests them—focus on prose instead.
            Make the tone friendly, engaging, and professional.
        Examples:
            For a dictionary like {"name": "Alice", "age": 25, "city": "New York"}, respond with:
            "It looks like we have some information about a person named Alice. She's 25 years old and lives in New York, a vibrant and bustling city!"
            For a DataFrame like {"Name": ["Alice", "Bob"], "Age": [25, 30], "City": ["New York", "London"]}, respond with:
            "Here's what I found in the data: Alice is 25 years old and calls New York home, while Bob, who's 30, resides in London. Two interesting people from two amazing cities!"
            For norman text like "Hello" reply with hi i am sonatabot how can i help you or in conversation style reply to that like you are talking
        Edge Cases:
            If the data is empty (e.g., {} or an empty DataFrame), respond with:
            "It seems like there's no data to share yet. Could you provide some details for me to work with?"
            If the input contains complex nested structures, summarize where appropriate and offer to dive deeper if the user asks.
            User Interaction:
            If the user asks for a specific part of the data (e.g., "Tell me about the ages"), focus on that aspect while still keeping the response natural and flowing.
            If the user requests a different format (e.g., a table or list), adapt the output accordingly while maintaining clarity.
            Your goal is to make the data feel approachable and interesting, as if you're telling a story about it. Let's bring the numbers and facts to life!
        """

        # Dynamic prompt from database based on prompt_name
        prompt_3 = self.get_prompt_from_database(self.prompt_name)
        
        # Initialize models
        self.interpreter_model = AIModel("gemini-2.0-flash-001", system_instruction=prompt_1)
        self.query_model = AIModel("gemini-2.0-flash-001", system_instruction=prompt_3)
        self.chat1 = self.interpreter_model.start_chat()
        self.chat2 = self.query_model.start_chat()
        
        logger.info(f"Hierarchical search WebSocket connection established for prompt: {self.prompt_name}")

    def get_prompt_from_database(self, prompt_name=None):
        """Fetch prompt from database - now dynamic based on prompt_name"""
        if prompt_name is None:
            prompt_name = self.prompt_name
            
        if prompt_name in HierarchicalSearchConsumer._main_prompts_cache:
            return HierarchicalSearchConsumer._main_prompts_cache[prompt_name]
            
        try:
            with self.engine.begin() as connection:
                query = text("""
                    SELECT PromptContent 
                    FROM Marklytix_ChatbotHierarchyPrompts 
                    WHERE (PromptName = :prompt_name OR PromptName = 'MarklytixChat' OR PromptName = 'HierarchicalSearch')
                      AND IsActive = 1
                    ORDER BY CASE WHEN PromptName = :prompt_name THEN 1 WHEN PromptName = 'MarklytixChat' THEN 2 ELSE 3 END
                """)
                result = connection.execute(query, {"prompt_name": prompt_name})
                row = result.fetchone()
                print(f"Database row for prompt '{prompt_name}':", row)

                if row:
                    prompt_val = row[0]
                    HierarchicalSearchConsumer._main_prompts_cache[prompt_name] = prompt_val
                    return prompt_val
                else:
                    logger.warning(f"Prompt '{prompt_name}' not found in database or not active")
                    return self.get_default_prompt()
        except Exception as e:
            logger.error(f"Error fetching prompt from database: {e}")
            return self.get_default_prompt()

    def get_default_prompt(self):
        """Return a default prompt if the specific one is not found"""
        return """
        You are a helpful SQL query generator. Your task is to analyze the user's question and generate appropriate SQL queries.
        
        Guidelines:
        - Understand the user's intent and translate it into SQL queries
        - Use proper SQL syntax for SQL Server
        - Consider the database schema and available tables
        - If the question is not clear, ask for clarification
        - Always wrap your SQL queries in ```sql``` code blocks
        """

    def build_database_tree_with_prompts(self):
        """
        Build the complete database tree structure with all categories, subcategories, and tables
        This will be called once during initialization
        """
        tree = DatabaseSearchTree()
        
        # Load tree structure from database
        try:
            with self.engine.begin() as connection:
                # Get all active subcategory prompts to build the tree
                query = text("""
                    SELECT  Category, Subcategory, Table_List
                    FROM Marklytix_SubcategoryPrompts 
                    WHERE IsActive = 1
                    ORDER BY Category, Subcategory
                """)
                result = connection.execute(query)
                rows = result.fetchall()
                
                for row in rows:
                    category = row[0].strip().lower() if row[0] else ""
                    subcategory = row[1].strip().lower() if row[1] else "" 
                    table_list = row[2] or ""
                    
                    # Parse table list (assuming comma-separated)
                    tables = [t.strip() for t in table_list.split(',') if t.strip()]
                    
                    # Add category if not exists
                    if category not in tree.categories:
                        tree.add_category(
                            name=category,
                            keywords=self.get_category_keywords(category),
                            tables=[]
                        )
                    
                    # Add subcategory
                    tree.add_subcategory(
                        parent_name=category,
                        name=subcategory,
                        keywords=self.get_subcategory_keywords(category, subcategory),
                        tables=tables
                    )
                    
                    print(f"Added {category} -> {subcategory} with {len(tables)} tables")
                
                print(f"Database tree built with {len(tree.categories)} categories and {tree.total_tables} total tables")
                return tree
                
        except Exception as e:
            print(f"Error building database tree: {e}")
            # Return empty tree as fallback
            return DatabaseSearchTree()

    def load_keywords_from_database(self):
        """Load category and subcategory keywords from the database"""
        self.category_keywords_db = {}
        self.subcategory_keywords_db = {}
        
        try:
            with self.engine.begin() as connection:
                # 1. Load Category Keywords
                category_query = text("""
                    SELECT CategoryName, Keywords 
                    FROM dbo.Marklytix_Categories
                    WHERE IsActive = 1
                """)
                cat_result = connection.execute(category_query)
                for row in cat_result.fetchall():
                    category = row[0].strip().lower() if row[0] else ""
                    keywords_str = row[1] or ""
                    keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]
                    if category:
                        self.category_keywords_db[category] = keywords
                
                # 2. Load Subcategory Keywords
                subcategory_query = text("""
                    SELECT CategoryName, SubcategoryName, Keywords 
                    FROM dbo.Marklytix_Subcategories
                    WHERE IsActive = 1
                """)
                sub_result = connection.execute(subcategory_query)
                for row in sub_result.fetchall():
                    category = row[0].strip().lower() if row[0] else ""
                    subcategory = row[1].strip().lower() if row[1] else ""
                    keywords_str = row[2] or ""
                    keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]
                    
                    if category and subcategory:
                        if category not in self.subcategory_keywords_db:
                            self.subcategory_keywords_db[category] = {}
                        self.subcategory_keywords_db[category][subcategory] = keywords
                        
            print(f"Loaded {len(self.category_keywords_db)} categories and {sum(len(sub) for sub in self.subcategory_keywords_db.values())} subcategory keyword lists from split DB tables.")
        except Exception as e:
            print(f"Error loading keywords from split database tables: {e}")
            # Fallback to defaults
            self.category_keywords_db = {
                'sonata premier league': ['batting', 'bowling', 'top scorer', 'disbursement', 'collection', 'rankings', 'branch', 
                            'BRO', 'SPL', 'penelty', 'bonus', 'lowest performers', 'customer', 'mobile number',
                            'overdue_amount'],
                'hierarchy': ['branch', 'hub', 'region', 'division','zone', 'bro', 'branch manager', 'hub head', 'region head', 'division head', 'zonal head', 'hierarchy head', 'hierarchy', 'HO'],
                'user/staff details': ['userid', 'username', 'role', 'role_name', 'buid', 'active', 'mobile number', 'email', 'branch','hub', 'region','division','dropout', 'first_name', 'last_name', 'designation']
            }
            self.subcategory_keywords_db = {
                'sonata premier league': {
                    'daily scores': ['batting', 'bowling', 'bro', 'branch', 'total score', 'top 5']
                },
                'hierarchy': {
                    'geo-hierarchy' : ['branch', 'hub', 'region', 'division','zone', 'hierarchy', 'give me all the branches under patna'],
                    'geo-hierarchy-head': ['branch manager', 'hub head', 'region head', 'division head', 'zonal head', 'hierarchy head', 'hierarchy', 'HO'],
                },
                'user/staff details': {
                    'mst_usertbl': ['userid', 'username', 'role', 'role_name', 'buid', 'active', 'mobile number', 'email', 'branch','hub', 'region','division','dropout', 'first_name', 'last_name', 'designation']
                }
            }

    def get_category_keywords(self, category):
        """Get keywords for a category"""
        cat_lower = category.lower().strip()
        return self.category_keywords_db.get(cat_lower, [])

    def get_subcategory_keywords(self, category, subcategory):
        """Get keywords for a subcategory"""
        cat_lower = category.lower().strip()
        sub_lower = subcategory.lower().strip()
        return self.subcategory_keywords_db.get(cat_lower, {}).get(sub_lower, [])

    def sync_chroma_db_from_database(self):
        """Auto-Syncer: Query SQL Server database directly to keep Chroma DB in sync on WebSocket connection"""

        if not HAS_CHROMADB:
            return

        try:
            print("[ChromaDB Auto-Syncer] Starting automatic sync between SQL Server & Chroma DB...")
            storage_dir = os.path.join(os.path.dirname(__file__), "scratch", "chroma_db_storage")
            os.makedirs(storage_dir, exist_ok=True)

            if HierarchicalSearchConsumer._chroma_ef is None:
                # HierarchicalSearchConsumer._chroma_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                #     model_name="all-MiniLM-L6-v2"
                # )
                # Using Chroma's default embedding function to avoid sentence-transformers dependency
                HierarchicalSearchConsumer._chroma_ef = None
            if HierarchicalSearchConsumer._chroma_client is None:
                HierarchicalSearchConsumer._chroma_client = chromadb.PersistentClient(path=storage_dir)

            def get_or_create_clean_collection(name):
                try:
                    coll = HierarchicalSearchConsumer._chroma_client.get_or_create_collection(
                        name=name,
                        embedding_function=HierarchicalSearchConsumer._chroma_ef,
                        metadata={"hnsw:space": "cosine"}
                    )
                    # Force ChromaDB to load and validate the embedding function config by running a query
                    coll.query(query_texts=["test"], n_results=1)
                    print(f"💡 [ChromaDB Auto-Syncer] Collection '{name}' loaded/verified successfully.")
                    return coll
                except Exception as ex:
                    print(f"⚠️ [ChromaDB Auto-Syncer] Recreating collection '{name}' due to model mismatch or config error: {ex}")
                    try:
                        HierarchicalSearchConsumer._chroma_client.delete_collection(name=name)
                        print(f"🗑️ [ChromaDB Auto-Syncer] Deleted stale collection '{name}' from disk.")
                    except Exception as e_del:
                        print(f"⚠️ [ChromaDB Auto-Syncer] Error deleting collection '{name}': {e_del}")
                    
                    new_coll = HierarchicalSearchConsumer._chroma_client.get_or_create_collection(
                        name=name,
                        embedding_function=HierarchicalSearchConsumer._chroma_ef,
                        metadata={"hnsw:space": "cosine"}
                    )
                    print(f"✅ [ChromaDB Auto-Syncer] Recreated collection '{name}' successfully with default embedding function!")
                    return new_coll

            cat_coll = get_or_create_clean_collection("marklytix_categories")
            subcat_coll = get_or_create_clean_collection("marklytix_subcategories")
            schema_coll = get_or_create_clean_collection("marklytix_table_schemas")

            # 1. Fetch Table Schemas & extract column maps per Category and Subcategory
            table_schemas_map = {}
            category_columns_map = {}
            subcategory_columns_map = {}

            try:
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT Category, Subcategory, Table_List, PromptContent 
                        FROM dbo.Marklytix_SubcategoryPrompts 
                        WHERE IsActive = 1
                    """)
                    for row in cursor.fetchall():
                        category = row[0].strip().lower() if row[0] else ""
                        subcategory = row[1].strip().lower() if row[1] else ""
                        table_list_raw = row[2] or ""
                        prompt_content = row[3] or ""

                        tables = [t.strip() for t in table_list_raw.split(',') if t.strip()]
                        for t_name in tables:
                            if t_name not in table_schemas_map:
                                table_schemas_map[t_name] = {
                                    "category": category,
                                    "subcategory": subcategory,
                                    "prompt_snippets": [prompt_content[:300]]
                                }
                            else:
                                table_schemas_map[t_name]["prompt_snippets"].append(prompt_content[:300])

                    t_ids, t_docs, t_metas = [], [], []
                    for t_name, info in table_schemas_map.items():
                        cols = []
                        cursor.execute("""
                            SELECT COLUMN_NAME, DATA_TYPE 
                            FROM INFORMATION_SCHEMA.COLUMNS 
                            WHERE TABLE_NAME = %s
                            ORDER BY ORDINAL_POSITION
                        """, [t_name])
                        for c_row in cursor.fetchall():
                            c_name = c_row[0]
                            c_type = c_row[1]
                            cols.append(f"{c_name} ({c_type})")

                            cat = info["category"]
                            sub = info["subcategory"]

                            if cat:
                                if cat not in category_columns_map:
                                    category_columns_map[cat] = set()
                                category_columns_map[cat].add(c_name)
                            if sub:
                                if sub not in subcategory_columns_map:
                                    subcategory_columns_map[sub] = set()
                                subcategory_columns_map[sub].add(c_name)

                        cols_str = ", ".join(cols) if cols else "Columns derived from specialized subcategory prompt"
                        snippet = " | ".join(info["prompt_snippets"])[:250]

                        t_ids.append(f"tbl_{t_name.replace(' ', '_').lower()}")
                        t_docs.append(f"Table Name: {t_name}\nCategory: {info['category']} | Subcategory: {info['subcategory']}\nColumns: {cols_str}\nPrompt Schema Context: {snippet}")
                        t_metas.append({"table_name": t_name, "category": info["category"], "subcategory": info["subcategory"]})

                    if t_ids:
                        schema_coll.upsert(ids=t_ids, documents=t_docs, metadatas=t_metas)
                        HierarchicalSearchConsumer._schema_collection = schema_coll
                        print(f"🎉 [ChromaDB Auto-Syncer] Synced {len(t_ids)} dynamic table schemas from SQL Server database!")
            except Exception as e_sql:
                print(f"⚠️ [ChromaDB Auto-Syncer SQL Error]: {e_sql}")


            # 2. Sync ENRICHED Categories from Marklytix_Categories + Table Columns
            cat_db = getattr(self, 'category_keywords_db', getattr(HierarchicalSearchConsumer, '_category_keywords_db', {}))
            cat_ids, cat_docs, cat_metas = [], [], []
            for cat, keywords in cat_db.items():
                cat_lower = cat.lower().strip()
                kw_text = " ".join(keywords) if isinstance(keywords, list) else str(keywords)
                cols_set = category_columns_map.get(cat_lower, set())
                cols_str = f". Relevant Table Columns: {', '.join(sorted(cols_set))}" if cols_set else ""

                cat_ids.append(f"cat_{cat_lower.replace(' ', '_')}")
                cat_docs.append(f"{cat}: {cat} {kw_text} {cols_str}")
                cat_metas.append({"category": cat, "code": cat.upper()})
            if cat_ids:
                try:
                    existing_cat_ids = cat_coll.get()['ids']
                    stale_cat_ids = [cid for cid in existing_cat_ids if cid not in cat_ids]
                    if stale_cat_ids:
                        cat_coll.delete(ids=stale_cat_ids)
                except Exception:
                    pass
                cat_coll.upsert(ids=cat_ids, documents=cat_docs, metadatas=cat_metas)
            else:
                try:
                    existing_cat_ids = cat_coll.get()['ids']
                    if existing_cat_ids:
                        cat_coll.delete(ids=existing_cat_ids)
                except Exception:
                    pass
            HierarchicalSearchConsumer._cat_collection = cat_coll

            # 3. Sync ENRICHED Subcategories from Marklytix_Subcategories + Table Columns
            subcat_db = getattr(self, 'subcategory_keywords_db', getattr(HierarchicalSearchConsumer, '_subcategory_keywords_db', {}))
            sub_ids, sub_docs, sub_metas = [], [], []
            idx = 0
            for parent_cat, sub_dict in subcat_db.items():
                if isinstance(sub_dict, dict):
                    for subcat, keywords in sub_dict.items():
                        subcat_lower = subcat.lower().strip()
                        kw_text = " ".join(keywords) if isinstance(keywords, list) else str(keywords)
                        cols_set = subcategory_columns_map.get(subcat_lower, set())
                        cols_str = f". Relevant Table Columns: {', '.join(sorted(cols_set))}" if cols_set else ""

                        idx += 1
                        sub_ids.append(f"sub_{idx}")
                        sub_docs.append(f"{subcat}: {subcat} {kw_text} {cols_str}")
                        sub_metas.append({"parent_category": parent_cat, "subcategory": subcat})
            if sub_ids:
                try:
                    existing_sub_ids = subcat_coll.get()['ids']
                    stale_sub_ids = [sid for sid in existing_sub_ids if sid not in sub_ids]
                    if stale_sub_ids:
                        subcat_coll.delete(ids=stale_sub_ids)
                except Exception:
                    pass
                subcat_coll.upsert(ids=sub_ids, documents=sub_docs, metadatas=sub_metas)
            else:
                try:
                    existing_sub_ids = subcat_coll.get()['ids']
                    if existing_sub_ids:
                        subcat_coll.delete(ids=existing_sub_ids)
                except Exception:
                    pass
            HierarchicalSearchConsumer._subcat_collection = subcat_coll

            HierarchicalSearchConsumer._chroma_initialized = True
            print("✅ [ChromaDB Auto-Syncer] WebSocket connection auto-sync completed successfully with ENRICHED Column Schemas!")



        except Exception as e:
            print(f"⚠️ [ChromaDB Auto-Syncer Error]: {e}")

    def _init_chroma_vector_store(self):
        """Initialize local persistent Chroma DB vector collections directly from database keywords"""
        self.sync_chroma_db_from_database()

    _schema_collection = None

    def _init_chroma_schema_store(self):
        """Initialize local persistent Chroma DB schema store"""
        if HierarchicalSearchConsumer._schema_collection is not None:
            return
        self.sync_chroma_db_from_database()




    def retrieve_top_k_schemas_chroma(self, query, k=2):
        """Retrieve top K relevant table schemas for dynamic RAG prompt injection from disk storage"""
        if not HAS_CHROMADB:
            return ""

        try:
            storage_dir = os.path.join(os.path.dirname(__file__), "scratch", "chroma_db_storage")
            client = chromadb.PersistentClient(path=storage_dir)
            # ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
            # schema_coll = client.get_collection(name="marklytix_table_schemas", embedding_function=ef)
            # Using Chroma's default embedding function to avoid sentence-transformers dependency
            schema_coll = client.get_collection(name="marklytix_table_schemas")

            results = schema_coll.query(
                query_texts=[query],
                n_results=k
            )
            schemas = []
            if results and results.get('documents') and results['documents'][0]:
                for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
                    schemas.append(f"--- Table Schema: {meta['table_name']} ---\n{doc}")
            return "\n\n".join(schemas)
        except Exception as e:
            print(f"[ChromaDB RAG] Error retrieving schemas for query: {e}")
            return ""



    def classify_category_chroma(self, message):
        """Vector-based category classification using Chroma DB cosine similarity"""
        if not getattr(HierarchicalSearchConsumer, '_chroma_initialized', False) or HierarchicalSearchConsumer._cat_collection is None:
            return {
                'category': 'general',
                'confidence': 0.0,
                'reasoning': 'ChromaDB vector store not initialized'
            }

        try:
            results = HierarchicalSearchConsumer._cat_collection.query(
                query_texts=[message],
                n_results=1
            )
            if results and results.get('documents') and results['documents'][0]:
                top_doc = results['documents'][0][0]
                top_meta = results['metadatas'][0][0]
                top_id = results['ids'][0][0] if 'ids' in results and results['ids'] else "N/A"
                dist = results['distances'][0][0]
                similarity = round(max(0.0, 1.0 - (dist * 0.70)), 4)
                matched_category = top_meta.get('category', 'general')

                return {
                    'category': matched_category,
                    'confidence': similarity,
                    'method': 'vector_chroma',
                    'matched_doc': top_doc,
                    'matched_meta': top_meta,
                    'matched_id': top_id,
                    'reasoning': f"Vector match '{matched_category}' with similarity {similarity:.2f} (distance: {dist:.3f})"
                }
        except Exception as e:
            print(f"[ChromaDB] Category vector classification error: {e}")

        return {
            'category': 'general',
            'confidence': 0.1,
            'reasoning': 'Vector query failed'
        }

    def classify_subcategory_chroma(self, message, category):
        """Vector-based subcategory classification using Chroma DB cosine similarity"""
        if not getattr(HierarchicalSearchConsumer, '_chroma_initialized', False) or HierarchicalSearchConsumer._subcat_collection is None:
            return {
                'subcategory': 'general',
                'confidence': 0.0,
                'method': 'vector_chroma',
                'reasoning': 'ChromaDB vector store not initialized'
            }

        try:
            results = HierarchicalSearchConsumer._subcat_collection.query(
                query_texts=[message],
                n_results=1,
                where={"parent_category": category.strip().lower()}
            )
            if results and results.get('documents') and results['documents'][0]:
                top_doc = results['documents'][0][0]
                top_meta = results['metadatas'][0][0]
                top_id = results['ids'][0][0] if 'ids' in results and results['ids'] else "N/A"
                dist = results['distances'][0][0]
                similarity = round(max(0.0, 1.0 - (dist * 0.70)), 4)
                matched_subcat = top_meta.get('subcategory', 'general')

                return {
                    'subcategory': matched_subcat,
                    'confidence': similarity,
                    'method': 'vector_chroma',
                    'matched_doc': top_doc,
                    'matched_meta': top_meta,
                    'matched_id': top_id,
                    'reasoning': f"Vector subcategory match '{matched_subcat}' (similarity: {similarity:.2f})"
                }
        except Exception as e:
            print(f"[ChromaDB] Subcategory vector search error: {e}")



        return {
            'subcategory': 'general',
            'confidence': 0.1,
            'method': 'vector_chroma',
            'reasoning': 'Subcategory vector search fallback'
        }


    def classify_category_hybrid(self, message, search_tree):
        """
        Hybrid Level 1 Agent: Uses Keyword + Chroma DB Vector Search + LLM Fallback
        """
        print("🔍 Starting hybrid category classification...")

        if not self.category_keywords_db:
            print("⚠️ No categories configured in database, defaulting to general (confidence: 0.0)")
            return {
                'method': 'no_categories',
                'category': 'general',
                'confidence': 0.0,
                'reasoning': 'No categories configured in database'
            }

        # Step 1: Quick keyword-based classification
        print("⚡ Step 1: Keyword-based classification...")
        keyword_result = self.classify_category_keywords(message)
        print(f"📊 Keyword result: {keyword_result['category']} (confidence: {keyword_result['confidence']:.2f})")
        
        if keyword_result['confidence'] >= 0.7:
            print("✅ High confidence keyword match, using keyword result")
            return {
                'method': 'keyword',
                'category': keyword_result['category'],
                'confidence': keyword_result['confidence'],
                'reasoning': keyword_result['reasoning']
            }
        
        # Step 2: Vector Embedding Classification (Chroma DB)
        if getattr(HierarchicalSearchConsumer, '_chroma_initialized', False):
            print("🧠 Step 2: Chroma DB Vector Embedding Classification...")
            vector_result = self.classify_category_chroma(message)
            print(f"📊 Vector result: {vector_result['category']} (confidence: {vector_result['confidence']:.2f})")
            
            if vector_result['confidence'] >= 0.45:
                print("✅ High confidence vector match, using Chroma DB result")
                print("==========================================================")
                print("🎯 [CHROMADB LEVEL 1 CATEGORY MATCH DETAILS] 🎯")
                print(f"   ID: {vector_result.get('matched_id', 'N/A')}")
                print(f"   Category: {vector_result['category']}")
                print(f"   Similarity Score: {vector_result['confidence']:.4f}")
                print(f"   Metadata: {json.dumps(vector_result.get('matched_meta', {}))}")
                print(f"   Document Text:\n   {vector_result.get('matched_doc', '')}")
                print("==========================================================")
                return vector_result

        # Step 3: LLM Fallback for complex/ambiguous queries
        print("🤖 Step 3: AI LLM Fallback classification...")
        ai_result = self.classify_category_with_ai(message)
        print(f"📊 AI result: {ai_result['category']} (confidence: {ai_result['confidence']:.2f})")
        
        if (keyword_result['category'] == ai_result['category'] and 
            keyword_result['confidence'] >= 0.4):
            print("🤝 Both methods agree, using hybrid agreement")
            return {
                'method': 'hybrid_agreement',
                'category': keyword_result['category'],
                'confidence': (keyword_result['confidence'] + ai_result['confidence']) / 2,
                'reasoning': f"Both methods agree: {keyword_result['reasoning']}"
            }
        
        if ai_result['confidence'] > keyword_result['confidence']:
            print("🤖 AI has higher confidence, using AI result")
            return {
                'method': 'ai_preferred',
                'category': ai_result['category'],
                'confidence': ai_result['confidence'],
                'reasoning': ai_result['reasoning'],
                'keyword_suggestion': keyword_result['category']
            }
        
        print("⚡ Using keyword result as fallback")
        return {
            'method': 'keyword_fallback',
            'category': keyword_result['category'],
            'confidence': keyword_result['confidence'],
            'reasoning': keyword_result['reasoning'],
            'ai_suggestion': ai_result['category']
        }

    
    def classify_category_keywords(self, message):
        """
        Fast keyword-based category classification
        """
        message_lower = message.lower()
        words = message_lower.split()
        
        category_scores = {}
        
        for category, keywords in self.category_keywords_db.items():
            score = 0
            matches = []
            
            for keyword in keywords:
                if keyword in message_lower:
                    score += 1
                    matches.append(keyword)
            
            confidence = score / max(len(words), 1)
            category_scores[category] = {
                'score': score,
                'confidence': min(confidence, 1.0),
                'matches': matches
            }
        
        sorted_categories = sorted(
            category_scores.items(),
            key=lambda x: x[1]['confidence'],
            reverse=True
        )
        
        if not sorted_categories:
            return {
                'category': 'general',
                'confidence': 0.0,
                'matches': [],
                'reasoning': "No categories available"
            }

        top_category, top_data = sorted_categories[0]
        
        if top_data['confidence'] > 0:
            return {
                'category': top_category,
                'confidence': top_data['confidence'],
                'matches': top_data['matches'],
                'reasoning': f"Matched keywords: {', '.join(top_data['matches'])}"
            }
        else:
            return {
                'category': 'general',
                'confidence': 0.0,
                'matches': [],
                'reasoning': "No keywords matched"
            }
    
    def classify_category_with_ai(self, message):
        """
        AI-based category classification using your existing chat model
        """
        if not self.category_keywords_db:
            return {
                'category': 'general',
                'confidence': 0.0,
                'reasoning': 'No categories configured in database'
            }

        try:
            # Dynamically list categories and their keywords for the prompt
            categories_details = []
            for cat, kws in self.category_keywords_db.items():
                kws_str = ", ".join([f"'{k}'" for k in kws[:15]]) # Limit to first 15 keywords to keep prompt clean
                categories_details.append(f"- {cat}: {kws_str}")
            
            categories_prompt_str = "\n".join(categories_details)
            valid_categories = list(self.category_keywords_db.keys())
            
            prompt = f"""
            You are a database query classifier. Analyze this user query and classify it into ONE of these categories:
            categories are only within the below list:(eg - category_name: 'keyword1', 'keyword2', 'keyword3'):

            {categories_prompt_str}
            
            User Query: "{message}"
            
            Respond with ONLY the category name and confidence score (0.0 to 1.0).
            Format: category_name|confidence_score
            
            Example: sonata premier league|0.85
            """
            
            response = self.query_model.generate_content([prompt])
            response_text = response.text.strip()
            
            # Parse the response
            if '|' in response_text:
                category, confidence_str = response_text.split('|', 1)
                category = category.strip().lower()
                confidence = float(confidence_str.strip())
                
                # Validate category
                if category not in valid_categories:
                    category = 'general'
                    confidence = 0.3
                    
                return {
                    'category': category,
                    'confidence': confidence,
                    'reasoning': f'AI classified as {category} with {confidence:.2f} confidence'
                }
            else:
                # Fallback parsing
                response_lower = response_text.lower()
                for cat in valid_categories:
                    if cat in response_lower:
                        return {
                            'category': cat,
                            'confidence': 0.6,
                            'reasoning': f'AI mentioned {cat} in response'
                        }
                
                return {
                    'category': 'general',
                    'confidence': 0.3,
                    'reasoning': 'AI response could not be parsed'
                }
                
        except Exception as e:
            print(f"Error in AI classification: {e}")
            return {
                'category': 'general',
                'confidence': 0.2,
                'reasoning': f'AI classification failed: {str(e)}'
            }        
    
    def classify_subcategory_hybrid(self, message, category, search_tree):
        """
        Hybrid Level 2 Agent: Classifies subcategory within a given category
        Uses AI + keyword matching for subcategory selection
        """
        print(f"🔍 Starting hybrid subcategory classification for category: {category}")
        # Get available subcategories for the category
        available_subcategories = search_tree.get_subcategories_for_category(category)
        print(f"📋 Available subcategories: {available_subcategories}")
        
        if not available_subcategories:
            print("⚠️  No subcategories found, returning general")
            return {
                'method': 'no_subcategories',
                'subcategory': 'general',
                'confidence': 0.5,
                'reasoning': f'No subcategories defined for {category}'
            }
        
        # Step 1: Quick keyword-based subcategory classification
        print("⚡ Step 1: Keyword-based subcategory classification...")
        keyword_result = self.classify_subcategory_keywords(message, category, available_subcategories)
        print(f"📊 Keyword result: {keyword_result['subcategory']} (confidence: {keyword_result['confidence']:.2f})")
        
        # If confidence is high enough, return keyword result
        if keyword_result['confidence'] >= 0.7:
            print("✅ High confidence keyword match, using keyword result")
            return {
                'method': 'keyword',
                'subcategory': keyword_result['subcategory'],
                'confidence': keyword_result['confidence'],
                'reasoning': keyword_result['reasoning']
            }
        
        # Step 2: Vector Embedding Subcategory Search (Chroma DB)
        if getattr(HierarchicalSearchConsumer, '_chroma_initialized', False):
            print("🧠 Step 2: Chroma DB Vector Subcategory Classification...")
            vector_sub_result = self.classify_subcategory_chroma(message, category)
            print(f"📊 Vector subcategory result: {vector_sub_result['subcategory']} (confidence: {vector_sub_result['confidence']:.2f})")
            
            if vector_sub_result['confidence'] >= 0.45:
                print("✅ High confidence vector match, using Chroma DB subcategory result")
                print("==========================================================")
                print("🎯 [CHROMADB LEVEL 2 SUBCATEGORY MATCH DETAILS] 🎯")
                print(f"   ID: {vector_sub_result.get('matched_id', 'N/A')}")
                print(f"   Subcategory: {vector_sub_result['subcategory']} (Parent Category: {category})")
                print(f"   Similarity Score: {vector_sub_result['confidence']:.4f}")
                print(f"   Metadata: {json.dumps(vector_sub_result.get('matched_meta', {}))}")
                print(f"   Document Text:\n   {vector_sub_result.get('matched_doc', '')}")
                print("==========================================================")
                return vector_sub_result


        # Step 3: Use AI for complex/ambiguous queries
        print("🤖 Step 3: AI-based subcategory classification...")
        ai_result = self.classify_subcategory_with_ai(message, category, available_subcategories)
        print(f"📊 AI result: {ai_result['subcategory']} (confidence: {ai_result['confidence']:.2f})")

        
        # Step 3: Combine results if both methods agree
        if (keyword_result['subcategory'] == ai_result['subcategory'] and 
            keyword_result['confidence'] >= 0.4):
            print("🤝 Both methods agree, using hybrid agreement")
            return {
                'method': 'hybrid_agreement',
                'subcategory': keyword_result['subcategory'],
                'confidence': (keyword_result['confidence'] + ai_result['confidence']) / 2,
                'reasoning': f"Both methods agree: {keyword_result['reasoning']}"
            }
        
        # Step 4: Use AI result if it has higher confidence
        if ai_result['confidence'] >= keyword_result['confidence']:
            print("🤖 AI has higher confidence, using AI result")
            return {
                'method': 'ai_preferred',
                'subcategory': ai_result['subcategory'],
                'confidence': ai_result['confidence'],
                'reasoning': ai_result['reasoning'],
                'keyword_suggestion': keyword_result['subcategory']
            }
        
        # Step 5: Fallback to keyword result
        print("⚡ Using keyword result as fallback")
        return {
            'method': 'keyword_fallback',
            'subcategory': keyword_result['subcategory'],
            'confidence': keyword_result['confidence'],
            'reasoning': keyword_result['reasoning'],
            'ai_suggestion': ai_result['subcategory']
        }
    
    def classify_subcategory_keywords(self, message, category, available_subcategories):
        """
        Fast keyword-based subcategory classification
        """
        message_lower = message.lower()
        words = message_lower.split()
        
        # Get keywords for the category from self.subcategory_keywords_db
        category_keywords = self.subcategory_keywords_db.get(category.lower().strip(), {})
        
        subcategory_scores = {}
        
        for subcategory in available_subcategories:
            sub_key = subcategory.lower().strip()
            keywords = category_keywords.get(sub_key, [])
            score = 0
            matches = []
            
            for keyword in keywords:
                if keyword in message_lower:
                    score += 1
                    matches.append(keyword)
            
            confidence = score / max(len(words), 1)
            subcategory_scores[subcategory] = {
                'score': score,
                'confidence': min(confidence, 1.0),
                'matches': matches
            }
        
        if not subcategory_scores or max(cs['score'] for cs in subcategory_scores.values()) == 0:
            return {
                'subcategory': 'general',
                'confidence': 0.3,
                'reasoning': f'No subcategory keywords found for {category}'
            }
        
        best = max(subcategory_scores.items(), key=lambda x: x[1]['score'])
        
        return {
            'subcategory': best[0],
            'confidence': best[1]['confidence'],
            'reasoning': f"Matched {len(best[1]['matches'])} keywords: {', '.join(best[1]['matches'][:3])}"
        }
    
    def classify_subcategory_with_ai(self, message, category, available_subcategories):
        """
        AI-based subcategory classification within a specific category
        """
        try:
            subcategories_str = ', '.join(available_subcategories)
            
            prompt = f"""
            You are a database query classifier. The user query has been classified into the '{category}' category.
            Now classify it into ONE of these subcategories within {category}:
            
            Available subcategories: {subcategories_str}
            
            User Query: "{message}"
            
            Respond with ONLY the subcategory name and confidence score (0.0 to 1.0).
            Format: subcategory_name|confidence_score
            
            Example: budget|0.85
            """
            
            response = self.query_model.generate_content([prompt])
            response_text = response.text.strip()
            
            # Parse the response
            if '|' in response_text:
                subcategory, confidence_str = response_text.split('|', 1)
                subcategory = subcategory.strip().lower()
                confidence = float(confidence_str.strip())
                
                # Validate subcategory
                if subcategory not in available_subcategories:
                    subcategory = 'general'
                    confidence = 0.3
                    
                return {
                    'subcategory': subcategory,
                    'confidence': confidence,
                    'reasoning': f'AI classified as {subcategory} with {confidence:.2f} confidence'
                }
            else:
                # Fallback parsing
                response_lower = response_text.lower()
                for subcat in available_subcategories:
                    if subcat in response_lower:
                        return {
                            'subcategory': subcat,
                            'confidence': 0.6,
                            'reasoning': f'AI mentioned {subcat} in response'
                        }
                
                return {
                    'subcategory': 'general',
                    'confidence': 0.3,
                    'reasoning': 'AI response could not be parsed'
                }
                
        except Exception as e:
            print(f"Error in AI subcategory classification: {e}")
            return {
                'subcategory': 'general',
                'confidence': 0.2,
                'reasoning': f'AI subcategory classification failed: {str(e)}'
            }
    
    def select_tables_hybrid(self, message, category, subcategory, search_tree):
        """
        Hybrid Level 3 Agent: Selects specific tables and generates SQL query
        Uses AI + keyword matching for table selection and query generation
        """
        # Get available tables for the category-subcategory path
        path = f"{category}_{subcategory}"
        available_tables = search_tree.get_tables_for_path(path)
        
        if not available_tables:
            return {
                'method': 'no_tables',
                'tables': [],
                'query': 'No tables available for this category-subcategory combination',
                'confidence': 0.1,
                'reasoning': f'No tables found for {path}'
            }
        
        # Step 1: Quick keyword-based table selection
        keyword_result = self.select_tables_keywords(message, available_tables, category, subcategory)
        
        # If confidence is high enough, return keyword result
        if keyword_result['confidence'] >= 0.7:
            return {
                'method': 'keyword',
                'tables': keyword_result['tables'],
                'query': keyword_result['query'],
                'confidence': keyword_result['confidence'],
                'reasoning': keyword_result['reasoning']
            }
        
        # Step 2: Use AI for complex/ambiguous queries
        ai_result = self.select_tables_with_ai(message, available_tables, category, subcategory)
        
        # Step 3: Combine results if both methods agree
        if (set(keyword_result['tables']) == set(ai_result['tables']) and 
            keyword_result['confidence'] >= 0.4):
            return {
                'method': 'hybrid_agreement',
                'tables': keyword_result['tables'],
                'query': keyword_result['query'],
                'confidence': (keyword_result['confidence'] + ai_result['confidence']) / 2,
                'reasoning': f"Both methods agree: {keyword_result['reasoning']}"
            }
        
        # Step 4: Use AI result if it has higher confidence
        if ai_result['confidence'] > keyword_result['confidence']:
            return {
                'method': 'ai_preferred',
                'tables': ai_result['tables'],
                'query': ai_result['query'],
                'confidence': ai_result['confidence'],
                'reasoning': ai_result['reasoning'],
                'keyword_suggestion': keyword_result['tables']
            }
        
        # Step 5: Fallback to keyword result
        return {
            'method': 'keyword_fallback',
            'tables': keyword_result['tables'],
            'query': keyword_result['query'],
            'confidence': keyword_result['confidence'],
            'reasoning': keyword_result['reasoning'],
            'ai_suggestion': ai_result['tables']
        }
    
    def select_tables_keywords(self, message, available_tables, category, subcategory):
        """
        Fast keyword-based table selection
        """
        message_lower = message.lower()
        words = message_lower.split()
        
        # Get keywords for the category/subcategory from self.subcategory_keywords_db
        category_keywords = self.subcategory_keywords_db.get(category.lower().strip(), {})
        
        table_scores = {}
        
        for table in available_tables:
            table_lower = table.lower()
            score = 0
            matches = []
            
            # Check table name against keywords of the subcategory
            keywords = category_keywords.get(subcategory.lower().strip(), [])
            for keyword in keywords:
                if keyword in table_lower or keyword in message_lower:
                    score += 1
                    matches.append(keyword)
            
            # Check for direct table name matches in message
            if any(word in table_lower for word in words):
                score += 2
                matches.append('direct_match')
            
            confidence = score / max(len(words), 1)
            table_scores[table] = {
                'score': score,
                'confidence': min(confidence, 1.0),
                'matches': matches
            }
        
        # Select top tables (limit to 3 for performance)
        sorted_tables = sorted(table_scores.items(), key=lambda x: x[1]['score'], reverse=True)
        selected_tables = [table for table, _ in sorted_tables[:3] if table_scores[table]['score'] > 0]
        
        if not selected_tables:
            selected_tables = available_tables[:2]  # Fallback to first 2 tables
        
        # Generate basic SQL query
        query = self.generate_basic_sql_query(message, selected_tables, category, subcategory)
        
        return {
            'tables': selected_tables,
            'query': query,
            'confidence': max([table_scores[table]['confidence'] for table in selected_tables], default=0.3),
            'reasoning': f"Selected {len(selected_tables)} tables based on keyword matching"
        }
    
    def select_tables_with_ai(self, message, available_tables, category, subcategory):
        """
        AI-based table selection and query generation
        """
        try:
            tables_str = ', '.join(available_tables)
            
            prompt = f"""
            You are a database query expert. The user query has been classified as:
            Category: {category}
            Subcategory: {subcategory}
            
            Available tables: {tables_str}
            
            User Query: "{message}"
            
            Select the most relevant tables (maximum 3) and generate a SQL query.
            
            Respond in this exact format:
            TABLES: table1, table2, table3
            QUERY: SELECT * FROM table1 WHERE condition
            CONFIDENCE: 0.85
            
            Example:
            TABLES: employee_master, payroll_data
            QUERY: SELECT e.name, p.salary FROM employee_master e JOIN payroll_data p ON e.id = p.employee_id WHERE p.salary > 50000
            CONFIDENCE: 0.90
            """
            
            response = self.chat2.send_message([prompt])
            response_text = response.text.strip()
            
            # Parse the response
            lines = response_text.split('\n')
            tables = []
            query = ""
            confidence = 0.5
            
            for line in lines:
                line = line.strip()
                if line.startswith('TABLES:'):
                    tables_str = line.replace('TABLES:', '').strip()
                    tables = [t.strip() for t in tables_str.split(',') if t.strip()]
                elif line.startswith('QUERY:'):
                    query = line.replace('QUERY:', '').strip()
                elif line.startswith('CONFIDENCE:'):
                    try:
                        confidence = float(line.replace('CONFIDENCE:', '').strip())
                    except:
                        confidence = 0.5
            
            # Validate tables
            valid_tables = [table for table in tables if table in available_tables]
            if not valid_tables:
                valid_tables = available_tables[:2]  # Fallback
            
            # If no query generated, create a basic one
            if not query:
                query = self.generate_basic_sql_query(message, valid_tables, category, subcategory)
            
            return {
                'tables': valid_tables,
                'query': query,
                'confidence': confidence,
                'reasoning': f'AI selected {len(valid_tables)} tables and generated query'
            }
            
        except Exception as e:
            print(f"Error in AI table selection: {e}")
            # Fallback to basic selection
            fallback_tables = available_tables[:2]
            fallback_query = self.generate_basic_sql_query(message, fallback_tables, category, subcategory)
            
            return {
                'tables': fallback_tables,
                'query': fallback_query,
                'confidence': 0.3,
                'reasoning': f'AI table selection failed, using fallback: {str(e)}'
            }
    
    def generate_basic_sql_query(self, message, tables, category, subcategory):
        """
        Generate a basic SQL query when AI fails or for simple cases
        """
        if not tables:
            return "SELECT * FROM information_schema.tables WHERE 1=0"
        
        # Simple query based on table count
        if len(tables) == 1:
            return f"SELECT TOP 100 * FROM {tables[0]}"
        else:
            # Multi-table query with basic join
            main_table = tables[0]
            other_tables = tables[1:]
            
            query = f"SELECT TOP 100 * FROM {main_table}"
            
            for table in other_tables:
                # Try to find common column for join (basic approach)
                query += f" LEFT JOIN {table} ON {main_table}.id = {table}.id"
            
            return query
    
    def select_tables_with_specialized_prompt(self, message, category, subcategory, search_tree):
        """
        Level 3 Agent: Uses specialized subcategory prompts to generate SQL directly
        This is the main function that will use your detailed prompts
        """
        print(f"🔍 Starting specialized prompt table selection for: {category} -> {subcategory}")
        try:
            # Get the specialized prompt for this subcategory
            print("📋 Fetching specialized prompt from database...")
            specialized_prompt = self.get_subcategory_prompt(category, subcategory)
            
            if not specialized_prompt:
                print("⚠️  No specialized prompt found, falling back to hybrid approach")
                # Fallback to hybrid approach if no specialized prompt
                return self.select_tables_hybrid(message, category, subcategory, search_tree)
            
            print("✅ Specialized prompt found, proceeding with prompt-based generation")
            
            # Get available tables for this subcategory
            path = f"{category}_{subcategory}"
            available_tables = search_tree.get_tables_for_path(path)
            print(f"📋 Available tables for {path}: {available_tables}")
            
            if not available_tables:
                print("⚠️  No tables found for this subcategory")
                return {
                    'method': 'no_tables',
                    'tables': [],
                    'query': 'No tables available for this subcategory',
                    'confidence': 0.1,
                    'reasoning': f'No tables found for {path}'
                }
            
            # Dynamic Chroma DB Schema RAG Retrieval
            print("🧠 [Chroma DB RAG] Fetching dynamic table schemas from Chroma vector store...")
            rag_schemas = self.retrieve_top_k_schemas_chroma(message, k=2)
            
            if rag_schemas:
                print("✅ Dynamic table schemas retrieved successfully from Chroma DB:")
                for line in rag_schemas.splitlines()[:4]:
                    print(f"   {line}")
                schema_section = f"\n[DYNAMICALLY RETRIEVED TABLE SCHEMAS FROM CHROMADB]\n{rag_schemas}\n"
            else:
                tables_str = ', '.join(available_tables)
                schema_section = f"\nAVAILABLE TABLES FOR THIS QUERY: {tables_str}\n"

            print("🔧 Creating complete prompt with user query and retrieved schemas...")
            complete_prompt = f"""
            {specialized_prompt}
            
            {schema_section}
            
            USER QUERY: "{message}"
            
            Generate a T-SQL query that:
            1. Uses only the available tables and columns in the schema listed above
            2. Follows the schema definitions and patterns provided
            3. Answers exactly what the user is asking for
            4. Uses proper T-SQL syntax for SQL Server
            
            Respond with ONLY the SQL query, no explanations.
            """

            
            # Use your existing chat2 model with the specialized prompt
            print("🤖 Sending prompt to AI model for SQL generation...")
            response = self.query_model.generate_content([complete_prompt])
            query = response.text.strip()
            print(f"✅ SQL query generated: {query[:100]}...")
            
            # Clean up the response (remove markdown if present)
            print("🧹 Cleaning up AI response (removing markdown if present)...")
            if '```sql' in query:
                query = query.split('```sql')[1].split('```')[0].strip()
                print("✅ Removed SQL markdown formatting")
            elif '```' in query:
                query = query.split('```')[1].strip()
                print("✅ Removed generic markdown formatting")
            
            # Validate the query
            print("🔍 Validating generated SQL query...")
            if not query or query.lower().startswith('select') == False:
                print("⚠️  Query validation failed, using fallback query")
                # Fallback to basic query
                query = self.generate_basic_sql_query(message, available_tables, category, subcategory)
                confidence = 0.4
                reasoning = 'Specialized prompt failed, using fallback query'
            else:
                print("✅ Query validation passed")
                confidence = 0.9
                reasoning = f'Generated query using specialized {subcategory} prompt'
            
            print(f"🎯 Final result: {confidence:.2f} confidence using {reasoning}")
            return {
                'method': 'specialized_prompt',
                'tables': available_tables,
                'query': query,
                'confidence': confidence,
                'reasoning': reasoning,
                'prompt_used': f"{category}_{subcategory}"
            }
            
        except Exception as e:
            print(f"💥 Error in specialized prompt table selection: {e}")
            print("🔄 Falling back to hybrid approach...")
            # Fallback to hybrid approach
            return self.select_tables_hybrid(message, category, subcategory, search_tree)
    
    def get_subcategory_prompt(self, category, subcategory):
        """
        Get specialized prompt from database for a specific subcategory
        """
        prompt_key = f"{category.lower().strip()}_{subcategory.lower().strip()}"
        if prompt_key in HierarchicalSearchConsumer._subcategory_prompts_cache:
            return HierarchicalSearchConsumer._subcategory_prompts_cache[prompt_key]
            
        try:
            if not getattr(self, 'engine', None):
                sql_user = os.environ.get('DATABASE_USER', '')
                sql_password = os.environ.get('DATABASE_PASSWORD', '')
                sql_server = os.environ.get('DATABASE_HOST', '')
                sql_db = os.environ.get('DATABASE_NAME', '')
                sql_driver = os.environ.get('DATABASE_DRIVER', 'ODBC Driver 17 for SQL Server')
                connection_url = (
                    f"mssql+pyodbc://{sql_user}:{quote_plus(sql_password)}@{sql_server}/{sql_db}"
                    f"?driver={sql_driver.replace(' ', '+')}"
                )
                self.engine = create_engine(connection_url, fast_executemany=True)

            with self.engine.begin() as connection:
                query = text("""
                    SELECT PromptContent, Table_List, Query_Patterns
                    FROM dbo.Marklytix_SubcategoryPrompts 
                    WHERE LOWER(Category) = LOWER(:category) 
                      AND LOWER(Subcategory) = LOWER(:subcategory) 
                      AND IsActive = 1
                """)
                result = connection.execute(query, {
                    "category": category, 
                    "subcategory": subcategory
                })
                row = result.fetchone()
                
                if row:
                    prompt_content = row[0] or ""
                    table_list = row[1] or ""
                    query_patterns = row[2] or ""
                    
                    # Combine components into comprehensive prompt
                    full_prompt = f"""{prompt_content}

AVAILABLE TABLES: {table_list}

QUERY PATTERNS:
{query_patterns}
"""
                    HierarchicalSearchConsumer._subcategory_prompts_cache[prompt_key] = full_prompt
                    return full_prompt
                else:
                    print(f"No specialized prompt found for {category}_{subcategory}")
                    return None
                    
        except Exception as e:
            print(f"Error fetching subcategory prompt: {e}")
            return None


_shared_db_engine = None

def get_shared_db_engine():
    global _shared_db_engine
    if _shared_db_engine is None:
        sql_user = os.environ.get('DATABASE_USER', '')
        sql_password = os.environ.get('DATABASE_PASSWORD', '')
        sql_server = os.environ.get('DATABASE_HOST', '')
        sql_db = os.environ.get('DATABASE_NAME', '')
        sql_driver = os.environ.get('DATABASE_DRIVER', 'ODBC Driver 17 for SQL Server')
        connection_url = (
            f"mssql+pyodbc://{sql_user}:{quote_plus(sql_password)}@{sql_server}/{sql_db}"
            f"?driver={sql_driver.replace(' ', '+')}"
        )
        _shared_db_engine = create_engine(connection_url, fast_executemany=True, pool_pre_ping=True)
    return _shared_db_engine


class ChatHistoryConsumer(AsyncWebsocketConsumer):
    """
    Async WebSocket Consumer for History Page and Sidebar Recent Chats (/ws/history/)
    Retrieves previous conversation list, message history for a ChatID, and CSV exports cleanly without blocking Daphne tasks.
    """
    async def connect(self):
        await self.accept()
        await self.send_chat_list()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action = data.get("action")

            if action == "get_chat_list":
                await self.send_chat_list()
            elif action == "get_chat":
                chat_id = data.get("chat_id")
                if chat_id:
                    await self.send_chat_messages(chat_id)
            elif action == "csv_download":
                chat_id = data.get("chat_id")
                if chat_id:
                    await self.send_chat_csv(chat_id)
        except Exception as e:
            logging.error(f"Error handling ChatHistoryConsumer receive: {e}")

    @sync_to_async
    def _fetch_chat_list(self):
        engine = get_shared_db_engine()
        with engine.begin() as conn:
            sql = text("""
                WITH RankedQuestions AS (
                    SELECT 
                        ChatID,
                        Question,
                        Username,
                        Created_At,
                        ROW_NUMBER() OVER (PARTITION BY ChatID ORDER BY Id ASC) as rn
                    FROM dbo.Marklytix_ChatHistory
                    WHERE Question IS NOT NULL AND Question <> ''
                ),
                ChatStats AS (
                    SELECT 
                        ChatID,
                        MAX(Created_At) as max_created_at,
                        COUNT(Id) as message_count
                    FROM dbo.Marklytix_ChatHistory
                    GROUP BY ChatID
                )
                SELECT 
                    s.ChatID,
                    q.Question as first_question,
                    q.Username,
                    s.max_created_at,
                    s.message_count
                FROM ChatStats s
                LEFT JOIN RankedQuestions q ON s.ChatID = q.ChatID AND q.rn = 1
                ORDER BY s.max_created_at DESC
            """)
            rows = conn.execute(sql).fetchall()
            chats = []
            for r in rows:
                q_text = (r[1] or "").strip()
                title_words = q_text.split() if q_text else []
                title = " ".join(title_words[:6]) if title_words else f"Chat #{r[0]}"
                if len(title_words) > 6:
                    title += "..."
                
                chats.append({
                    "ChatID": r[0],
                    "first_question": q_text or title,
                    "question": q_text or title,
                    "title": title,
                    "Username": r[2] or "SONATABOT",
                    "created_at": r[3].isoformat() if r[3] else datetime.now().isoformat(),
                    "message_count": r[4]
                })
            return chats

    async def send_chat_list(self):
        try:
            chats = await self._fetch_chat_list()
            await self.send(text_data=json.dumps({
                "type": "chat_list",
                "chats": chats
            }))
        except Exception as e:
            logging.error(f"Error in send_chat_list: {e}")
            await self.send(text_data=json.dumps({"type": "chat_list", "chats": []}))

    @sync_to_async
    def _fetch_chat_messages(self, chat_id):
        engine = get_shared_db_engine()
        with engine.begin() as conn:
            sql = text("""
                SELECT 
                    Sender,
                    Question,
                    Result_Generated,
                    Response_Table,
                    Generated_Query,
                    Query_Creation_Time,
                    Query_Execution_Time,
                    Created_At
                FROM dbo.Marklytix_ChatHistory
                WHERE ChatID = :chat_id
                ORDER BY Id ASC
            """)
            rows = conn.execute(sql, {"chat_id": chat_id}).fetchall()
            messages = []
            for r in rows:
                sender = (r[0] or "bot").lower()
                messages.append({
                    "sender": sender,
                    "question": r[1] or "",
                    "result_generated": r[2] or r[1] or "",
                    "response_table": r[3] or "",
                    "generated_query": r[4] or "",
                    "query_creation_time": r[5] or 0.0,
                    "query_execution_time": r[6] or 0.0,
                    "created_at": r[7].isoformat() if r[7] else datetime.now().isoformat()
                })
            return messages

    async def send_chat_messages(self, chat_id):
        try:
            messages = await self._fetch_chat_messages(chat_id)
            await self.send(text_data=json.dumps({
                "type": "chat_messages",
                "chat_id": chat_id,
                "messages": messages
            }))
        except Exception as e:
            logging.error(f"Error in send_chat_messages for ChatID {chat_id}: {e}")
            await self.send(text_data=json.dumps({
                "type": "chat_messages",
                "chat_id": chat_id,
                "messages": []
            }))

    @sync_to_async
    def _generate_chat_csv(self, chat_id):
        engine = get_shared_db_engine()
        with engine.begin() as conn:
            sql = text("""
                SELECT Question, Generated_Query, Result_Generated, Created_At
                FROM dbo.Marklytix_ChatHistory
                WHERE ChatID = :chat_id
                ORDER BY Id ASC
            """)
            rows = conn.execute(sql, {"chat_id": chat_id}).fetchall()
            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer)
            writer.writerow(["Question", "Generated_Query", "Result_Generated", "Created_At"])
            for r in rows:
                writer.writerow([r[0] or "", r[1] or "", r[2] or "", r[3] or ""])
            return csv_buffer.getvalue()

    async def send_chat_csv(self, chat_id):
        try:
            csv_data = await self._generate_chat_csv(chat_id)
            await self.send(text_data=json.dumps({
                "type": "csv_download",
                "filename": f"chat_history_{chat_id}.csv",
                "csv_data": csv_data
            }))
        except Exception as e:
            logging.error(f"Error generating chat CSV: {e}")



# -------------------------------------- ai graph consumer ------------------------------------- #
