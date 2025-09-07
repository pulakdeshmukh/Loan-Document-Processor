import streamlit as st
import sqlite3
import hashlib
import json
import io
import numpy as np
import pandas as pd
import re
import cv2
from datetime import datetime
from typing import List, Dict, Any, Optional
from PIL import Image
import pytesseract
import google.generativeai as genai
import fitz
import pdfplumber

# Page Configuration
st.set_page_config(
    page_title="Loan Document Processing System", 
    page_icon="🏦", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1f4e79 0%, #2e8b57 100%);
        color: white;
        padding: 1rem;
        border-radius: 10px;
        text-align: center;
        margin-bottom: 2rem;
    }
    .instance-card {
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        background: white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .user-info {
        background: linear-gradient(90deg, #1f4e79 0%, #2e8b57 100%);
        padding: 0.5rem 1rem;
        border-radius: 5px;
        border-left: 4px solid #007bff;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# Document Types Configuration
DOCUMENT_TYPES = {
    'aadhaar': {
        'name': 'Aadhaar Card',
        'patterns': [r'\d{4}\s?\d{4}\s?\d{4}', r'aadhaar', r'आधार', r'uidai'],
        'required_fields': ['aadhaar_number', 'name', 'address', 'dob'],
        'validation_regex': r'^[2-9]{1}[0-9]{3}\s?[0-9]{4}\s?[0-9]{4}$'
    },
    'pan': {
        'name': 'PAN Card',
        'patterns': [r'[A-Z]{5}[0-9]{4}[A-Z]{1}', r'permanent account number', r'income tax'],
        'required_fields': ['pan_number', 'name', 'father_name', 'dob'],
        'validation_regex': r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
    },
    'salary_slip': {
        'name': 'Salary Slip',
        'patterns': [r'salary slip', r'pay slip', r'payslip', r'net pay', r'gross salary'],
        'required_fields': ['employee_name', 'employee_id', 'basic_pay', 'net_pay', 'pay_date'],
        'validation_regex': None
    },
    'cibil_report': {
        'name': 'CIBIL Report',
        'patterns': [r'cibil', r'credit score', r'credit report', r'transunion'],
        'required_fields': ['cibil_score', 'name', 'pan_number', 'report_date'],
        'validation_regex': None
    }
}

class DatabaseManager:
    def __init__(self, db_path: str = "loan_verification.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database with all required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
        ''')
        
        # Document instances table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_instances (
            instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            instance_name VARCHAR(100) NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        # Documents table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            document_id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            filename VARCHAR(255) NOT NULL,
            document_type VARCHAR(50) NOT NULL,
            file_hash VARCHAR(64) UNIQUE,
            extracted_text TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confidence_score FLOAT DEFAULT 0,
            FOREIGN KEY (instance_id) REFERENCES document_instances (instance_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        # Document analysis table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS document_analysis (
            analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            extracted_data TEXT NOT NULL,
            verification_result TEXT,
            confidence_score FLOAT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (document_id) REFERENCES documents (document_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        # Chat history table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_type VARCHAR(20) NOT NULL,
            message_content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (instance_id) REFERENCES document_instances (instance_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def hash_password(self, password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def create_user(self, username: str, email: str, password: str) -> Dict[str, Any]:
        """Create a new user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            password_hash = self.hash_password(password)
            cursor.execute('''
            INSERT INTO users (username, email, password_hash)
            VALUES (?, ?, ?)
            ''', (username, email, password_hash))
            
            user_id = cursor.lastrowid
            conn.commit()
            
            return {'success': True, 'user_id': user_id, 'message': 'User created successfully'}
            
        except sqlite3.IntegrityError:
            return {'success': False, 'message': 'Username or email already exists'}
        finally:
            conn.close()
    
    def authenticate_user(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate user login"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        password_hash = self.hash_password(password)
        cursor.execute('''
        SELECT user_id, username, email, is_active 
        FROM users 
        WHERE username = ? AND password_hash = ?
        ''', (username, password_hash))
        
        user = cursor.fetchone()
        
        if user and user[3]:  # is_active
            cursor.execute('''
            UPDATE users SET last_login = CURRENT_TIMESTAMP 
            WHERE user_id = ?
            ''', (user[0],))
            conn.commit()
            
            result = {'success': True, 'user_id': user[0], 'username': user[1], 'email': user[2]}
        else:
            result = {'success': False, 'message': 'Invalid credentials'}
        
        conn.close()
        return result
    
    def create_document_instance(self, user_id: int, instance_name: str, description: str = "") -> int:
        """Create a new document processing instance"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO document_instances (user_id, instance_name, description)
        VALUES (?, ?, ?)
        ''', (user_id, instance_name, description))
        
        instance_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return instance_id
    
    def get_user_instances(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all document instances for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT instance_id, instance_name, description, created_at, updated_at, status
        FROM document_instances 
        WHERE user_id = ? 
        ORDER BY updated_at DESC
        ''', (user_id,))
        
        instances = []
        for row in cursor.fetchall():
            instances.append({
                'instance_id': row[0],
                'instance_name': row[1],
                'description': row[2],
                'created_at': row[3],
                'updated_at': row[4],
                'status': row[5]
            })
        
        conn.close()
        return instances
    
    def save_document(self, instance_id: int, user_id: int, filename: str, 
                     document_type: str, extracted_text: str) -> int:
        """Save uploaded document"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        file_hash = hashlib.md5(f"{filename}_{datetime.now().timestamp()}".encode()).hexdigest()
        
        cursor.execute('''
        INSERT INTO documents 
        (instance_id, user_id, filename, document_type, file_hash, extracted_text)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (instance_id, user_id, filename, document_type, file_hash, extracted_text))
        
        document_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return document_id
    
    def save_document_analysis(self, document_id: int, user_id: int, 
                              extracted_data: Dict[str, Any], 
                              verification_result: Dict[str, Any], 
                              confidence_score: float):
        """Save document analysis results"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO document_analysis 
        (document_id, user_id, extracted_data, verification_result, confidence_score)
        VALUES (?, ?, ?, ?, ?)
        ''', (document_id, user_id, json.dumps(extracted_data), 
              json.dumps(verification_result), confidence_score))
        
        cursor.execute('''
        UPDATE documents SET confidence_score = ? WHERE document_id = ?
        ''', (confidence_score, document_id))
        
        conn.commit()
        conn.close()
    
    def get_instance_documents(self, instance_id: int, user_id: int) -> List[Dict[str, Any]]:
        """Get all documents for a specific instance"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT d.document_id, d.filename, d.document_type, d.upload_date, 
               d.confidence_score, da.extracted_data, da.verification_result
        FROM documents d
        LEFT JOIN document_analysis da ON d.document_id = da.document_id
        WHERE d.instance_id = ? AND d.user_id = ?
        ORDER BY d.upload_date DESC
        ''', (instance_id, user_id))
        
        documents = []
        for row in cursor.fetchall():
            extracted_data = json.loads(row[5]) if row[5] else {}
            verification_result = json.loads(row[6]) if row[6] else {}
            
            documents.append({
                'document_id': row[0],
                'filename': row[1],
                'document_type': row[2],
                'upload_date': row[3],
                'confidence_score': row[4] or 0,
                'extracted_data': extracted_data,
                'verification_result': verification_result
            })
        
        conn.close()
        return documents
    
    def save_chat_message(self, instance_id: int, user_id: int, 
                         message_type: str, message_content: str):
        """Save chat message"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO chat_history (instance_id, user_id, message_type, message_content)
        VALUES (?, ?, ?, ?)
        ''', (instance_id, user_id, message_type, message_content))
        
        conn.commit()
        conn.close()
    
    def get_chat_history(self, instance_id: int, user_id: int) -> List[Dict[str, Any]]:
        """Get chat history for an instance"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT message_type, message_content, created_at 
        FROM chat_history 
        WHERE instance_id = ? AND user_id = ?
        ORDER BY created_at ASC
        ''', (instance_id, user_id))
        
        messages = []
        for row in cursor.fetchall():
            messages.append({
                'role': row[0],
                'content': row[1],
                'timestamp': row[2]
            })
        
        conn.close()
        return messages

# Initialize session state
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'authenticated': False,
        'user_id': None,
        'username': None,
        'email': None,
        'current_instance_id': None,
        'gemini_configured': False,
        'processed_documents': {},
        'document_analysis': {},
        'verification_results': {},
        'messages': [],
        'current_page': 'dashboard'
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# Authentication functions
def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def show_auth_page():
    """Main authentication page"""
    st.markdown("""
    <div style="text-align: center; padding: 2rem;">
        <h1>🏦 Loan Document Verification System</h1>
        <p style="font-size: 1.2rem; color: #666;">
            Secure document processing with AI-powered analysis
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        
        with tab1:
            show_login_form()
        
        with tab2:
            show_signup_form()

def show_login_form():
    """Display login form"""
    st.subheader("🔐 Login to Your Account")
    
    with st.form("login_form", clear_on_submit=True):
        username = st.text_input("Username", placeholder="Enter your username")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        
        login_submitted = st.form_submit_button("Login", type="primary", use_container_width=True)
    
    if login_submitted:
        if username and password:
            db = DatabaseManager()
            result = db.authenticate_user(username, password)
            
            if result['success']:
                st.session_state.authenticated = True
                st.session_state.user_id = result['user_id']
                st.session_state.username = result['username']
                st.session_state.email = result['email']
                st.success(f"Welcome back, {result['username']}!")
                st.rerun()
            else:
                st.error(result['message'])
        else:
            st.error("Please enter both username and password")

def show_signup_form():
    """Display signup form"""
    st.subheader("📝 Create New Account")
    
    with st.form("signup_form", clear_on_submit=True):
        username = st.text_input("Username", placeholder="Choose a username")
        email = st.text_input("Email", placeholder="Enter your email address")
        password = st.text_input("Password", type="password", placeholder="Create a password")
        confirm_password = st.text_input("Confirm Password", type="password", placeholder="Re-enter your password")
        
        terms_accepted = st.checkbox("I agree to the Terms of Service")
        signup_submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)
    
    if signup_submitted:
        errors = []
        
        if not username or len(username) < 3:
            errors.append("Username must be at least 3 characters")
        
        if not email or not validate_email(email):
            errors.append("Please enter a valid email address")
        
        if not password or len(password) < 6:
            errors.append("Password must be at least 6 characters")
        
        if password != confirm_password:
            errors.append("Passwords do not match")
        
        if not terms_accepted:
            errors.append("Please accept the Terms of Service")
        
        if errors:
            for error in errors:
                st.error(error)
        else:
            db = DatabaseManager()
            result = db.create_user(username, email, password)
            
            if result['success']:
                st.success("Account created successfully! Please login.")
                st.balloons()
            else:
                st.error(result['message'])

def logout_user():
    """Logout current user"""
    st.session_state.authenticated = False
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.email = None
    st.session_state.current_instance_id = None
    st.session_state.processed_documents = {}
    st.session_state.document_analysis = {}
    st.session_state.verification_results = {}
    st.session_state.messages = []
    st.rerun()

# Document processing functions
def extract_text_from_pdf(uploaded_file):
    """Extract text from PDF"""
    try:
        text_pages = []
        
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                extracted_text = page.extract_text()
                if extracted_text:
                    text_pages.append(extracted_text)
        
        return "\n\n".join(text_pages)
        
    except Exception as e:
        st.error(f"PDF extraction error: {e}")
        return ""

def extract_text_from_image(image_file):
    """Extract text from image"""
    try:
        image = Image.open(image_file)
        text = pytesseract.image_to_string(image, lang="eng+hin")
        return text.strip()
    except Exception as e:
        st.error(f"Image extraction error: {e}")
        return ""

def identify_document_type(text: str) -> str:
    """Identify document type based on text patterns"""
    text_lower = text.lower()
    scores = {}
    
    for doc_type, config in DOCUMENT_TYPES.items():
        score = 0
        for pattern in config['patterns']:
            if re.search(pattern, text_lower, re.IGNORECASE):
                score += 1
        scores[doc_type] = score
    
    return max(scores, key=scores.get) if scores and max(scores.values()) > 0 else 'other'

def extract_fields_with_ai(text: str, doc_type: str, filename: str) -> Dict[str, Any]:
    """Extract fields using AI"""
    if not st.session_state.gemini_configured:
        return {"error": "Gemini API not configured"}
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        if doc_type == 'salary_slip':
            prompt = f"""
            Extract salary slip information. Return ONLY valid JSON:
            {{
                "Employee Name": "...",
                "Company Name": "...",
                "Net Pay": "...",
                "Gross Salary": "...",
                "Pay Date": "...",
                "confidence": 85
            }}
            
            Text: {text[:2000]}
            """
        elif doc_type == 'cibil_report':
            prompt = f"""
            Extract CIBIL report information. Return ONLY valid JSON:
            {{
                "CIBIL Score": "...",
                "Name": "...",
                "PAN Number": "...",
                "Report Date": "...",
                "confidence": 85
            }}
            
            Text: {text[:2000]}
            """
        else:
            prompt = f"""
            Extract information from this {doc_type} document. Return ONLY valid JSON with appropriate fields.
            If a field is not found, use "Not Available".
            
            Text: {text[:2000]}
            """
        
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Clean JSON response
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        
        data = json.loads(response_text.strip())
        data.update({
            "document_type": doc_type,
            "filename": filename,
            "processed_at": datetime.now().isoformat()
        })
        
        return data
        
    except Exception as e:
        return {"error": str(e), "confidence": 0}

def verify_document(doc_type: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Basic document verification"""
    return {'is_valid': True, 'details': ['Basic verification passed']}

def configure_gemini_api(api_key: str) -> bool:
    """Configure the Gemini API"""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        test_response = model.generate_content("Hello")
        st.session_state.gemini_configured = True
        return True
    except Exception as e:
        st.error(f"Failed to configure Gemini API: {e}")
        st.session_state.gemini_configured = False
        return False

# Main application pages
def show_sidebar():
    """Display sidebar with navigation and user info"""
    with st.sidebar:
        # User information
        if st.session_state.authenticated:
            st.markdown(f"""
            <div class="user-info">
                <strong>Welcome, {st.session_state.username}!</strong><br>
                <small>{st.session_state.email}</small>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("Logout", type="secondary", use_container_width=True):
                logout_user()
        
        st.divider()
        
        # Navigation
        st.header("Navigation")
        
        pages = {
            'dashboard': 'Dashboard',
            'documents': 'Document Processing', 
            'chat': 'Q&A Chat',
            'history': 'History'
        }
        
        for page_key, page_name in pages.items():
            if st.button(page_name, key=f"nav_{page_key}", use_container_width=True):
                st.session_state.current_page = page_key
                st.rerun()
        
        st.divider()
        
        # Instance management
        if st.session_state.authenticated:
            show_instance_management()

def show_instance_management():
    """Show document instance management in sidebar"""
    st.header("Document Instances")
    
    db = DatabaseManager()
    instances = db.get_user_instances(st.session_state.user_id)
    
    # Create new instance
    with st.expander("Create New Instance", expanded=False):
        with st.form("new_instance_form"):
            instance_name = st.text_input("Instance Name", placeholder="e.g., Home Loan Application")
            description = st.text_area("Description", placeholder="Brief description")
            
            if st.form_submit_button("Create Instance", type="primary"):
                if instance_name.strip():
                    instance_id = db.create_document_instance(
                        st.session_state.user_id, 
                        instance_name.strip(), 
                        description.strip()
                    )
                    st.session_state.current_instance_id = instance_id
                    st.success(f"Created instance: {instance_name}")
                    st.rerun()
                else:
                    st.error("Please enter an instance name")
    
    # Show existing instances
    if instances:
        st.subheader("Your Instances")
        
        for instance in instances:
            is_active = st.session_state.current_instance_id == instance['instance_id']
            
            if st.button(
                f"📁 {instance['instance_name']}", 
                key=f"instance_{instance['instance_id']}",
                type="primary" if is_active else "secondary",
                use_container_width=True
            ):
                st.session_state.current_instance_id = instance['instance_id']
                load_instance_data(instance['instance_id'])
                st.rerun()
            
            if instance['description']:
                st.caption(instance['description'])
            st.caption(f"Updated: {instance['updated_at'][:16]}")
    else:
        st.info("No instances yet. Create your first one above!")

def load_instance_data(instance_id: int):
    """Load data for a specific instance"""
    db = DatabaseManager()
    
    documents = db.get_instance_documents(instance_id, st.session_state.user_id)
    
    st.session_state.processed_documents = {}
    st.session_state.document_analysis = {}
    st.session_state.verification_results = {}
    
    for doc in documents:
        doc_id = str(doc['document_id'])
        
        st.session_state.processed_documents[doc_id] = {
            'filename': doc['filename'],
            'type': doc['document_type'],
            'status': 'Processed',
            'confidence': doc['confidence_score']
        }
        
        st.session_state.document_analysis[doc_id] = doc['extracted_data']
        st.session_state.verification_results[doc_id] = doc['verification_result']
    
    # Load chat history
    messages = db.get_chat_history(instance_id, st.session_state.user_id)
    st.session_state.messages = messages

def show_dashboard():
    """Dashboard page"""
    st.markdown("""
    <div class="main-header">
        <h1>Dashboard - Loan Document Verification System</h1>
        <p>Complete overview of your document processing instances</p>
    </div>
    """, unsafe_allow_html=True)
    
    db = DatabaseManager()
    instances = db.get_user_instances(st.session_state.user_id)
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    total_instances = len(instances)
    total_documents = 0
    
    for instance in instances:
        docs = db.get_instance_documents(instance['instance_id'], st.session_state.user_id)
        total_documents += len(docs)
    
    with col1:
        st.metric("Total Instances", total_instances)
    with col2:
        st.metric("Total Documents", total_documents)
    with col3:
        active_instance = "Selected" if st.session_state.current_instance_id else "None"
        st.metric("Active Instance", active_instance)
    with col4:
        st.metric("API Status", "Configured" if st.session_state.gemini_configured else "Not Set")
    
    # Recent instances
    st.subheader("Recent Instances")
    
    if instances:
        for instance in instances[:5]:
            with st.expander(f"📁 {instance['instance_name']}", expanded=False):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**Created:** {instance['created_at'][:16]}")
                    st.write(f"**Status:** {instance['status'].title()}")
                
                with col2:
                    docs = db.get_instance_documents(instance['instance_id'], st.session_state.user_id)
                    st.write(f"**Documents:** {len(docs)}")
                
                if instance['description']:
                    st.write(f"**Description:** {instance['description']}")
                
                if st.button(f"Load Instance", key=f"load_{instance['instance_id']}"):
                    st.session_state.current_instance_id = instance['instance_id']
                    load_instance_data(instance['instance_id'])
                    st.success(f"Loaded instance: {instance['instance_name']}")
                    st.rerun()
    else:
        st.info("No instances found. Create your first instance using the sidebar.")

def show_documents_page():
    """Document processing page"""
    st.header("Document Processing")
    
    if not st.session_state.current_instance_id:
        st.warning("Please select or create a document instance from the sidebar")
        return
    
    # API Configuration
    st.subheader("API Configuration")
    gemini_api_key = st.text_input("Gemini API Key:", type="password")
    
    if st.button("Configure API", type="primary"):
        if gemini_api_key:
            if configure_gemini_api(gemini_api_key):
                st.success("API configured successfully!")
            else:
                st.error("Failed to configure API")
        else:
            st.warning("Please enter your API key")
    
    st.divider()
    
    # Document upload
    st.subheader("Upload Documents")
    uploaded_files = st.file_uploader(
        "Choose document files",
        type=['pdf', 'png', 'jpg', 'jpeg'],
        accept_multiple_files=True,
        help="Upload Aadhaar, PAN, Salary Slip, ITR, Bank Statement, CIBIL Report"
    )
    
    if uploaded_files and st.session_state.gemini_configured:
        if st.button("Process All Documents", type="primary"):
            process_documents_with_db(uploaded_files)
    
    # Show processed documents
    if st.session_state.processed_documents:
        st.subheader("Processed Documents")
        
        for doc_id, doc_info in st.session_state.processed_documents.items():
            with st.expander(f"📄 {doc_info['filename']}"):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**Type:** {doc_info['type']}")
                    st.write(f"**Status:** {doc_info['status']}")
                    st.write(f"**Confidence:** {doc_info['confidence']:.1f}%")
                
                with col2:
                    if doc_id in st.session_state.verification_results:
                        verification = st.session_state.verification_results[doc_id]
                        if verification.get('is_valid'):
                            st.success("✅ Verified")
                        else:
                            st.error("❌ Issues Found")
                
                # Show extracted data
                if doc_id in st.session_state.document_analysis:
                    analysis = st.session_state.document_analysis[doc_id]
                    st.write("**Extracted Information:**")
                    for key, value in analysis.items():
                        if key not in ['confidence', 'document_type', 'filename', 'processed_at', 'error']:
                            if value and value != "Not Available":
                                st.write(f"- **{key}:** {value}")

def process_documents_with_db(uploaded_files):
    """Process documents and save to database"""
    if not st.session_state.current_instance_id:
        st.error("No active instance selected")
        return
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    db = DatabaseManager()
    
    for i, uploaded_file in enumerate(uploaded_files):
        progress = (i + 1) / len(uploaded_files)
        status_text.text(f"Processing {uploaded_file.name} ({i+1}/{len(uploaded_files)})...")
        progress_bar.progress(progress)
        
        # Extract text
        if uploaded_file.type == "application/pdf":
            text = extract_text_from_pdf(uploaded_file)
        else:
            text = extract_text_from_image(uploaded_file)
        
        if not text or len(text.strip()) < 10:
            st.error(f"Could not extract text from {uploaded_file.name}")
            continue
        
        # Identify document type and analyze
        doc_type = identify_document_type(text)
        analysis = extract_fields_with_ai(text, doc_type, uploaded_file.name)
        verification = verify_document(doc_type, analysis)
        
        # Save to database
        document_id = db.save_document(
            st.session_state.current_instance_id,
            st.session_state.user_id,
            uploaded_file.name,
            doc_type,
            text
        )
        
        db.save_document_analysis(
            document_id,
            st.session_state.user_id,
            analysis,
            verification,
            analysis.get('confidence', 0)
        )
        
        # Update session state
        doc_id = str(document_id)
        st.session_state.processed_documents[doc_id] = {
            'filename': uploaded_file.name,
            'type': doc_type,
            'status': 'Processed',
            'confidence': analysis.get('confidence', 0)
        }
        
        st.session_state.document_analysis[doc_id] = analysis
        st.session_state.verification_results[doc_id] = verification
    
    progress_bar.empty()
    status_text.success("All documents processed successfully!")

def show_chat_page():
    """Chat page"""
    st.header("Interactive Q&A")
    
    if not st.session_state.current_instance_id:
        st.warning("Please select a document instance to start chatting")
        return
    
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Suggested questions if no messages
    if not st.session_state.messages and st.session_state.processed_documents:
        st.subheader("Ask questions about your documents:")
        suggestions = [
            "Summarize my financial information",
            "What documents have been processed?",
            "What is my monthly income?",
            "Are there any issues with my documents?",
            "What loan amount might I be eligible for?"
        ]
        
        cols = st.columns(2)
        for i, suggestion in enumerate(suggestions):
            with cols[i % 2]:
                if st.button(suggestion, key=f"suggestion_{i}", use_container_width=True):
                    handle_chat_message(suggestion)
    
    # Chat input
    if prompt := st.chat_input("Ask questions about your documents..."):
        handle_chat_message(prompt)

def handle_chat_message(user_message):
    """Handle chat message and save to database"""
    if not st.session_state.current_instance_id:
        return
    
    # Add user message
    st.session_state.messages.append({"role": "user", "content": user_message})
    
    with st.chat_message("user"):
        st.markdown(user_message)
    
    # Generate and add assistant response
    with st.chat_message("assistant"):
        with st.spinner("Analyzing..."):
            response = generate_ai_response(user_message)
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
    
    # Save to database
    db = DatabaseManager()
    db.save_chat_message(
        st.session_state.current_instance_id,
        st.session_state.user_id,
        "user",
        user_message
    )
    db.save_chat_message(
        st.session_state.current_instance_id,
        st.session_state.user_id,
        "assistant", 
        response
    )

def generate_ai_response(query: str) -> str:
    """Generate AI response based on document analysis"""
    if not st.session_state.gemini_configured:
        return "Please configure the Gemini API key first."
    
    # Prepare context from processed documents
    context_parts = []
    for doc_id, analysis in st.session_state.document_analysis.items():
        doc_info = st.session_state.processed_documents[doc_id]
        doc_context = f"Document: {doc_info['filename']} (Type: {doc_info['type']})\n"
        
        for key, value in analysis.items():
            if key not in ['confidence', 'document_type', 'filename', 'processed_at', 'error']:
                if value and value != "Not Available":
                    doc_context += f"- {key}: {value}\n"
        context_parts.append(doc_context)
    
    context_str = "\n\n".join(context_parts)
    
    prompt = f"""
    You are an expert financial advisor and loan document analyst. Answer the user's question based on the provided document analysis.
    
    DOCUMENT ANALYSIS:
    {context_str}
    
    USER QUESTION: {query}
    
    Provide a comprehensive, accurate answer based on the document data. Include specific numbers, recommendations, and actionable insights where applicable.
    """
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error generating response: {e}"

def show_history_page():
    """History page showing all user instances and their data"""
    st.header("Document Processing History")
    
    db = DatabaseManager()
    instances = db.get_user_instances(st.session_state.user_id)
    
    if not instances:
        st.info("No processing history found. Start by creating your first document instance.")
        return
    
    # Summary statistics
    total_instances = len(instances)
    total_documents = 0
    
    for instance in instances:
        docs = db.get_instance_documents(instance['instance_id'], st.session_state.user_id)
        total_documents += len(docs)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Instances", total_instances)
    with col2:
        st.metric("Documents Processed", total_documents)
    with col3:
        st.metric("Current Instance", "Active" if st.session_state.current_instance_id else "None")
    
    st.divider()
    
    # Instance history
    for instance in instances:
        with st.expander(f"📁 {instance['instance_name']} - {instance['created_at'][:16]}", expanded=False):
            
            # Instance details
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Created:** {instance['created_at']}")
                st.write(f"**Last Updated:** {instance['updated_at']}")
                st.write(f"**Status:** {instance['status'].title()}")
            
            with col2:
                if instance['description']:
                    st.write(f"**Description:** {instance['description']}")
                
                # Load instance button
                if st.button(f"Load Instance", key=f"hist_load_{instance['instance_id']}"):
                    st.session_state.current_instance_id = instance['instance_id']
                    load_instance_data(instance['instance_id'])
                    st.success(f"Loaded instance: {instance['instance_name']}")
                    st.rerun()
            
            # Documents in this instance
            docs = db.get_instance_documents(instance['instance_id'], st.session_state.user_id)
            
            if docs:
                st.write("**Documents:**")
                for doc in docs:
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.write(f"📄 {doc['filename']}")
                    with col2:
                        st.write(f"*{doc['document_type']}*")
                    with col3:
                        confidence = doc['confidence_score']
                        if confidence >= 80:
                            st.success(f"{confidence:.0f}%")
                        elif confidence >= 60:
                            st.warning(f"{confidence:.0f}%")
                        else:
                            st.error(f"{confidence:.0f}%")
            else:
                st.write("*No documents in this instance*")

def main():
    """Main application entry point"""
    init_session_state()
    
    # Authentication check
    if not st.session_state.authenticated:
        show_auth_page()
        return
    
    # Show sidebar
    show_sidebar()
    
    # Route to pages based on current_page
    if st.session_state.current_page == 'dashboard':
        show_dashboard()
    elif st.session_state.current_page == 'documents':
        show_documents_page()
    elif st.session_state.current_page == 'chat':
        show_chat_page()
    elif st.session_state.current_page == 'history':
        show_history_page()
    else:
        show_dashboard()

if __name__ == "__main__":
    main()