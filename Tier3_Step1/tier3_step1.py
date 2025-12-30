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
# Database Helper Functions
# --------------------------
def get_db_connection():
    """Get SQLite database connection"""
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(f"Database file '{DB_FILE}' not found. Please run 'python init_database.py' first.")
    return sqlite3.connect(DB_FILE)


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
        return False, "LoyaltyID QR code format invalid: invalid base URL", None
    
    # Extract encoded parameter (everything after "USER_")
    encoded_param = loyalty_id[len(QR_CODE_BASE_URL):]
    
    if not encoded_param:
        return False, "LoyaltyID QR code format invalid: missing encoded parameter", None
    
    # Validate Base64 format (alphanumeric, +, /, = characters only)
    if not QR_CODE_BASE64_PATTERN.match(encoded_param):
        return False, "LoyaltyID QR code format invalid: encoded parameter contains invalid characters (must be Base64)", None
    
    # Check reasonable length (Base64 encoded strings are typically 20-60 chars)
    if len(encoded_param) < 10 or len(encoded_param) > 200:
        return False, f"LoyaltyID QR code format invalid: encoded parameter length {len(encoded_param)} out of expected range", None
    
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
    
    # Rule 2: Determine Loyalty ID Format and Validate
    format_type = None
    normalized_loyalty_id = loyalty_id  # Store the full ID for tracking
    
    # Check if it's a QR code format
    if is_qr_code_format(loyalty_id):
        format_type = "QR_CODE"
        is_valid_qr, qr_reason, encoded_param = validate_qr_code(loyalty_id)
        
        if not is_valid_qr:
            result["reason"] = qr_reason
            log(f"validate_loyalty_id: {result['reason']}")
            return result
        
        # QR code is valid, use full URL as normalized_loyalty_id
        normalized_loyalty_id = loyalty_id
        log(f"validate_loyalty_id: QR code format detected and validated | Encoded param length: {len(encoded_param) if encoded_param else 0}")
    
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
    
    # Neither QR code nor phone number format
    else:
        result["reason"] = "LoyaltyID format unrecognized (must be phone number or RTNSmart QR code)"
        log(f"validate_loyalty_id: {result['reason']}")
        return result
    
    # Track daily transaction count for fraud detection (using database)
    # Use normalized_loyalty_id (full QR code URL or phone number) for tracking
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get or create daily transaction count
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
        
        # Update customer profile to mark as manager card
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if customer exists
            cursor.execute("SELECT loyalty_id FROM customer_profiles WHERE loyalty_id = ?", (normalized_loyalty_id,))
            exists = cursor.fetchone() is not None
            
            if not exists:
                # New customer - insert with manager card flag
                cursor.execute("""
                    INSERT INTO customer_profiles 
                    (loyalty_id, store_id, first_seen, last_seen, total_transactions, is_manager_card, format_type)
                    VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1, ?)
                """, (normalized_loyalty_id, store_id, format_type))
            else:
                # Existing customer - update
                cursor.execute("""
                    UPDATE customer_profiles 
                    SET last_seen = CURRENT_TIMESTAMP,
                        total_transactions = total_transactions + 1,
                        is_manager_card = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE loyalty_id = ?
                """, (normalized_loyalty_id,))
            
            # Log validation result
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
            log(f"validate_loyalty_id: Database error updating manager card: {e}")
        
        return result
    
    # Daily count is within cap (1-5 transactions), so eligible for CID funds
    # Per AGDC DTP: 6+ transactions per day makes it ineligible (already handled above)
    result["eligible_for_cid_fund"] = True
    result["reason"] = "LoyaltyID valid and eligible"
    
    # Valid LID format and within daily cap
    result["valid"] = True
    result["eligible_for_tier3"] = True
    
    # Update customer profile in database
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if customer exists
        cursor.execute("SELECT loyalty_id FROM customer_profiles WHERE loyalty_id = ?", (normalized_loyalty_id,))
        exists = cursor.fetchone() is not None
        
        if not exists:
            # New customer - insert record
            cursor.execute("""
                INSERT INTO customer_profiles 
                (loyalty_id, store_id, first_seen, last_seen, total_transactions, is_manager_card, format_type)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, ?, ?)
            """, (normalized_loyalty_id, store_id, 1 if result["is_manager_card"] else 0, format_type))
            log(f"validate_loyalty_id: New customer added to database: {normalized_loyalty_id} (format: {format_type})")
        else:
            # Existing customer - update last_seen and increment total_transactions
            cursor.execute("""
                UPDATE customer_profiles 
                SET last_seen = CURRENT_TIMESTAMP,
                    total_transactions = total_transactions + 1,
                    is_manager_card = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE loyalty_id = ?
            """, (1 if result["is_manager_card"] else 0, normalized_loyalty_id))
        
        # Log validation result
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
        log(f"validate_loyalty_id: Database error updating profile: {e}")
        # Continue execution even if database update fails
    
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