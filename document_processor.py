import io
import numpy as np
import pandas as pd
import re
import json
import cv2
from datetime import datetime
from typing import List, Dict, Any, Optional
from PIL import Image
import pytesseract
import google.generativeai as genai
import fitz
import pdfplumber
import streamlit as st

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
    'itr': {
        'name': 'Income Tax Return',
        'patterns': [r'income tax return', r'itr', r'assessment year', r'total income'],
        'required_fields': ['name', 'pan_number', 'assessment_year', 'total_income'],
        'validation_regex': None
    },
    'bank_statement': {
        'name': 'Bank Statement',
        'patterns': [r'bank statement', r'account statement', r'current balance', r'account number'],
        'required_fields': ['account_number', 'bank_name', 'account_holder_name', 'balance'],
        'validation_regex': None
    },
    'cibil_report': {
        'name': 'CIBIL Report',
        'patterns': [r'cibil', r'credit score', r'credit report', r'transunion'],
        'required_fields': ['cibil_score', 'name', 'pan_number', 'report_date'],
        'validation_regex': None
    }
}

class DocumentProcessor:
    def __init__(self):
        self.document_types = DOCUMENT_TYPES
    
    def preprocess_image(self, image):
        """Preprocess image for better OCR results"""
        try:
            img_array = np.array(image)
            gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 35, 11
            )
            resized = cv2.resize(thresh, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
            return Image.fromarray(resized)
        except Exception as e:
            st.error(f"Image preprocessing error: {e}")
            return image
    
    def extract_text_tesseract(self, image, aadhaar_mode=False):
        """Extract text using Tesseract OCR"""
        try:
            processed = self.preprocess_image(image)
            config = "--psm 6" if aadhaar_mode else ""
            text = pytesseract.image_to_string(processed, lang="eng+hin", config=config)
            return text.strip()
        except Exception as e:
            st.error(f"OCR Error: {e}")
            return ""
    
    def extract_text_from_pdf(self, uploaded_file):
        """Extract text from PDF with multiple methods"""
        try:
            text_pages = []
            
            # Method 1: Using pdfplumber
            try:
                with pdfplumber.open(uploaded_file) as pdf:
                    for page in pdf.pages:
                        extracted_text = page.extract_text()
                        if extracted_text:
                            text_pages.append(extracted_text)
                        else:
                            # OCR fallback for scanned pages
                            pil_image = page.to_image(resolution=400).original
                            ocr_text = self.extract_text_tesseract(pil_image)
                            text_pages.append(ocr_text)
            except:
                # Method 2: Using PyMuPDF
                pdf_bytes = uploaded_file.read()
                uploaded_file.seek(0)  # Reset file pointer
                doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
                
                for page_num, page in enumerate(doc):
                    page_text = page.get_text()
                    if not page_text.strip():
                        # OCR fallback
                        pix = page.get_pixmap()
                        img_data = pix.tobytes("png")
                        img = Image.open(io.BytesIO(img_data))
                        page_text = self.extract_text_tesseract(img)
                    text_pages.append(page_text)
                doc.close()
            
            return "\n\n".join(text_pages)
            
        except Exception as e:
            st.error(f"PDF extraction error: {e}")
            return ""
    
    def extract_text_from_image(self, image_file):
        """Extract text from image"""
        try:
            image = Image.open(image_file)
            aadhaar_mode = 'aadhaar' in image_file.name.lower()
            return self.extract_text_tesseract(image, aadhaar_mode=aadhaar_mode)
        except Exception as e:
            st.error(f"Image extraction error: {e}")
            return ""
    
    def identify_document_type(self, text: str) -> str:
        """Identify document type based on text patterns"""
        text_lower = text.lower()
        scores = {}
        
        for doc_type, config in self.document_types.items():
            score = 0
            for pattern in config['patterns']:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    score += 1
            scores[doc_type] = score
        
        return max(scores, key=scores.get) if scores and max(scores.values()) > 0 else 'other'
    
    def extract_fields_with_ai(self, text: str, doc_type: str, filename: str) -> Dict[str, Any]:
        """Extract fields using AI with enhanced prompts"""
        if not st.session_state.gemini_configured:
            return {"error": "Gemini API not configured"}
        
        try:
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            
            if doc_type == 'salary_slip':
                prompt = f"""
                Analyze this salary slip and extract salary information. Return ONLY valid JSON:
                {{
                    "Employee Name": "...",
                    "Employee ID": "...",
                    "Designation": "...",
                    "Company Name": "...",
                    "Pay Date": "...",
                    "Month": "...",
                    "Year": "...",
                    "Basic Pay": "...",
                    "HRA": "...",
                    "Other Allowances": "...",
                    "Gross Salary": "...",
                    "Deductions": "...",
                    "Net Pay": "...",
                    "Annual CTC": "...",
                    "confidence": 85
                }}
                
                Text: {text[:3000]}
                """
            elif doc_type == 'cibil_report':
                prompt = f"""
                Extract CIBIL/Credit Report information. Return ONLY valid JSON:
                {{
                    "CIBIL Score": "...",
                    "Name": "...",
                    "PAN Number": "...",
                    "Report Date": "...",
                    "Credit Accounts": "...",
                    "Total Credit Limit": "...",
                    "Credit Utilization": "...",
                    "Payment History": "...",
                    "Credit Age": "...",
                    "Recent Inquiries": "...",
                    "confidence": 85
                }}
                
                Text: {text[:3000]}
                """
            else:
                schema_fields = self.document_types.get(doc_type, self.document_types['aadhaar'])['required_fields']
                prompt = f"""
                Extract information from this {doc_type} document. Return ONLY valid JSON:
                {{
                    {', '.join([f'"{field}": "..."' for field in schema_fields])},
                    "confidence": 85
                }}
                
                If a field is not found, use "Not Available".
                Text: {text[:3000]}
                """
            
            response = model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Clean JSON response
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            
            data = json.loads(response_text.strip())
            
            # Add metadata
            data.update({
                "document_type": doc_type,
                "filename": filename,
                "extraction_method": "AI",
                "processed_at": datetime.now().isoformat()
            })
            
            return data
            
        except Exception as e:
            st.error(f"AI extraction error: {e}")
            return {"error": str(e), "confidence": 0}
    
    def regex_extract_fields(self, text: str) -> Dict[str, str]:
        """Fallback regex extraction for key fields"""
        fields = {}
        
        patterns = {
            "Aadhaar Number": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
            "PAN Number": r'\b[A-Z]{5}[0-9]{4}[A-Z]\b',
            "Phone Number": r'(\+91[-\s]?\d{10}|\b\d{10}\b)',
            "Date of Birth": r'(?:DOB[:\s]*)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            "Year of Birth": r'(?:YOB[:\s]*)?(\d{4})',
            "CIBIL Score": r'(?:cibil|credit)?\s*score[:\s]*(\d{3})',
            "Net Pay": r'(?:net\s*pay|net\s*salary)[:\s]*₹?\s*([\d,]+)',
            "Gross Pay": r'(?:gross\s*pay|gross\s*salary)[:\s]*₹?\s*([\d,]+)',
            "Account Number": r'(?:account\s*no|a/c\s*no)[:\s]*(\d{9,18})'
        }
        
        for field, pattern in patterns.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                fields[field] = matches[0] if isinstance(matches[0], str) else matches[0]
        
        return fields
    
    def verify_document(self, doc_type: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Verify document based on type"""
        if doc_type == 'aadhaar':
            aadhaar_number = analysis.get('aadhaar_number') or analysis.get('Aadhaar Number')
            if aadhaar_number:
                return self.verify_aadhaar(aadhaar_number)
        
        elif doc_type == 'pan':
            pan_number = analysis.get('pan_number') or analysis.get('PAN Number')
            if pan_number:
                return self.verify_pan(pan_number)
        
        elif doc_type == 'cibil_report':
            cibil_score = analysis.get('CIBIL Score')
            if cibil_score:
                return self.validate_cibil_score(str(cibil_score))
        
        return {'is_valid': False, 'details': ['No verification available']}
    
    def verify_aadhaar(self, aadhaar_number: str) -> Dict[str, Any]:
        """Verify Aadhaar number with Verhoeff checksum"""
        clean_aadhaar = re.sub(r'\s+', '', aadhaar_number)
        
        result = {
            'is_valid': False,
            'format_valid': False,
            'checksum_valid': False,
            'details': []
        }
        
        if re.match(r'^[2-9]{1}[0-9]{11}$', clean_aadhaar):
            result['format_valid'] = True
            result['details'].append("Format is valid")
            
            # Verhoeff checksum validation
            def verhoeff_checksum(num_str):
                d = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
                     [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
                     [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
                     [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
                     [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
                
                p = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
                     [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
                     [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
                     [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
                
                c = 0
                for i, digit in enumerate(reversed([int(x) for x in num_str])):
                    c = d[c][p[(i + 1) % 8][digit]]
                return c == 0
            
            if verhoeff_checksum(clean_aadhaar):
                result['checksum_valid'] = True
                result['details'].append("Checksum is valid")
                result['is_valid'] = True
            else:
                result['details'].append("Invalid checksum")
        else:
            result['details'].append("Invalid format - should be 12 digits starting with 2-9")
        
        return result
    
    def verify_pan(self, pan_number: str) -> Dict[str, Any]:
        """Verify PAN number format"""
        clean_pan = pan_number.upper().replace(' ', '')
        
        result = {
            'is_valid': False,
            'format_valid': False,
            'details': []
        }
        
        if re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', clean_pan):
            result['format_valid'] = True
            result['is_valid'] = True
            result['details'].append("Format is valid")
            
            fourth_char = clean_pan[3]
            if fourth_char == 'P':
                result['details'].append("Individual PAN")
            elif fourth_char in ['C', 'H', 'F', 'A', 'T', 'B', 'L', 'J', 'G']:
                result['details'].append("Company/Entity PAN")
        else:
            result['details'].append("Invalid format - should be AAAAA9999A")
        
        return result
    
    def validate_cibil_score(self, score: str) -> Dict[str, Any]:
        """Validate and categorize CIBIL score"""
        try:
            score_int = int(score)
            
            result = {
                'is_valid': True,
                'score': score_int,
                'category': '',
                'description': '',
                'loan_impact': '',
                'details': []
            }
            
            if 300 <= score_int <= 850:
                if score_int >= 750:
                    result['category'] = 'Excellent'
                    result['description'] = 'Excellent credit score'
                    result['loan_impact'] = 'Best interest rates, quick approvals'
                    result['details'].append("Excellent credit history")
                elif score_int >= 650:
                    result['category'] = 'Good'
                    result['description'] = 'Good credit score'
                    result['loan_impact'] = 'Good interest rates, likely approval'
                    result['details'].append("Good credit management")
                elif score_int >= 550:
                    result['category'] = 'Fair'
                    result['description'] = 'Fair credit score'
                    result['loan_impact'] = 'Higher interest rates, conditional approval'
                    result['details'].append("Room for improvement")
                else:
                    result['category'] = 'Poor'
                    result['description'] = 'Poor credit score'
                    result['loan_impact'] = 'Difficult approval, very high rates'
                    result['details'].append("Significant credit issues")
            else:
                result['is_valid'] = False
                result['details'].append("Score out of valid range (300-850)")
                
        except ValueError:
            result = {
                'is_valid': False,
                'details': ['Invalid score format']
            }
        
        return result