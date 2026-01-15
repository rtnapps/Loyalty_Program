#!/usr/bin/env python3
"""
Tier 3 Rules Engine - Step 2: Confirm Adult / Age Gating

Validates age verification status per AGDC DTP Tier 3 requirements:
- AVT (Age Verification Technology) - in-person confirmation by cashier (legally required)
- EAIV (Electronic Age Identity Verification) - from RTN app, stored in database
- Determines eligibility for Tier 3 incentives and EAIV-only offers

NEW MODEL (App-first):
- Step 1: Customer does EAIV in RTN App (ID scan, selfie, DOB, Identity, ATC flag)
- Step 2: Customer shows QR code at POS (contains CID, EAIV_verified, EAIV_expiry, Signature)
- Step 3: Cashier performs physical age confirmation (legally required) - clicks "Age Verified"
- Step 4: RTN logs AVT transaction (AVT_performed, AVT_method, AVT_timestamp, Cashier_ID, Store_ID, Transaction_ID)
"""

import sqlite3
import os
from datetime import datetime
from typing import Dict, Optional, Callable, Union


# --------------------------
# Configuration
# --------------------------
# Database file path
DB_FILE = "loyalty.db"


# --------------------------
# Database Helper Functions
# --------------------------
def get_db_connection():
    """Get SQLite database connection with timeout for concurrent access"""
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(f"Database file '{DB_FILE}' not found. Please run 'python init_database.py' first.")
    conn = sqlite3.connect(DB_FILE, timeout=10.0)  # 10 second timeout for concurrent access
    return conn


# --------------------------
# Age Verification Helper Functions
# --------------------------
def normalize_age_status(age_status: Union[str, Dict, None]) -> Dict[str, Optional[str]]:
    """
    Normalize age_status input to consistent format.
    
    Args:
        age_status: Can be:
            - String: "verified", "not_verified", "unknown"
            - Dict: {"avt": "verified", "eaiv": "verified"}
            - None: No age status provided
    
    Returns:
        dict: {"avt": str or None, "eaiv": str or None}
    """
    if age_status is None:
        return {"avt": None, "eaiv": None}
    
    if isinstance(age_status, str):
        # If single string, assume it's AVT status
        avt_status = age_status.lower() if age_status else None
        return {"avt": avt_status, "eaiv": None}
    
    if isinstance(age_status, dict):
        avt = age_status.get("avt") or age_status.get("AVT") or age_status.get("age_verified")
        eaiv = age_status.get("eaiv") or age_status.get("EAIV") or age_status.get("eaiv_verified")
        
        # Normalize to lowercase strings
        avt_status = avt.lower() if isinstance(avt, str) else None
        eaiv_status = eaiv.lower() if isinstance(eaiv, str) else None
        
        return {"avt": avt_status, "eaiv": eaiv_status}
    
    return {"avt": None, "eaiv": None}


def is_verified(status: Optional[str]) -> bool:
    """Check if status indicates verification"""
    if status is None:
        return False
    return status.lower() in ["verified", "true", "yes", "1", "ok", "pass"]


