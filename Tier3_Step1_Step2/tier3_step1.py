#!/usr/bin/env python3
"""
Tier 3 Rules Engine - Step 1: Loyalty ID (CID/LID) Validation

Validates Loyalty IDs per AGDC DTP Tier 3 requirements:
- Format validation (length, characters)
- Fraud detection (manager/store cards - 6+ transactions/day)
- Daily cap enforcement for CID promotional fund eligibility
"""

import re
import sqlite3
import os
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable


# --------------------------
# Configuration
# --------------------------
# Database file path
DB_FILE = "loyalty.db"

# Daily cap for CID fund eligibility (per AGDC DTP: 6+ transactions/day = manager/store card)
DAILY_TRANSACTION_CAP = 5  # Exceeding 5 means 6+ transactions, which is ineligible


# --------------------------
# QR Code Configuration
# --------------------------
QR_CODE_BASE_URL = "https://rtnsmart.com/rtnsmartapp/?USER_"
QR_CODE_BASE64_PATTERN = re.compile(r'^[A-Za-z0-9+/=]+$')


# --------------------------
# CID Customer ID Generation
# --------------------------
def generate_cid_customer_id(loyalty_id: str, format_type: str) -> str:
    """
    Generate a unique CID Customer ID for a customer.
    
    Strategy:
    - For phone numbers: Use phone number as CID Customer ID (normalized)
    - For QR codes: Generate UUID or hash-based ID (since QR codes are URLs)
    - Ensures uniqueness and persistence
    
    Args:
        loyalty_id: The loyalty ID (phone number or QR code URL)
        format_type: "PHONE_NUMBER" or "QR_CODE"
    
    Returns:
        str: Unique CID Customer ID
    """
    if format_type == "PHONE_NUMBER":
        # For phone numbers, use the phone number itself as CID Customer ID
        # This allows linking if same person uses different formats later
        return loyalty_id
    else:
        # For QR codes, generate a deterministic hash-based ID
        # This allows same QR code to always get same CID Customer ID
        # Using SHA256 hash (first 16 chars for readability)
        hash_obj = hashlib.sha256(loyalty_id.encode('utf-8'))
        return f"CID_{hash_obj.hexdigest()[:16].upper()}"


def get_or_create_cid_customer_id(loyalty_id: str, format_type: str, conn: sqlite3.Connection) -> str:
    """
    Get existing CID Customer ID or create new one for a customer.
    
    This function:
    1. Checks if customer already has a CID Customer ID
    2. If not, generates one based on format type
    3. For phone numbers: tries to find existing CID Customer ID if same phone was used
    4. Returns the CID Customer ID
    
    Args:
        loyalty_id: The loyalty ID
        format_type: "PHONE_NUMBER" or "QR_CODE"
        conn: Database connection
    
    Returns:
        str: CID Customer ID
    """
    cursor = conn.cursor()
    
    # Check if customer already has CID Customer ID
    cursor.execute("SELECT cid_customer_id FROM customer_profiles WHERE loyalty_id = ?", (loyalty_id,))
    row = cursor.fetchone()
    
    if row and row[0]:
        return row[0]
    
    # Generate new CID Customer ID
    cid_customer_id = generate_cid_customer_id(loyalty_id, format_type)
    
    # For phone numbers, check if this CID Customer ID already exists (same phone used before)
    if format_type == "PHONE_NUMBER":
        cursor.execute("SELECT loyalty_id FROM customer_profiles WHERE cid_customer_id = ?", (cid_customer_id,))
        existing = cursor.fetchone()
        if existing:
            # Same phone number already has this CID Customer ID, reuse it
            return cid_customer_id
    
    # For QR codes or new phone numbers, ensure uniqueness
    # Check if generated CID Customer ID already exists
    cursor.execute("SELECT loyalty_id FROM customer_profiles WHERE cid_customer_id = ?", (cid_customer_id,))
    existing = cursor.fetchone()
    
    if existing:
        # CID Customer ID collision (rare), generate UUID-based one
        cid_customer_id = f"CID_{uuid.uuid4().hex[:16].upper()}"
    
    return cid_customer_id


