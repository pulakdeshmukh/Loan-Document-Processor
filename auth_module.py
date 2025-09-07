import streamlit as st
from database_setup import DatabaseManager
import re

def init_auth_session_state():
    """Initialize authentication session state"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user_id' not in st.session_state:
        st.session_state.user_id = None
    if 'username' not in st.session_state:
        st.session_state.username = None
    if 'email' not in st.session_state:
        st.session_state.email = None
    if 'current_instance_id' not in st.session_state:
        st.session_state.current_instance_id = None

def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_password(password: str) -> tuple[bool, str]:
    """Validate password strength"""
    if len(password) < 6:
        return False, "Password must be at least 6 characters long"
    if not re.search(r'[A-Za-z]', password):
        return False, "Password must contain at least one letter"
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    return True, "Password is valid"

def show_login_form():
    """Display login form"""
    st.subheader("🔐 Login to Your Account")
    
    with st.form("login_form", clear_on_submit=True):
        username = st.text_input("Username", placeholder="Enter your username")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        
        col1, col2 = st.columns(2)
        with col1:
            login_submitted = st.form_submit_button("Login", type="primary", use_container_width=True)
        with col2:
            if st.form_submit_button("Forgot Password?", use_container_width=True):
                st.info("Please contact administrator for password reset")
    
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
        username = st.text_input("Username", placeholder="Choose a username (3-50 characters)")
        email = st.text_input("Email", placeholder="Enter your email address")
        password = st.text_input("Password", type="password", placeholder="Create a strong password")
        confirm_password = st.text_input("Confirm Password", type="password", placeholder="Re-enter your password")
        
        terms_accepted = st.checkbox("I agree to the Terms of Service and Privacy Policy")
        
        signup_submitted = st.form_submit_button("Create Account", type="primary", use_container_width=True)
    
    if signup_submitted:
        # Validation
        errors = []
        
        if not username or len(username) < 3 or len(username) > 50:
            errors.append("Username must be between 3-50 characters")
        
        if not email or not validate_email(email):
            errors.append("Please enter a valid email address")
        
        if not password:
            errors.append("Password is required")
        else:
            is_valid, password_msg = validate_password(password)
            if not is_valid:
                errors.append(password_msg)
        
        if password != confirm_password:
            errors.append("Passwords do not match")
        
        if not terms_accepted:
            errors.append("Please accept the Terms of Service and Privacy Policy")
        
        if errors:
            for error in errors:
                st.error(error)
        else:
            # Create user
            db = DatabaseManager()
            result = db.create_user(username, email, password)
            
            if result['success']:
                st.success("Account created successfully! Please login with your credentials.")
                st.balloons()
                st.info("You can now switch to the Login tab to access your account.")
            else:
                st.error(result['message'])

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
    
    # Center the authentication form
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        
        with tab1:
            show_login_form()
        
        with tab2:
            show_signup_form()
    
    # Footer information
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        **🔒 Secure Processing**
        - End-to-end encryption
        - Secure document storage
        - Privacy protected
        """)
    
    with col2:
        st.markdown("""
        **🤖 AI-Powered Analysis**
        - Advanced OCR technology
        - Smart field extraction
        - Automated verification
        """)
    
    with col3:
        st.markdown("""
        **📊 Complete Analysis**
        - Loan eligibility calculation
        - CIBIL score analysis
        - Document consistency check
        """)

def logout_user():
    """Logout current user"""
    st.session_state.authenticated = False
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.email = None
    st.session_state.current_instance_id = None
    
    # Clear any processed documents from session
    if 'processed_documents' in st.session_state:
        st.session_state.processed_documents = {}
    if 'document_analysis' in st.session_state:
        st.session_state.document_analysis = {}
    if 'verification_results' in st.session_state:
        st.session_state.verification_results = {}
    if 'messages' in st.session_state:
        st.session_state.messages = []
    
    st.rerun()

def require_auth(func):
    """Decorator to require authentication for pages"""
    def wrapper(*args, **kwargs):
        if not st.session_state.get('authenticated', False):
            st.error("Please login to access this page")
            st.stop()
        return func(*args, **kwargs)
    return wrapper