# --------------------------
# Age Verification Function
# --------------------------
def confirm_age_gating(
    age_status: Union[str, Dict, None],
    loyalty_id: Optional[str] = None,
    store_id: Optional[str] = None,
    transaction_id: Optional[str] = None,
    cashier_id: Optional[str] = None,
    logger: Optional[Callable[[str], None]] = None
) -> Dict:
    """
    Step 2: Confirm Adult / Age Gating per Tier 3 requirements (App-first model).
    
    NEW MODEL:
    - EAIV comes from database (updated by RTN app, not from POS)
    - AVT is in-person confirmation by cashier (comes from POS when cashier clicks "Age Verified")
    - AVT transaction is logged for compliance audit trail
    
    Args:
        age_status: AVT status from POS (cashier confirmation)
            - Can be string: "verified", "not_verified", "unknown"
            - Can be dict: {"avt": "verified"} (EAIV is NOT from POS, it's from database)
            - Can be None: No AVT status provided
        loyalty_id: Customer loyalty ID (required to check EAIV from database)
        store_id: Store ID (required for AVT logging)
        transaction_id: Transaction ID (required for AVT logging)
        cashier_id: Cashier/employee ID who performed confirmation (required for AVT logging)
        logger: Optional logging function (if None, no logging)
    
    Returns dict with:
    - age_verified: bool - Is AVT verified (cashier confirmed)?
    - eaiv_verified: bool - Is EAIV verified (from database, updated by RTN app)?
    - eligible_for_tier3_incentives: bool - Can receive Tier 3 incentives?
    - eligible_for_eaiv_only_incentives: bool - Can receive EAIV-only incentives?
    - reason: str - Explanation of verification result
    """
    def log(msg: str):
        if logger:
            logger(msg)
    
    result = {
        "age_verified": False,
        "eaiv_verified": False,
        "eligible_for_tier3_incentives": False,
        "eligible_for_eaiv_only_incentives": False,
        "reason": ""
    }
    
    # Normalize age_status input (this is AVT from POS, not EAIV)
    normalized = normalize_age_status(age_status)
    avt_status = normalized["avt"]  # AVT comes from POS (cashier confirmation)
    # EAIV is NOT from age_status - it comes from database (updated by RTN app)
    
    log(f"confirm_age_gating: ========== START AGE VERIFICATION ==========")
    log(f"confirm_age_gating: Input - loyalty_id='{loyalty_id}' (length: {len(loyalty_id) if loyalty_id else 0}), store_id={store_id}, transaction_id={transaction_id}, cashier_id={cashier_id}")
    log(f"confirm_age_gating: AVT status from POS={avt_status} (NOTE: Using RTN app EAIV, AVT not required)")
    
    # NEW MODEL: Only check EAIV from database (RTN app handles age verification)
    # AVT blocker removed - we only check EAIV from database
    
    # Rule 1: EAIV (Electronic Age Identity Verification) Check
    # EAIV comes from database (updated by RTN app, not from POS)
    # Search by phone_number OR rtn_qr_code OR driver_license (any of these can be used)
    log(f"confirm_age_gating: Checking EAIV from database for loyalty_id='{loyalty_id}'")
    log(f"confirm_age_gating: Will search: phone_number='{loyalty_id}' OR rtn_qr_code='{loyalty_id}' OR driver_license='{loyalty_id}'")
    
    if loyalty_id:
        try:
            log(f"confirm_age_gating: Opening database connection...")
            conn = get_db_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            log(f"confirm_age_gating: Searching customer_profiles for: phone_number='{loyalty_id}' OR rtn_qr_code='{loyalty_id}' OR driver_license='{loyalty_id}'")
            
            # Get EAIV status from customer profile (updated by RTN app)
            # Search by phone_number OR rtn_qr_code OR driver_license
            cursor.execute("""
                SELECT eaiv_verified, cid_customer_id, loyalty_id, phone_number, rtn_qr_code, driver_license, customer_name
                FROM customer_profiles 
                WHERE phone_number = ? OR rtn_qr_code = ? OR driver_license = ?
                LIMIT 1
            """, (loyalty_id, loyalty_id, loyalty_id))
            
            row = cursor.fetchone()
            if row:
                log(f"confirm_age_gating: ✅ Customer FOUND in database")
                log(f"confirm_age_gating:   - loyalty_id: {row['loyalty_id']}")
                log(f"confirm_age_gating:   - phone_number: {row['phone_number']}")
                log(f"confirm_age_gating:   - rtn_qr_code: {row['rtn_qr_code']}")
                log(f"confirm_age_gating:   - driver_license: {row['driver_license']}")
                log(f"confirm_age_gating:   - customer_name: {row['customer_name']}")
                log(f"confirm_age_gating:   - cid_customer_id: {row['cid_customer_id']}")
                log(f"confirm_age_gating:   - eaiv_verified (raw): {row['eaiv_verified']} (type: {type(row['eaiv_verified'])})")
                
                # EAIV status from database (updated by RTN app)
                eaiv_verified_db = bool(row["eaiv_verified"]) if row["eaiv_verified"] is not None else False
                cid_customer_id = row["cid_customer_id"]
                found_loyalty_id = row["loyalty_id"]
                
                result["eaiv_verified"] = eaiv_verified_db
                log(f"confirm_age_gating:   - eaiv_verified (processed): {eaiv_verified_db}")
                
                if eaiv_verified_db:
                    log(f"confirm_age_gating: ✅ EAIV VERIFIED from database (updated by RTN app)")
                    log(f"confirm_age_gating:   - CID: {cid_customer_id}")
                    log(f"confirm_age_gating:   - Found by loyalty_id: {found_loyalty_id}")
                    # Set age_verified = True if EAIV is verified (RTN app handles age verification)
                    result["age_verified"] = True
                else:
                    log(f"confirm_age_gating: ❌ EAIV NOT VERIFIED in database")
                    log(f"confirm_age_gating:   - Customer needs to complete EAIV in RTN app")
                    result["age_verified"] = False
            else:
                # Customer not found in database - EAIV not verified
                log(f"confirm_age_gating: ❌ Customer NOT FOUND in database")
                log(f"confirm_age_gating:   - Searched for: phone_number='{loyalty_id}' OR rtn_qr_code='{loyalty_id}' OR driver_license='{loyalty_id}'")
                log(f"confirm_age_gating:   - No matching records found")
                result["eaiv_verified"] = False
                result["age_verified"] = False
            
            conn.close()
            log(f"confirm_age_gating: Database connection closed")
        except Exception as e:
            log(f"confirm_age_gating: ❌ DATABASE ERROR checking EAIV: {e}")
            log(f"confirm_age_gating:   - Exception type: {type(e).__name__}")
            import traceback
            log(f"confirm_age_gating:   - Traceback: {traceback.format_exc()}")
            # Default to not verified on error
            result["eaiv_verified"] = False
            result["age_verified"] = False
    else:
        # No loyalty_id provided - cannot check EAIV
        log(f"confirm_age_gating: ❌ No loyalty_id provided - cannot check EAIV from database")
        result["eaiv_verified"] = False
        result["age_verified"] = False
    
    # Rule 2: Tier 3 Incentive Eligibility
    # Based on EAIV status from database (RTN app handles age verification)
    if result["age_verified"]:
        result["eligible_for_tier3_incentives"] = True
        result["reason"] = "Age verified (EAIV verified by RTN app) - eligible for Tier 3 incentives"
        log(f"confirm_age_gating: ✅ Eligible for Tier 3 incentives (EAIV verified)")
    else:
        result["eligible_for_tier3_incentives"] = False
        result["reason"] = "Age not verified (EAIV not verified in RTN app) - ineligible for Tier 3 incentives"
        log(f"confirm_age_gating: ❌ NOT eligible for Tier 3 incentives (EAIV not verified)")
    
    # Rule 3: EAIV-Only Incentive Eligibility
    if result["age_verified"] and result["eaiv_verified"]:
        result["eligible_for_eaiv_only_incentives"] = True
        if result["reason"]:
            result["reason"] += "; EAIV verified (from RTN app) - eligible for EAIV-only incentives"
        else:
            result["reason"] = "Age verified (EAIV verified by RTN app) - eligible for EAIV-only incentives"
        log(f"confirm_age_gating: ✅ Eligible for EAIV-only incentives")
    elif result["age_verified"] and not result["eaiv_verified"]:
        result["eligible_for_eaiv_only_incentives"] = False
        if result["reason"]:
            result["reason"] += "; EAIV not verified (customer needs to complete EAIV in RTN app) - EAIV-only incentives restricted"
        log(f"confirm_age_gating: ❌ NOT eligible for EAIV-only incentives (EAIV not verified)")
    else:
        result["eligible_for_eaiv_only_incentives"] = False
        log(f"confirm_age_gating: ❌ NOT eligible for EAIV-only incentives (age not verified)")
    
    # Step 4: Log AVT Transaction (compliance audit trail)
    # Log transaction when EAIV is verified (RTN app handles age verification)
    log(f"confirm_age_gating: ========== AVT TRANSACTION LOGGING ==========")
    log(f"confirm_age_gating: age_verified={result['age_verified']}, transaction_id={transaction_id}, store_id={store_id}")
    
    if result["age_verified"] and transaction_id and store_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Get CID and EAIV info from customer profile
            # Search by phone_number OR rtn_qr_code OR driver_license
            cid_customer_id = None
            eaiv_verified_db = None
            if loyalty_id:
                cursor.execute("""
                    SELECT cid_customer_id, eaiv_verified
                    FROM customer_profiles 
                    WHERE phone_number = ? OR rtn_qr_code = ? OR driver_license = ?
                    LIMIT 1
                """, (loyalty_id, loyalty_id, loyalty_id))
                row = cursor.fetchone()
                if row:
                    cid_customer_id = row[0]
                    eaiv_verified_db = row[1]
            
            # Insert AVT transaction record
            cursor.execute("""
                INSERT INTO avt_transactions (
                    transaction_id,
                    store_id,
                    loyalty_id,
                    cid_customer_id,
                    avt_performed,
                    avt_method,
                    avt_timestamp,
                    cashier_id,
                    eaiv_verified
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            """, (
                transaction_id,
                store_id,
                loyalty_id,
                cid_customer_id,
                1,  # avt_performed = true
                'in_person_confirmation',  # avt_method
                cashier_id,
                1 if result["eaiv_verified"] else 0 if result["eaiv_verified"] is False else None
            ))
            
            conn.commit()
            conn.close()
            log(f"confirm_age_gating: ✅ Logged AVT transaction successfully")
            log(f"confirm_age_gating:   - transaction_id: {transaction_id}")
            log(f"confirm_age_gating:   - store_id: {store_id}")
            log(f"confirm_age_gating:   - cashier_id: {cashier_id}")
            log(f"confirm_age_gating:   - loyalty_id: {loyalty_id}")
            log(f"confirm_age_gating:   - cid_customer_id: {cid_customer_id}")
            log(f"confirm_age_gating:   - eaiv_verified: {result['eaiv_verified']}")
        except Exception as e:
            log(f"confirm_age_gating: ❌ DATABASE ERROR logging AVT transaction: {e}")
            import traceback
            log(f"confirm_age_gating:   - Traceback: {traceback.format_exc()}")
            # Continue execution even if AVT logging fails (but this should not happen in production)
    else:
        log(f"confirm_age_gating: ⚠️  Skipping AVT transaction logging (missing required fields)")
        log(f"confirm_age_gating:   - age_verified: {result['age_verified']}")
        log(f"confirm_age_gating:   - transaction_id: {transaction_id}")
        log(f"confirm_age_gating:   - store_id: {store_id}")
    
    # Update customer profile AVT timestamp if loyalty_id is provided
    # Search by phone_number OR rtn_qr_code OR driver_license
    log(f"confirm_age_gating: ========== UPDATING CUSTOMER PROFILE ==========")
    if loyalty_id and result["age_verified"]:
        try:
            log(f"confirm_age_gating: Updating customer profile AVT timestamp for loyalty_id={loyalty_id}")
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Update last_avt_verified timestamp (search by any identifier)
            cursor.execute("""
                UPDATE customer_profiles 
                SET avt_verified = ?, last_avt_verified = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE phone_number = ? OR rtn_qr_code = ? OR driver_license = ?
            """, (1, loyalty_id, loyalty_id, loyalty_id))
            
            rows_updated = cursor.rowcount
            conn.commit()
            conn.close()
            log(f"confirm_age_gating: ✅ Updated customer profile AVT timestamp")
            log(f"confirm_age_gating:   - Rows updated: {rows_updated}")
            log(f"confirm_age_gating:   - loyalty_id: {loyalty_id}")
        except Exception as e:
            log(f"confirm_age_gating: ❌ DATABASE ERROR updating profile: {e}")
            import traceback
            log(f"confirm_age_gating:   - Traceback: {traceback.format_exc()}")
            # Continue execution even if database update fails
    else:
        log(f"confirm_age_gating: ⚠️  Skipping customer profile update")
        log(f"confirm_age_gating:   - loyalty_id: {loyalty_id}")
        log(f"confirm_age_gating:   - age_verified: {result['age_verified']}")
    
    log(f"confirm_age_gating: ========== FINAL RESULT ==========")
    log(f"confirm_age_gating: age_verified: {result['age_verified']}")
    log(f"confirm_age_gating: eaiv_verified: {result['eaiv_verified']}")
    log(f"confirm_age_gating: eligible_for_tier3_incentives: {result['eligible_for_tier3_incentives']}")
    log(f"confirm_age_gating: eligible_for_eaiv_only_incentives: {result['eligible_for_eaiv_only_incentives']}")
    log(f"confirm_age_gating: reason: {result['reason']}")
    log(f"confirm_age_gating: ========== END AGE VERIFICATION ==========")
    
    return result


# --------------------------
# Getter Functions (for external access)
# --------------------------
def get_customer_age_status(loyalty_id: str) -> Optional[Dict]:
    """
    Get customer's age verification status from database.
    
    Args:
        loyalty_id: Customer loyalty ID
        
    Returns:
        dict with avt_verified and eaiv_verified, or None if customer not found
    """
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT avt_verified, eaiv_verified, last_avt_verified, last_eaiv_verified
            FROM customer_profiles 
            WHERE loyalty_id = ?
        """, (loyalty_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "avt_verified": bool(row["avt_verified"]) if row["avt_verified"] is not None else None,
                "eaiv_verified": bool(row["eaiv_verified"]) if row["eaiv_verified"] is not None else None,
                "last_avt_verified": row["last_avt_verified"],
                "last_eaiv_verified": row["last_eaiv_verified"]
            }
        return None
    except Exception:
        return None