# --------------------------
# Database Helper Functions
# --------------------------
def get_db_connection():
    """Get SQLite database connection with timeout for concurrent access"""
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(f"Database file '{DB_FILE}' not found. Please run 'python init_database.py' first.")
    conn = sqlite3.connect(DB_FILE, timeout=10.0)  # 10 second timeout for concurrent access
    return conn


def init_db_if_needed():
    """Initialize database if it doesn't exist"""
    if not os.path.exists(DB_FILE):
        # Try to run init_database.py
        import subprocess
        import sys
        try:
            subprocess.run([sys.executable, 'init_database.py'], check=True, timeout=30)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize database: {e}")


# --------------------------
# QR Code Validation Helper Functions
# --------------------------
def is_qr_code_format(loyalty_id: str) -> bool:
    """Check if loyalty_id is a QR code format (RTNSmart URL)"""
    return loyalty_id.startswith(QR_CODE_BASE_URL)


def validate_qr_code(loyalty_id: str) -> tuple:
    """
    Validate QR code format.
    
    Args:
        loyalty_id: The loyalty ID to validate
        
    Returns:
        tuple: (is_valid, reason, encoded_parameter)
        - is_valid: True if QR code format is valid
        - reason: Error message if invalid, empty if valid
        - encoded_parameter: The Base64 encoded parameter if valid, None otherwise
    """
    # Check base URL
    if not loyalty_id.startswith(QR_CODE_BASE_URL):
        # return False, f"LoyaltyID QR code format invalid: invalid base URL (expected '{QR_CODE_BASE_URL}', got '{loyalty_id[:50]}...')", None
        return False, f"LoyaltyID QR code format invalid: invalid base URL (expected '{QR_CODE_BASE_URL}', got '{loyalty_id}...')", None
    
    # Extract encoded parameter (everything after "USER_")
    encoded_param = loyalty_id[len(QR_CODE_BASE_URL):]
    
    if not encoded_param:
        return False, f"LoyaltyID QR code format invalid: missing encoded parameter (full URL: '{loyalty_id}')", None
    
    # Validate Base64 format (alphanumeric, +, /, = characters only)
    if not QR_CODE_BASE64_PATTERN.match(encoded_param):
        return False, f"LoyaltyID QR code format invalid: encoded parameter contains invalid characters (must be Base64). Encoded param: '{encoded_param}'", None
    
    # Check reasonable length (Base64 encoded strings are typically 20-60 chars)
    # Made more lenient: minimum 1 char (was 10), maximum 500 (was 200) to handle edge cases
    if len(encoded_param) < 1 or len(encoded_param) > 500:
        return False, f"LoyaltyID QR code format invalid: encoded parameter length {len(encoded_param)} out of expected range (1-500 chars). Encoded param: '{encoded_param}'", None
    
    return True, "", encoded_param


def is_phone_number_format(loyalty_id: str) -> bool:
    """Check if loyalty_id is a phone number format (10-12 digits)"""
    return bool(re.match(r'^[0-9]{10,12}$', loyalty_id))


def validate_phone_number(loyalty_id: str) -> tuple:
    """
    Validate phone number format.
    
    Args:
        loyalty_id: The loyalty ID to validate
        
    Returns:
        tuple: (is_valid, reason)
        - is_valid: True if phone number format is valid
        - reason: Error message if invalid, empty if valid
    """
    # Check length: 10-12 digits
    if len(loyalty_id) < 10 or len(loyalty_id) > 12:
        return False, f"LoyaltyID format invalid: length {len(loyalty_id)} not in range [10, 12]"
    
    # Check characters: numeric only
    if not re.match(r'^[0-9]+$', loyalty_id):
        return False, "LoyaltyID contains invalid characters (only digits 0-9 allowed)"
    
    return True, ""


