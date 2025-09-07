import sqlite3
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import os

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
        
        # Document instances table (for multiple processing sessions)
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
            file_size INTEGER,
            mime_type VARCHAR(100),
            extracted_text TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processing_status VARCHAR(20) DEFAULT 'pending',
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
            extracted_data TEXT NOT NULL,  -- JSON string
            verification_result TEXT,      -- JSON string
            processing_method VARCHAR(50) DEFAULT 'AI',
            confidence_score FLOAT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (document_id) REFERENCES documents (document_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        # Loan eligibility table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS loan_eligibility (
            eligibility_id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            overall_score FLOAT NOT NULL,
            max_loan_amount DECIMAL(15,2),
            recommended_loan_amount DECIMAL(15,2),
            interest_rate_range VARCHAR(50),
            risk_assessment VARCHAR(20),
            cibil_impact FLOAT DEFAULT 0,
            identity_verification BOOLEAN DEFAULT 0,
            income_verification BOOLEAN DEFAULT 0,
            eligibility_data TEXT,  -- JSON string
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (instance_id) REFERENCES document_instances (instance_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        # Consistency checks table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS consistency_checks (
            check_id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            overall_score INTEGER DEFAULT 100,
            name_consistency BOOLEAN DEFAULT 1,
            pan_consistency BOOLEAN DEFAULT 1,
            phone_consistency BOOLEAN DEFAULT 1,
            address_consistency BOOLEAN DEFAULT 1,
            check_results TEXT,  -- JSON string
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (instance_id) REFERENCES document_instances (instance_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        # Chat history table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_type VARCHAR(20) NOT NULL,  -- 'user' or 'assistant'
            message_content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (instance_id) REFERENCES document_instances (instance_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        # API configurations table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_configurations (
            config_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            api_name VARCHAR(50) NOT NULL,
            api_key_hash VARCHAR(255),
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def hash_password(self, password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def hash_file_content(self, content: bytes) -> str:
        """Generate hash for file content"""
        return hashlib.md5(content).hexdigest()
    
    # User Management Methods
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
            
            return {
                'success': True,
                'user_id': user_id,
                'message': 'User created successfully'
            }
            
        except sqlite3.IntegrityError as e:
            return {
                'success': False,
                'message': 'Username or email already exists'
            }
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
            # Update last login
            cursor.execute('''
            UPDATE users SET last_login = CURRENT_TIMESTAMP 
            WHERE user_id = ?
            ''', (user[0],))
            conn.commit()
            
            result = {
                'success': True,
                'user_id': user[0],
                'username': user[1],
                'email': user[2]
            }
        else:
            result = {
                'success': False,
                'message': 'Invalid credentials or inactive account'
            }
        
        conn.close()
        return result
    
    # Document Instance Methods
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
    
    def update_instance_timestamp(self, instance_id: int):
        """Update instance last modified timestamp"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        UPDATE document_instances 
        SET updated_at = CURRENT_TIMESTAMP 
        WHERE instance_id = ?
        ''', (instance_id,))
        
        conn.commit()
        conn.close()
    
    # Document Methods
    def save_document(self, instance_id: int, user_id: int, filename: str, 
                     document_type: str, file_content: bytes, mime_type: str, 
                     extracted_text: str) -> int:
        """Save uploaded document"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        file_hash = self.hash_file_content(file_content)
        file_size = len(file_content)
        
        cursor.execute('''
        INSERT INTO documents 
        (instance_id, user_id, filename, document_type, file_hash, file_size, 
         mime_type, extracted_text, processing_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'processed')
        ''', (instance_id, user_id, filename, document_type, file_hash, 
              file_size, mime_type, extracted_text))
        
        document_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        self.update_instance_timestamp(instance_id)
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
        
        # Update document confidence score
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
    
    # Loan Eligibility Methods
    def save_loan_eligibility(self, instance_id: int, user_id: int, 
                             eligibility_data: Dict[str, Any]):
        """Save loan eligibility calculation"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if eligibility already exists for this instance
        cursor.execute('''
        SELECT eligibility_id FROM loan_eligibility 
        WHERE instance_id = ? AND user_id = ?
        ''', (instance_id, user_id))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing record
            cursor.execute('''
            UPDATE loan_eligibility SET
            overall_score = ?, max_loan_amount = ?, recommended_loan_amount = ?,
            interest_rate_range = ?, risk_assessment = ?, cibil_impact = ?,
            identity_verification = ?, income_verification = ?, eligibility_data = ?,
            calculated_at = CURRENT_TIMESTAMP
            WHERE eligibility_id = ?
            ''', (
                eligibility_data['overall_score'],
                eligibility_data['max_loan_amount'],
                eligibility_data['recommended_loan_amount'],
                eligibility_data['interest_rate_range'],
                eligibility_data['risk_assessment'],
                eligibility_data['cibil_impact'],
                eligibility_data['identity_verification'],
                eligibility_data['income_verification'],
                json.dumps(eligibility_data),
                existing[0]
            ))
        else:
            # Insert new record
            cursor.execute('''
            INSERT INTO loan_eligibility 
            (instance_id, user_id, overall_score, max_loan_amount, 
             recommended_loan_amount, interest_rate_range, risk_assessment,
             cibil_impact, identity_verification, income_verification, eligibility_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                instance_id, user_id, eligibility_data['overall_score'],
                eligibility_data['max_loan_amount'], eligibility_data['recommended_loan_amount'],
                eligibility_data['interest_rate_range'], eligibility_data['risk_assessment'],
                eligibility_data['cibil_impact'], eligibility_data['identity_verification'],
                eligibility_data['income_verification'], json.dumps(eligibility_data)
            ))
        
        conn.commit()
        conn.close()
        self.update_instance_timestamp(instance_id)
    
    def get_loan_eligibility(self, instance_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Get loan eligibility for an instance"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT eligibility_data FROM loan_eligibility 
        WHERE instance_id = ? AND user_id = ?
        ORDER BY calculated_at DESC LIMIT 1
        ''', (instance_id, user_id))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return json.loads(result[0])
        return None
    
    # Consistency Check Methods
    def save_consistency_check(self, instance_id: int, user_id: int, 
                              consistency_data: Dict[str, Any]):
        """Save consistency check results"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO consistency_checks 
        (instance_id, user_id, overall_score, name_consistency, pan_consistency,
         phone_consistency, address_consistency, check_results)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            instance_id, user_id, consistency_data['overall_score'],
            consistency_data['name_consistency'], consistency_data['pan_consistency'],
            consistency_data['phone_consistency'], consistency_data['address_consistency'],
            json.dumps(consistency_data)
        ))
        
        conn.commit()
        conn.close()
        self.update_instance_timestamp(instance_id)
    
    def get_consistency_check(self, instance_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Get latest consistency check for an instance"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT check_results FROM consistency_checks 
        WHERE instance_id = ? AND user_id = ?
        ORDER BY checked_at DESC LIMIT 1
        ''', (instance_id, user_id))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return json.loads(result[0])
        return None
    
    # Chat History Methods
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
    
    # API Configuration Methods
    def save_api_config(self, user_id: int, api_name: str, api_key: str):
        """Save API configuration"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        api_key_hash = self.hash_password(api_key)  # Use same hashing for API keys
        
        # Deactivate existing configs for this API
        cursor.execute('''
        UPDATE api_configurations SET is_active = 0 
        WHERE user_id = ? AND api_name = ?
        ''', (user_id, api_name))
        
        # Insert new config
        cursor.execute('''
        INSERT INTO api_configurations (user_id, api_name, api_key_hash, is_active)
        VALUES (?, ?, ?, 1)
        ''', (user_id, api_name, api_key_hash))
        
        conn.commit()
        conn.close()
    
    def verify_api_config(self, user_id: int, api_name: str, api_key: str) -> bool:
        """Verify API configuration"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        api_key_hash = self.hash_password(api_key)
        cursor.execute('''
        SELECT config_id FROM api_configurations 
        WHERE user_id = ? AND api_name = ? AND api_key_hash = ? AND is_active = 1
        ''', (user_id, api_name, api_key_hash))
        
        result = cursor.fetchone()
        conn.close()
        
        return result is not None