def is_driver_license_format(loyalty_id: str) -> bool:
    """Check if loyalty_id is a driver license format (alphanumeric, typically 6-20 characters)"""
    # Driver license format varies by state, but generally alphanumeric
    # Common patterns: 6-20 alphanumeric characters
    return bool(re.match(r'^[A-Za-z0-9]{6,20}$', loyalty_id))


def validate_driver_license(loyalty_id: str) -> tuple:
    """
    Validate driver license format.
    
    Args:
        loyalty_id: The loyalty ID to validate
        
    Returns:
        tuple: (is_valid, reason)
        - is_valid: True if driver license format is valid
        - reason: Error message if invalid, empty if valid
    """
    # Check length: 6-20 characters (varies by state)
    if len(loyalty_id) < 6 or len(loyalty_id) > 20:
        return False, f"Driver license format invalid: length {len(loyalty_id)} not in range [6, 20]"
    
    # Check characters: alphanumeric only
    if not re.match(r'^[A-Za-z0-9]+$', loyalty_id):
        return False, "Driver license contains invalid characters (only alphanumeric A-Z, a-z, 0-9 allowed)"
    
    return True, ""


# --------------------------
# Validation Function
# --------------------------
def validate_loyalty_id(
    loyalty_id: str, 
    store_id: Optional[str] = None,
    logger: Optional[Callable[[str], None]] = None
) -> Dict:
    """
    Step 1: Validate the Loyalty ID (CID/LID) per Tier 3 requirements.
    
    Args:
        loyalty_id: The loyalty ID to validate
        store_id: Optional store ID for context
        logger: Optional logging function (if None, no logging)
    
    Returns dict with:
    - valid: bool - Is the LID valid format and eligible?
    - eligible_for_tier3: bool - Can receive Tier 3 benefits?
    - eligible_for_cid_fund: bool - Can earn CID promotional fund?
    - reason: str - Reason for validation result
    - is_manager_card: bool - Detected as manager/store card?
    - daily_count: int - Number of transactions today
    """
    def log(msg: str):
        if logger:
            logger(msg)
    
    result = {
        "valid": False,
        "eligible_for_tier3": False,
        "eligible_for_cid_fund": False,
        "reason": "",
        "is_manager_card": False,
        "daily_count": 0
    }
    
    # Rule: If LoyaltyID is missing → return "No loyalty" response (no Tier 3 benefits)
    if not loyalty_id or not loyalty_id.strip():
        result["reason"] = "LoyaltyID is missing"
        log(f"validate_loyalty_id: {result['reason']}")
        return result
    
    loyalty_id = loyalty_id.strip()
    today = datetime.now().date()
    
    log(f"validate_loyalty_id: ========== START VALIDATION ==========")
    log(f"validate_loyalty_id: Input loyalty_id='{loyalty_id}' (length: {len(loyalty_id)})")
    log(f"validate_loyalty_id: QR_CODE_BASE_URL='{QR_CODE_BASE_URL}'")
    
    # Rule 2: Determine Loyalty ID Format and Validate
    format_type = None
    normalized_loyalty_id = loyalty_id  # Store the full ID for tracking
    
    # Check if it's a QR code format
    is_qr = is_qr_code_format(loyalty_id)
    log(f"validate_loyalty_id: is_qr_code_format() returned: {is_qr}")
    
    if is_qr:
        format_type = "QR_CODE"
        log(f"validate_loyalty_id: QR code format detected, validating...")
        is_valid_qr, qr_reason, encoded_param = validate_qr_code(loyalty_id)
        
        log(f"validate_loyalty_id: QR validation result: is_valid={is_valid_qr}, reason='{qr_reason}'")
        if encoded_param:
            log(f"validate_loyalty_id: Encoded parameter extracted: '{encoded_param}' (length: {len(encoded_param)})")
        else:
            log(f"validate_loyalty_id: No encoded parameter extracted")
        
        if not is_valid_qr:
            result["reason"] = qr_reason
            log(f"validate_loyalty_id: ❌ QR code validation FAILED: {result['reason']}")
            return result
        
        # QR code is valid, use full URL as normalized_loyalty_id
        normalized_loyalty_id = loyalty_id
        log(f"validate_loyalty_id: ✅ QR code format detected and validated | Encoded param length: {len(encoded_param) if encoded_param else 0}")
    
    # Check if it's a phone number format
    elif is_phone_number_format(loyalty_id):
        format_type = "PHONE_NUMBER"
        is_valid_phone, phone_reason = validate_phone_number(loyalty_id)
        
        if not is_valid_phone:
            result["reason"] = phone_reason
            log(f"validate_loyalty_id: {result['reason']}")
            return result
        
        # Phone number is valid, use as normalized_loyalty_id
        normalized_loyalty_id = loyalty_id
        log(f"validate_loyalty_id: Phone number format detected and validated")
    
    # Check if it's a driver license format
    elif is_driver_license_format(loyalty_id):
        format_type = "DRIVER_LICENSE"
        is_valid_dl, dl_reason = validate_driver_license(loyalty_id)
        
        if not is_valid_dl:
            result["reason"] = dl_reason
            log(f"validate_loyalty_id: {result['reason']}")
            return result
        
        # Driver license is valid, use as normalized_loyalty_id
        normalized_loyalty_id = loyalty_id
        log(f"validate_loyalty_id: Driver license format detected and validated")
    
    # Neither QR code, phone number, nor driver license format
    else:
        result["reason"] = "LoyaltyID format unrecognized (must be phone number, RTNSmart QR code, or driver license)"
        log(f"validate_loyalty_id: {result['reason']}")
        return result
    
    # Track daily transaction count for fraud detection (using database)
    # NOTE: We track daily counts but DO NOT create/update customer_profiles
    # Customer profiles are created/updated by RTN app only
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get or create daily transaction count (for manager card detection)
        cursor.execute("""
            INSERT INTO daily_transaction_counts (loyalty_id, transaction_date, count)
            VALUES (?, ?, 1)
            ON CONFLICT(loyalty_id, transaction_date) 
            DO UPDATE SET count = count + 1, updated_at = CURRENT_TIMESTAMP
        """, (normalized_loyalty_id, today))
        
        # Get the current count
        cursor.execute("""
            SELECT count FROM daily_transaction_counts
            WHERE loyalty_id = ? AND transaction_date = ?
        """, (normalized_loyalty_id, today))
        
        row = cursor.fetchone()
        daily_count = row[0] if row else 1
        result["daily_count"] = daily_count
        
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"validate_loyalty_id: Database error getting daily count: {e}")
        # Fallback: use 1 as default (shouldn't happen in production)
        daily_count = 1
        result["daily_count"] = daily_count
    
    # Check if it's a "store card/manager card" (high-frequency fraud control)
    # Per AGDC DTP: LIDs appearing in 6+ transactions in single day are ineligible
    if daily_count > DAILY_TRANSACTION_CAP:
        result["is_manager_card"] = True
        result["eligible_for_cid_fund"] = False
        result["reason"] = f"Manager/store card detected: {daily_count} transactions today (exceeds cap of {DAILY_TRANSACTION_CAP})"
        log(f"validate_loyalty_id: {loyalty_id} - {result['reason']}")
        # Still valid for basic Tier 3, but not for CID funds
        result["valid"] = True
        result["eligible_for_tier3"] = True
        
        # Log validation result (but DO NOT create/update customer_profiles - RTN app does that)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO loyalty_validation_log 
                (loyalty_id, store_id, valid, eligible_for_tier3, eligible_for_cid_fund, 
                 is_manager_card, daily_count, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                normalized_loyalty_id, store_id,
                1 if result["valid"] else 0,
                1 if result["eligible_for_tier3"] else 0,
                1 if result["eligible_for_cid_fund"] else 0,
                1 if result["is_manager_card"] else 0,
                daily_count,
                result["reason"]
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            log(f"validate_loyalty_id: Database error logging validation: {e}")
        
        return result
    
    # Daily count is within cap (1-5 transactions), so eligible for CID funds
    # Per AGDC DTP: 6+ transactions per day makes it ineligible (already handled above)
    result["eligible_for_cid_fund"] = True
    result["reason"] = "LoyaltyID valid and eligible"
    
    # Valid LID format and within daily cap
    result["valid"] = True
    result["eligible_for_tier3"] = True
    
    # Log validation result (but DO NOT create/update customer_profiles - RTN app does that)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO loyalty_validation_log 
            (loyalty_id, store_id, valid, eligible_for_tier3, eligible_for_cid_fund, 
             is_manager_card, daily_count, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            normalized_loyalty_id, store_id,
            1 if result["valid"] else 0,
            1 if result["eligible_for_tier3"] else 0,
            1 if result["eligible_for_cid_fund"] else 0,
            1 if result["is_manager_card"] else 0,
            daily_count,
            result["reason"]
        ))
        
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"validate_loyalty_id: Database error logging validation: {e}")
        # Continue execution even if logging fails
    
    log(f"validate_loyalty_id: {loyalty_id} - {result['reason']} | Daily count: {daily_count} | CID eligible: {result['eligible_for_cid_fund']}")
    
    return result


# --------------------------
# Cleanup Function
# --------------------------
def cleanup_old_daily_counts(logger: Optional[Callable[[str], None]] = None):
    """
    Cleanup old daily transaction counts (older than 7 days) to prevent database growth.
    Should be called periodically or on startup.
    
    Args:
        logger: Optional logging function (if None, no logging)
    """
    def log(msg: str):
        if logger:
            logger(msg)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete records older than 7 days
        cutoff_date = datetime.now().date() - timedelta(days=7)
        cursor.execute("""
            DELETE FROM daily_transaction_counts 
            WHERE transaction_date < ?
        """, (cutoff_date,))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        log(f"cleanup_old_daily_counts: Cleaned up {deleted_count} old daily transaction count records")
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            log(f"cleanup_old_daily_counts: Database locked (another process may be using it) - skipping cleanup")
        else:
            log(f"cleanup_old_daily_counts: Database error: {e}")
    except Exception as e:
        log(f"cleanup_old_daily_counts: Database error: {e}")


# --------------------------
# Getter Functions (for external access to data)
# --------------------------
def get_daily_transaction_count(loyalty_id: str) -> int:
    """Get today's transaction count for a loyalty ID from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        today = datetime.now().date()
        
        cursor.execute("""
            SELECT count FROM daily_transaction_counts
            WHERE loyalty_id = ? AND transaction_date = ?
        """, (loyalty_id, today))
        
        row = cursor.fetchone()
        conn.close()
        
        return row[0] if row else 0
    except Exception:
        return 0


def get_customer_profile(loyalty_id: str) -> Optional[Dict]:
    """Get customer profile for a loyalty ID from database"""
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row  # Enable column access by name
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM customer_profiles WHERE loyalty_id = ?
        """, (loyalty_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    except Exception:
        return None


def is_manager_card(loyalty_id: str) -> bool:
    """Check if a loyalty ID is currently flagged as a manager/store card"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        today = datetime.now().date()
        
        # Check daily count
        cursor.execute("""
            SELECT count FROM daily_transaction_counts
            WHERE loyalty_id = ? AND transaction_date = ?
        """, (loyalty_id, today))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return row[0] > DAILY_TRANSACTION_CAP
        return False
    except Exception:
        return False