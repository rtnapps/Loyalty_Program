================================================================================
STEP 1: VALIDATE THE LOYALTY ID (CID/LID)
================================================================================

LOYALTY ID FORMATS:
1. Phone Number Format: 10-12 digits (numeric only)
   Example: 5551239876, 15551239876
   
2. QR Code Format: RTNSmart QR Code URL
   Format: https://rtnsmart.com/rtnsmartapp/?USER_<encoded_parameter>
   Example: https://rtnsmart.com/rtnsmartapp/?USER_NU5LK3RqSEJRZWZXMmNtY1k0ME5hZz09
   - Base URL must match: https://rtnsmart.com/rtnsmartapp/?USER_
   - Encoded parameter: Base64 encoded string (alphanumeric, +, /, =)
   - Full URL length: Variable (typically 60-100 characters)

VALIDATION PRIORITY:
- If both phone number and QR code are provided, QR code takes precedence
- QR code customers are considered valid loyalty customers (same as phone number)
- Both formats follow the same daily transaction limits and manager card detection

================================================================================
VALIDATION RULES
================================================================================

Rule 1: Missing LID
    IF loyalty_id is None, empty, or whitespace-only
    THEN:
        - valid = False
        - eligible_for_tier3 = False
        - eligible_for_cid_fund = False
        - reason = "LoyaltyID is missing"
        - Return early (no Tier 3 benefits)

Rule 2: Determine Loyalty ID Format
    IF loyalty_id starts with "https://rtnsmart.com/rtnsmartapp/?USER_"
    THEN:
        - Format type = "QR_CODE"
        - Extract encoded parameter (everything after "USER_")
        - Validate QR code format (Rule 2.1)
    ELSE IF loyalty_id matches ^[0-9]{10,12}$
    THEN:
        - Format type = "PHONE_NUMBER"
        - Validate phone number format (Rule 2.2)
    ELSE:
        - valid = False
        - eligible_for_tier3 = False
        - eligible_for_cid_fund = False
        - reason = "LoyaltyID format unrecognized (must be phone number or RTNSmart QR code)"
        - Return early (no Tier 3 benefits)

Rule 2.1: QR Code Format Validation
    IF format type = "QR_CODE"
    THEN:
        - Check base URL: Must be exactly "https://rtnsmart.com/rtnsmartapp/?USER_"
        - Extract encoded_parameter (after "USER_")
        - Check encoded_parameter format:
          * Must be Base64 encoded (alphanumeric, +, /, = characters only)
          * Must match pattern: ^[A-Za-z0-9+/=]+$
          * Length: Typically 20-60 characters
        - IF base URL invalid OR encoded_parameter format invalid
        THEN:
            - valid = False
            - eligible_for_tier3 = False
            - eligible_for_cid_fund = False
            - reason = "LoyaltyID QR code format invalid: invalid URL or encoded parameter"
            - Return early (no Tier 3 benefits)
        - ELSE:
            - Store full QR code URL as normalized_loyalty_id for tracking
            - Continue to Rule 4 (Daily Transaction Tracking)

Rule 2.2: Phone Number Format Validation
    IF format type = "PHONE_NUMBER"
    THEN:
        - Check length: Must be 10-12 digits
        - IF length < 10 OR length > 12
        THEN:
            - valid = False
            - eligible_for_tier3 = False
            - eligible_for_cid_fund = False
            - reason = "LoyaltyID format invalid: length X not in range [10, 12]"
            - Return early (no Tier 3 benefits)
        - Check characters: Must be numeric only (0-9)
        - IF contains characters other than digits (0-9) - i.e., not matching ^[0-9]+$
        THEN:
            - valid = False
            - eligible_for_tier3 = False
            - eligible_for_cid_fund = False
            - reason = "LoyaltyID contains invalid characters (only digits 0-9 allowed)"
            - Return early (no Tier 3 benefits)
        - ELSE:
            - Store phone number as normalized_loyalty_id for tracking
            - Continue to Rule 4 (Daily Transaction Tracking)

Rule 4: Daily Transaction Tracking
    - Use normalized_loyalty_id for tracking (full QR code URL or phone number)
    - Increment daily transaction count for this LID
    - Track in DAILY_TRANSACTION_COUNTS[normalized_loyalty_id][today] = count
    - Store in database: daily_transaction_counts table
    - Note: QR codes and phone numbers are tracked separately (different loyalty_id values)

Rule 5: Manager/Store Card Detection
    IF daily_count > 5 (i.e., 6+ transactions today)
    THEN:
        - valid = True (format is valid)
        - eligible_for_tier3 = True (can still get basic Tier 3)
        - eligible_for_cid_fund = False (fraudulent pattern)
        - is_manager_card = True
        - reason = "Manager/store card detected: X transactions today (exceeds cap of 5)"
        - Return early (Tier 3 eligible, but CID fund ineligible)

Rule 6: Normal Valid LID
    IF daily_count <= 5 (1-5 transactions today)
    THEN:
        - valid = True
        - eligible_for_tier3 = True
        - eligible_for_cid_fund = True
        - is_manager_card = False
        - reason = "LoyaltyID valid and eligible"
        - Update customer profile in database

================================================================================
DATABASE RULES
================================================================================

New Customer (New LID):
    - Add new record to customer_profiles table
    - Store loyalty_id as provided (full QR code URL or phone number)
    - Generate or assign CID Customer ID (cid_customer_id)
      * CID Customer ID is separate from Loyalty ID
      * Used for CID promotional fund tracking and reporting
      * Format: Can be auto-generated or provided by external system
      * Must be unique across all customers
    - Store format_type: "QR_CODE" or "PHONE_NUMBER" (for reporting)
    - Initialize first_seen, last_seen, total_transactions
    - Add initial daily transaction count record

Existing Customer (Old LID):
    - Update last_seen timestamp
    - Increment total_transactions counter
    - Update daily transaction count for current date
    - Do NOT overwrite first_seen (preserve original registration date)
    - Do NOT change cid_customer_id (preserve CID Customer ID)
    - Note: QR code customers and phone number customers are separate records
      (same person using both formats = two separate customer profiles)

CID Customer ID Rules:
    - CID Customer ID is a separate identifier from Loyalty ID
    - Used specifically for CID promotional fund tracking and compliance reporting
    - Can be:
      * Auto-generated (UUID, sequential ID, or hash of loyalty_id)
      * Provided by external system (if available)
      * Derived from loyalty_id (if business rules allow)
    - Must be unique and persistent (does not change for a customer)
    - Stored in cid_customer_id field in customer_profiles table
    - Used for CID consistency tracking (5+ weeks in a quarter requirement)

================================================================================
QR CODE SPECIFIC NOTES
================================================================================

QR Code Format Details:
- Base URL: https://rtnsmart.com/rtnsmartapp/?USER_
- Encoded Parameter: Base64 encoded string
  * Example: NU5LK3RqSEJRZWZXMmNtY1k0ME5hZz09
  * Contains: A-Z, a-z, 0-9, +, /, = characters
  * Typically 20-60 characters in length
- Full URL Example: https://rtnsmart.com/rtnsmartapp/?USER_NU5LK3RqSEJRZWZXMmNtY1k0ME5hZz09

Validation Approach:
- Validate URL structure and encoded parameter format
- Store full QR code URL as loyalty_id in database
- QR codes are treated as valid loyalty customers (same privileges as phone numbers)
- Same daily transaction limits apply (5 transactions/day for CID fund eligibility)
- Same manager card detection applies (6+ transactions = manager card)

Future Enhancement (Optional):
- Decode Base64 parameter to extract underlying user identifier
- Link QR code to phone number if same customer uses both formats
- Currently: QR codes and phone numbers are tracked as separate customers

================================================================================
STEP 2: CONFIRM ADULT / AGE GATING
================================================================================

PURPOSE:
- Verify customer age eligibility for tobacco product purchases
- Enforce AVT (Age Verification Technology) requirements (in-person confirmation by cashier)
- Check EAIV (Electronic Age Identity Verification) status from database (updated by RTN app)
- Ensure compliance with age-gating regulations
- Log AVT transactions for compliance audit trail

NEW MODEL (App-first):
- Step 1: Customer does EAIV in RTN App (ID scan, selfie, DOB, Identity, ATC flag)
- Step 2: Customer shows QR code at POS (contains CID, EAIV_verified, EAIV_expiry, Signature)
- Step 3: Cashier performs physical age confirmation (legally required) - clicks "Age Verified"
- Step 4: RTN logs AVT transaction (AVT_performed, AVT_method, AVT_timestamp, Cashier_ID, Store_ID, Transaction_ID)

INPUTS:
- age_status (str/dict): AVT status from POS (cashier confirmation)
  - AVT status: "verified", "not_verified", "unknown", or None
  - NOTE: EAIV is NOT from POS - it comes from database (updated by RTN app)
- loyalty_id (str): Customer loyalty ID (from Step 1) - REQUIRED to check EAIV from database
- store_id (str): Store location ID - REQUIRED for AVT logging
- transaction_id (str): Transaction ID - REQUIRED for AVT logging
- cashier_id (str): Cashier/employee ID - REQUIRED for AVT logging

OUTPUTS:
Returns a dictionary with:
- age_verified (bool): True if AVT verified (cashier confirmed), False otherwise
- eaiv_verified (bool): True if EAIV verified (from database, updated by RTN app), False otherwise
- eligible_for_tier3_incentives (bool): True if can receive Tier 3 incentives
- eligible_for_eaiv_only_incentives (bool): True if can receive EAIV-only incentives
- reason (str): Explanation of age verification result

================================================================================
VALIDATION RULES
================================================================================

Rule 1: AVT (Age Verification Technology) Check
    AVT is in-person confirmation by cashier (legally required).
    Cashier must look at customer, confirm ID or face matches, and click "Age Verified".
    
    IF AVT status from POS is "verified" (cashier confirmed age)
    THEN:
        - age_verified = True
        - Continue to Rule 2 (EAIV check from database)
    ELSE IF AVT status is "not_verified" OR missing/invalid
    THEN:
        - age_verified = False
        - eaiv_verified = False (cannot check EAIV if AVT fails)
        - eligible_for_tier3_incentives = False
        - eligible_for_eaiv_only_incentives = False
        - reason = "Age verification required but not verified (cashier must confirm age)"
        - Return early (no Tier 3 benefits)
    ELSE:
        - age_verified = False (default to False if unknown)
        - Log warning: "AVT status unknown, defaulting to not verified"
        - Return early (no Tier 3 benefits)

Rule 2: EAIV (Electronic Age Identity Verification) Check
    EAIV comes from database (updated by RTN app), NOT from POS.
    Customer completes EAIV in RTN App (ID scan, selfie, DOB, Identity, ATC flag).
    RTN app updates customer_profiles.eaiv_verified in database.
    
    IF loyalty_id is provided
    THEN:
        - Query customer_profiles table for eaiv_verified status
        - IF eaiv_verified = 1 (true) in database
        THEN:
            - eaiv_verified = True
            - eligible_for_eaiv_only_incentives = True (if age_verified also True)
        ELSE:
            - eaiv_verified = False
            - eligible_for_eaiv_only_incentives = False
            - reason = "EAIV not verified (customer needs to complete EAIV in RTN app)"
    ELSE:
        - eaiv_verified = False
        - Log warning: "No loyalty_id provided - cannot check EAIV from database"

Rule 3: Tier 3 Incentive Eligibility
    IF age_verified = True (cashier confirmed)
    THEN:
        - eligible_for_tier3_incentives = True
        - reason = "Age verified (cashier confirmed) - eligible for Tier 3 incentives"
    ELSE:
        - eligible_for_tier3_incentives = False
        - reason = "Age not verified - ineligible for Tier 3 incentives"

Rule 4: EAIV-Only Incentive Eligibility
    IF age_verified = True AND eaiv_verified = True
    THEN:
        - eligible_for_eaiv_only_incentives = True
        - reason = "Age verified (cashier confirmed) and EAIV verified (from RTN app) - eligible for EAIV-only incentives"
    ELSE IF age_verified = True AND eaiv_verified = False
    THEN:
        - eligible_for_eaiv_only_incentives = False
        - reason = "Age verified but EAIV not verified (customer needs to complete EAIV in RTN app) - EAIV-only incentives restricted"
    ELSE:
        - eligible_for_eaiv_only_incentives = False
        - reason = "Age not verified - EAIV-only incentives ineligible"

Rule 5: AVT Transaction Logging (Compliance Audit Trail)
    When cashier performs physical age confirmation, MUST log AVT transaction.
    This is legally required for compliance.
    
    IF age_verified = True AND transaction_id AND store_id are provided
    THEN:
        - Insert record into avt_transactions table:
          * transaction_id
          * store_id
          * loyalty_id (if available)
          * cid_customer_id (from customer profile, if available)
          * avt_performed = true
          * avt_method = 'in_person_confirmation'
          * avt_timestamp = CURRENT_TIMESTAMP
          * cashier_id (if available)
          * eaiv_verified (from customer profile)
        - This creates the AVT audit trail for compliance reporting

================================================================================
DATABASE RULES
================================================================================

Customer Profile Updates:
- Store AVT verification status in customer_profiles table
- Store EAIV verification status in customer_profiles table (updated by RTN app, NOT by POS)
- Update last_avt_verified timestamp when AVT is verified (cashier confirms)
- Update last_eaiv_verified timestamp when EAIV is verified (updated by RTN app)
- Track verification history for compliance reporting

Fields in customer_profiles:
- avt_verified (INTEGER): 0 = false, 1 = true, NULL = unknown
- eaiv_verified (INTEGER): 0 = false, 1 = true, NULL = unknown (updated by RTN app)
- last_avt_verified (TIMESTAMP): Last time AVT was verified (cashier confirmed)
- last_eaiv_verified (TIMESTAMP): Last time EAIV was verified (updated by RTN app)
- cid_customer_id (TEXT): CID Customer ID (from QR code or RTN app)

New Table: avt_transactions
- Logs AVT transactions for compliance audit trail
- Fields:
  * transaction_id (TEXT): Transaction ID
  * store_id (TEXT): Store location ID
  * loyalty_id (TEXT): Customer loyalty ID
  * cid_customer_id (TEXT): CID Customer ID
  * avt_performed (INTEGER): 1 = true (always true when record exists)
  * avt_method (TEXT): 'in_person_confirmation'
  * avt_timestamp (TIMESTAMP): When AVT was performed
  * cashier_id (TEXT): Cashier/employee ID who performed confirmation
  * eaiv_verified (INTEGER): EAIV status from customer profile
  * created_at (TIMESTAMP): Record creation timestamp

================================================================================
AGE VERIFICATION NOTES
================================================================================

AVT (Age Verification Technology):
- Required for all tobacco product purchases (legally required)
- Performed by cashier at POS (in-person confirmation)
- Cashier must: look at customer, confirm ID or face matches, click "Age Verified"
- Must be verified before applying any digital tobacco incentives
- If AVT fails, customer cannot receive Tier 3 benefits
- AVT verification is transaction-specific (cashier confirms each transaction)
- AVT transaction MUST be logged in avt_transactions table for compliance

EAIV (Electronic Age Identity Verification):
- Performed in RTN App (NOT at POS, NOT from Gilbarco)
- Customer completes EAIV in RTN App: ID scan, selfie, DOB, Identity, ATC flag
- RTN app updates customer_profiles.eaiv_verified in database
- QR code contains: CID, EAIV_verified, EAIV_expiry, Signature
- Tier 3 requirement for some incentives (EAIV-only offers)
- Stored in customer profile for future transactions
- If EAIV is not verified, customer can still purchase but:
  * Cannot receive EAIV-only Tier 3 incentives
  * Can receive general Tier 3 incentives (if age_verified = True)
- EAIV status persists across transactions (stored in profile, updated by RTN app)

Business Rules:
- AVT verification is mandatory for Tier 3 benefits (cashier must confirm)
- EAIV verification is optional but required for EAIV-only incentives
- EAIV comes from database (updated by RTN app), NOT from POS
- If both AVT and EAIV are verified, customer gets full Tier 3 access
- If only AVT is verified, customer gets basic Tier 3 (no EAIV-only offers)
- AVT transaction MUST be logged for compliance audit trail

Compliance Requirements:
- AGDC accepts this model because:
  * EAIV already proves identity (done in RTN app)
  * Store confirmed physical presence (cashier confirms at POS)
  * Timestamped compliance record (avt_transactions table)

================================================================================
STEP 3: NORMALIZE THE BASKET (CLEAN THE UPC LIST)
================================================================================

PURPOSE:
- Lookup product master data for each UPC (brand, manufacturer, category, unit_of_measure)
- Classify unknown UPCs as "unknown tobacco"
- Combine identical UPC rows only if same unit price (AGDC scan rules expect line integrity)
- Map unit of measure (pack vs carton, etc.)
- Prepare normalized basket for discount calculation (Step 4-6)

INPUTS:
- transaction_lines (list): List of transaction line items from POS XML
  - Each line item contains:
    * upc (str): UPC code
    * quantity (int/str): Quantity purchased
    * unit_price (str): Unit price (regular price)
    * line_number (str): Line number in transaction
    * description (str): Item description (optional)

OUTPUTS:
Returns a dictionary with:
- normalized_lines (list): List of normalized line items with product master data
- unknown_upcs (list): List of UPCs not found in master table
- total_lines (int): Total number of lines after normalization
- combined_lines (int): Number of lines that were combined (same UPC + same price)
- errors (list): List of errors encountered during normalization

================================================================================
VALIDATION RULES
================================================================================

Rule 1: Extract Transaction Lines from POS XML
    Extract all transaction lines from GetRewardsRequest XML.
    
    FOR EACH TransactionLine element in XML:
        - Extract LineNumber
        - Extract UPC from ItemCode/POSCode
        - Extract Quantity
        - Extract RegularUnitPrice (or ExtendedPrice as fallback)
        - Extract Description (optional)
        - IF UPC is present:
            - Add to transaction_lines list
        - ELSE:
            - Log warning: "Line X has no UPC - skipping"
            - Add to errors list

Rule 2: Lookup UPC in Master Table
    For each UPC in transaction_lines, lookup product master data.
    
    FOR EACH UPC in transaction_lines:
        - Search upc_master table for UPC:
          * Search in CARTON_UPC column
          * Search in PACK_UPC column
          * Search in CARTON_SuppressedUPC column
        - IF UPC found in master table:
            - Extract product data:
              * SKUGUID: Unique SKU identifier
              * SKUName: SKU name/description
              * Brand: Brand name
              * manufacturer: ATOC, Other, etc.
              * category: CIG, MST, CIGAR, ONP, etc.
              * program_eligibility: ATOC, Other, etc.
              * unit_of_measure: CARTON or PACK (determined by which column matched)
              * CARTON fields: CARTON_UPC, CARTON_SuppressedUPC, CARTON_ConversionFactor, CARTON_IsPromotionalUPC
              * PACK fields: PACK_UPC, PACK_ConversionFactor, PACK_IsPromotionalUPC
            - Create normalized line item with all product data
        - ELSE:
            - Classify as "UNKNOWN_TOBACCO"
            - Set category = "UNKNOWN_TOBACCO"
            - Set all other fields to None
            - Add UPC to unknown_upcs list
            - Log warning: "UPC 'X' not found in master table - classifying as 'unknown tobacco'"

Rule 3: Combine Identical UPC Rows
    AGDC scan rules expect line integrity - only combine if same UPC AND same unit price.
    
    FOR EACH normalized line item:
        - Create key: (UPC, unit_price)
        - IF key already exists in combined_lines:
            - Combine with existing line:
              * Add quantities together
              * Keep same UPC, price, and product data
              * Log: "Combined line - UPC='X', Price=Y, Total Qty=Z"
              * Increment combined_lines counter
        - ELSE:
            - Add as new line to combined_lines
            - Store key for future lookups

Rule 4: Return Normalized Basket
    Return normalized basket with all product master data attached.
    
    RETURN:
        - normalized_lines: List of combined, normalized line items
        - unknown_upcs: List of UPCs not found in master table
        - total_lines: Count of normalized lines
        - combined_lines: Count of lines that were combined
        - errors: List of errors encountered

================================================================================
DATABASE RULES
================================================================================

UPC Master Table (upc_master):
- Stores product master data for all UPCs
- One row per SKU (not per UPC)
- Each row contains both CARTON and PACK UPCs

Fields in upc_master:
- SKUGUID (TEXT): Unique SKU identifier
- SKUName (TEXT): SKU name/description
- Brand (TEXT): Brand name
- manufacturer (TEXT): ATOC, Other, etc. (optional)
- category (TEXT): CIG, MST, CIGAR, ONP, etc. (optional)
- program_eligibility (TEXT): ATOC, Other, etc. (optional)
- CARTON_UPC (TEXT): CARTON UPC code
- CARTON_SuppressedUPC (TEXT): CARTON Suppressed UPC (if applicable)
- CARTON_ConversionFactor (REAL): CARTON ConversionFactor (e.g., 10.0 for 10 packs per carton)
- CARTON_IsPromotionalUPC (INTEGER): 0 = false, 1 = true
- PACK_UPC (TEXT): PACK UPC code
- PACK_ConversionFactor (REAL): PACK ConversionFactor (typically 1.0)
- PACK_IsPromotionalUPC (INTEGER): 0 = false, 1 = true
- created_at (TIMESTAMP): Record creation timestamp
- updated_at (TIMESTAMP): Record update timestamp

Indexes:
- idx_upc_master_carton_upc: Fast lookup by CARTON_UPC
- idx_upc_master_pack_upc: Fast lookup by PACK_UPC
- idx_upc_master_carton_suppressed: Fast lookup by CARTON_SuppressedUPC
- idx_upc_master_skuguid: Fast lookup by SKUGUID
- idx_upc_master_brand: Fast lookup by Brand
- idx_upc_master_manufacturer: Fast lookup by manufacturer
- idx_upc_master_category: Fast lookup by category

UPC Lookup Logic:
- When a UPC is received from POS, search in this order:
  1. CARTON_UPC column
  2. PACK_UPC column
  3. CARTON_SuppressedUPC column
- If found, determine unit_of_measure:
  * If matched in CARTON_UPC or CARTON_SuppressedUPC → unit_of_measure = "CARTON"
  * If matched in PACK_UPC → unit_of_measure = "PACK"
- Return all product data including both CARTON and PACK fields

Unknown UPC Handling:
- If UPC not found in master table:
  * Classify as "UNKNOWN_TOBACCO"
  * Set category = "UNKNOWN_TOBACCO"
  * Set all product fields to None
  * Add to unknown_upcs list for reporting
  * Transaction can still proceed (unknown UPCs are allowed)
  * Optional: Call mapping service / fallback table (future enhancement)

Line Combination Rules:
- Only combine lines if:
  * Same UPC (exact match)
  * Same unit_price (exact match)
- Do NOT combine if:
  * Different prices (even if same UPC)
  * Different discounts applied
- Reason: AGDC scan rules expect line integrity for accurate reporting

================================================================================
NORMALIZATION NOTES
================================================================================

Product Master Data:
- Each SKU has one row in upc_master table
- Each row contains both CARTON and PACK UPCs (if applicable)
- Some SKUs may only have PACK_UPC (no carton version)
- Some SKUs may only have CARTON_UPC (no pack version)
- ConversionFactor indicates pack-to-carton ratio (e.g., 10.0 = 10 packs per carton)

UPC Matching:
- System searches all three UPC columns: CARTON_UPC, PACK_UPC, CARTON_SuppressedUPC
- First match wins (LIMIT 1 in SQL query)
- If UPC matches CARTON_UPC → unit_of_measure = "CARTON"
- If UPC matches PACK_UPC → unit_of_measure = "PACK"
- If UPC matches CARTON_SuppressedUPC → unit_of_measure = "CARTON" (suppressed)

Normalized Line Item Structure:
Each normalized line contains:
- Original fields: upc, quantity, unit_price, line_number, description
- Product master data: SKUGUID, SKUName, Brand, manufacturer, category, program_eligibility
- Unit of measure: unit_of_measure (CARTON or PACK)
- UPC type: matched_upc_type (CARTON, PACK, or CARTON_SUPPRESSED)
- CARTON fields: CARTON_UPC, CARTON_SuppressedUPC, CARTON_ConversionFactor, CARTON_IsPromotionalUPC
- PACK fields: PACK_UPC, PACK_ConversionFactor, PACK_IsPromotionalUPC
- Unknown flag: is_unknown (True if UPC not found in master table)

Combination Logic:
- AGDC scan rules require line integrity
- Only combine identical UPCs with same price
- Preserves discount accuracy and reporting compliance
- Example:
  * Line 1: UPC=123, Qty=2, Price=$5.00 → Combined
  * Line 2: UPC=123, Qty=1, Price=$5.00 → Combined (Total Qty=3)
  * Line 3: UPC=123, Qty=1, Price=$4.50 → NOT Combined (different price)

Future Enhancements:
- Optional: Call external mapping service for unknown UPCs
- Optional: Fallback table for common unknown UPCs
- Optional: Auto-classify category based on description keywords
- Optional: Link suppressed UPCs to primary UPCs for reporting

================================================================================
STEP 4: IDENTIFY WHICH DISCOUNT TYPES ARE ALLOWED
================================================================================

PURPOSE:
- Categorize discount rules into separate buckets (manufacturer, retailer, loyalty, multi-unit, coupon, etc.)
- Keep buckets separate for correct price calculation, receipt lines, and scan data reporting
- Identify PM USA Multi-Pack configurations (2-pack or 3-pack) for Marlboro revenue PACK items

INPUTS:
- normalized_lines (list): Output of Step 3 normalization
- customer_eligibility (dict): Output flags from Step 1-2:
  * eligible_for_tier3 (bool)
  * eligible_for_cid_fund (bool)  (used later for PM USA 5/day cap gating in Step 5)
  * age_verified (bool)
  * eaiv_verified (bool)
  * eligible_for_tier3_incentives (bool)
  * eligible_for_eaiv_only_incentives (bool)
- store_id (str): StoreLocationID
- loyalty_id (str): LoyaltyID

OUTPUTS:
Returns a dictionary with discount buckets:
- manufacturer_discounts: Manufacturer allowances (from `loyalty_allowances` / AGDC API)
- retailer_discounts: Retailer-funded discounts (placeholder – table not created yet)
- loyalty_discounts: Placeholder marker (calculated in Step 6)
- multi_pack_discounts: Marlboro Multi-Pack Fund detection (2-pack or 3-pack)
- multi_unit_discounts: Multi-unit rules (placeholder – table not created yet)
- coupon_discounts: Coupon rules (placeholder – table not created yet)
- other_manufacturer_discounts: Other manufacturer rules (placeholder)
- transaction_discounts: Transaction-level rules (placeholder)
- total_discounts_found: Count across all buckets

RULES IMPLEMENTED (CURRENT CODE):

Rule 1: Manufacturer Allowances (AGDC/PM USA Loyalty Funds)
- Lookup by SKUGUID list in `loyalty_allowances` joined to `loyalty_allowance_skus`
- Active date range only (StartDate <= today <= EndDate)
- Only included if customer_eligibility.eligible_for_tier3 is true

Rule 2: Multi-Pack Detection (PM USA Marlboro Multi-Pack Fund – detection only)
- Identify Marlboro “revenue” PACK items:
  * Brand contains "MARLBORO"
  * unit_of_measure == "PACK"
  * PACK_IsPromotionalUPC != "Y" (exclude Product Promotions)
- Detect multi-pack configuration as total quantity of 2 or 3 for the same UPC:
  * Works when POS sends a single line with SalesQuantity=2/3
  * Works when POS sends multiple lines that sum to 2 or 3
- Returns multi_pack_discounts entries including scan-data fields:
  * multi_unit_indicator = "Y"
  * multi_unit_required_quantity = 2 or 3
  * multi_unit_discount_amount = 0.0 (placeholder; actual amount applied in Step 6)
  * needs_rate_lookup = True (rate is geography/PSO specific; applied in Step 6)

NOTES:
- Step 4 does NOT apply pricing/discount amounts. It only identifies discount types and multi-pack configs.
- Actual Multi-Pack Fund amounts require rate tables/configuration and will be applied in Step 6.

================================================================================
STEP 5: DETERMINE ELIGIBILITY FOR EACH UPC / DISCOUNT BUCKET
================================================================================

PURPOSE:
- Decide which UPC lines and which discount buckets are eligible BEFORE Step 6 pricing.
- Enforce PM USA RTA gating that determines whether PM USA-funded allowances can be earned/reported.

PM USA RTA RULE (Jan 20, 2026 Doc010PMUSA-RTA):
- “Retailer will not earn LFP Promotional Allowances on more than five transactions per day
   with a single Loyalty ID (e.g., Manager Card, Store Card).”

INPUTS:
- normalized_lines (list): Output of Step 3
- customer_eligibility (dict): Output of Step 1-2 (includes eligible_for_cid_fund)
- categorized_discounts (dict): Output of Step 4 (includes multi_pack_discounts)
- store_id, loyalty_id

OUTPUTS:
Returns a dictionary with:
- transaction_flags:
  * tier3_eligible (bool)
  * tier3_incentives_eligible (bool)
  * pmusa_allowances_eligible (bool)
  * reasons (list of strings)
- eligible_discount_buckets:
  * manufacturer, multi_pack, multi_unit, coupon, retailer, loyalty, other_manufacturer, transaction
- line_results: list of per-line eligibility flags and reasons

RULES IMPLEMENTED (CURRENT CODE):

Rule 1: Base Tier 3 / Incentives gating
- tier3_eligible = customer_eligibility.eligible_for_tier3
- tier3_incentives_eligible = customer_eligibility.eligible_for_tier3_incentives

Rule 2: PM USA 5/day cap gating (manager/store card)
- If customer_eligibility.eligible_for_cid_fund is False:
  * pmusa_allowances_eligible = False
  * Disable PM USA-funded buckets:
    - eligible_discount_buckets["manufacturer"] = False
    - eligible_discount_buckets["multi_pack"] = False
  * Add reason: “PM USA allowances ineligible: loyalty ID exceeded 5 transactions/day…”

Rule 3: Per-line PM USA eligibility (conservative)
- For each line, compute:
  * is_marlboro (Brand contains “MARLBORO”)
  * unit_of_measure (“PACK” or “CARTON”)
  * is_promotional_upc (PACK_IsPromotionalUPC or CARTON_IsPromotionalUPC == "Y")
- If pmusa_allowances_eligible is True:
  * Eligible for PM USA Multi-Pack + LFP allowances only when:
    - Marlboro brand
    - PACK unit
    - Not promotional UPC
- If pmusa_allowances_eligible is False:
  * Line is not eligible for PM USA allowances (reason recorded)

INTEGRATION (app.py):
- Step 5 runs immediately after Step 4.
- Console will show a warning when PM USA allowances are ineligible:
  “⚠️  PM USA: Allowances ineligible (5/day loyalty cap / manager card).”

NOTES:
- Step 5 does NOT calculate or apply discount amounts.
- Step 5 only decides “allowed/not allowed” for each bucket and each line.
- Step 6 will apply amounts (including Multi-Pack fund rates) only if Step 5 allows the bucket/line.

================================================================================
STEP 6: APPLY PRICING RULES IN THE CORRECT ORDER
================================================================================

PURPOSE:
- Calculate actual discount amounts based on eligibility from Step 5.
- Apply discounts in the exact order specified by Workflow.txt (6A-6F).
- Respect discount bucket eligibility flags.
- Apply final price guardrails (no negative prices, rounding).

DISCOUNT APPLICATION ORDER (per Workflow.txt):

6A) Base Price
- Start with POS regular price (unit_price from normalized_lines).

6B) Multi-Unit / Mix&Match Rules
- Apply Buy 2 Save $X, Buy 3 Save $Y, Mix&Match bundle discounts.
- Multi-unit evaluation happens BEFORE coupons (changes which items qualify).

6C) Manufacturer Digital Coupons (RDC / Enhanced RDC)
- Apply manufacturer allowances from Step 4 (AGDC/Altria funded).
- Apply digital coupon discounts if customer clipped offer.
- Match by UPC/SKUGUID, verify frequency limits, apply per-unit discount.

6D) Loyalty / Tier 3 Locked Rewards
- Apply loyalty discounts if customer is Tier 3 eligible.
- Default loyalty discount: $0.97 (configurable via LOYALTY_DISCOUNT_AMOUNT).
- Can be enhanced to support EAIV-only or app-paid rewards (locked/unlocked logic).

6E) Retailer-Funded Incentives
- Apply store-funded discounts (only after manufacturer and loyalty calculated).
- Supports stacking if allowed by program rules.

6F) Final Price Guardrails
- Ensure no negative line prices (final_price = max(0, base_price - total_discount)).
- Enforce max discount caps per item / per transaction (future enhancement).
- Round properly to cents (2 decimal places, ROUND_HALF_UP).

INPUTS:
- normalized_lines (list): Output of Step 3 (normalized basket with unit prices)
- categorized_discounts (dict): Output of Step 4 (discount types identified)
- eligibility_result (dict): Output of Step 5 (eligibility flags and bucket gates)
- customer_eligibility (dict): Customer eligibility from Step 1-2
- store_id, loyalty_id

OUTPUTS:
Returns a dictionary with:
- line_results: List of pricing results per line:
  * upc, line_number, quantity, unit_of_measure
  * base_unit_price, base_extended_price
  * discounts_by_bucket: dict with discount amounts per bucket
  * total_discount, final_unit_price, final_extended_price
- transaction_summary:
  * total_base_price, total_discount, total_final_price
  * discounts_by_bucket: aggregated discount totals
- rewards: List of reward structures for POS response (format compatible with build_get_rewards_response)

MULTI-PACK (NOT APPLIED HERE):
- Single-pack and multi-pack discounts are applied by Gilbarco POS directly.
- We do NOT calculate or apply multi-pack amounts. No multi_pack_fund_rates table.
- Step 4 identifies multi-pack configs (2-pack/3-pack) for scan data tagging only.
- Multi-Unit Indicator, Multi-Unit Required Qty, Multi-Unit Discount Amount in scan
  data come from POS (or are captured when POS sends transaction data).

LOYALTY DISCOUNT CONFIGURATION:
- Lookup from loyalty_allowances.MaximumAllowancePerTransaction (from AGDC API).
- Matches by SKUGUID (or NULL SKUGUID for all products).
- Applied only if:
  * eligible_buckets["loyalty"] is True
  * transaction_flags["tier3_eligible"] is True
  * customer_eligibility["eligible_for_tier3"] is True

RULES IMPLEMENTED (CURRENT CODE):

Rule 1: Respect Eligibility Gates
- Only apply discounts if eligible_buckets[bucket_name] is True.
- Only apply line-level discounts if line_eligibility flags allow it.

Rule 2: Multi-Pack (Not Applied)
- Multi-pack applied by POS. We do not calculate or apply. discounts_by_bucket["multi_pack"] stays 0.

Rule 3: Discount Accumulation
- Each discount bucket is calculated independently (multi_pack excluded; POS applies).
- Total discount = sum of loyalty, manufacturer_coupon, multi_unit, retailer, etc.
- Applied order: multi_unit → manufacturer_coupon → loyalty → retailer → other_manufacturer → transaction.

Rule 4: Price Guardrails
- Final price = max(0, base_price - total_discount).
- Round to 2 decimal places using ROUND_HALF_UP.
- No negative prices allowed.

Rule 5: Reward Generation
- Generate one reward per line that has total_discount > 0 (loyalty + manufacturer only; no multi-pack).
- Reward value = total_discount for that line.
- Reward description: "LOYALTY" and/or "MANUFACTURER" (multi-pack not included; POS applies).
- Reward ID format: "{line_number}-1-B2_S150" (can be enhanced).

INTEGRATION (app.py):
- Step 6 runs immediately after Step 5.
- Console output: "💳 LOYALTY: $X.XX discount applied", "🏭 MANUFACTURER: $X.XX discount applied",
  "✅ REWARDS: Generated N reward(s) totaling $X.XX". No multi-pack applied message.
- Rewards from Step 6 passed to build_get_rewards_response.

NOTES:
- Step 6 applies loyalty (and manufacturer) only. Multi-pack applied by Gilbarco POS.
- Loyalty discount from loyalty_allowances.MaximumAllowancePerTransaction (no separate loyalty_discount_rules table).
- Multi-pack identification (Step 4) used for scan data tagging; amount from POS.


================================================================================
STEP 7: BUILD THE RESPONSE PAYLOAD (POS + RECEIPT SAFE)
================================================================================

PURPOSE:
Build the complete response payload for POS with formatted receipt lines and
enhanced reward descriptions. Ensures POS-safe formatting (<=32 chars per line).

FILE: tier3_step7.py

INPUTS:
- pricing_result: Output from Step 6 (rewards, transaction_summary, line_results)
- customer_eligibility: From Steps 1-2 (eligible_for_tier3, eligible_for_cid_fund)
- validation_result: From Step 1 (loyalty ID validation)
- age_result: From Step 2 (age_verified, eaiv_verified)

OUTPUTS:
- rewards: Enhanced rewards list with formatted descriptions
- receipt_lines: Formatted receipt lines (max 32 chars each, max 10 lines)
- transaction_summary: Summary for logging/display
- response_flags: Flags for response building

RECEIPT LINE FORMAT:
- Max 32 characters per line
- Max 10 lines total
- Left-right padding for amounts (e.g., "LOYALTY SAVINGS        -$1.70")

RECEIPT LINE EXAMPLES:
```
*** LOYALTY REWARDS ***
LOYALTY SAVINGS        -$1.70
--------------------------------
TOTAL SAVINGS          -$1.70
************************
```

LOCKED REWARDS MESSAGING:
If customer is eligible for Tier 3 but NOT EAIV verified:
```
APP BONUS AVAILABLE
VERIFY ID IN APP TO UNLOCK
```

REWARD DESCRIPTION FORMAT:
- short_desc: "LOYALTY -$1.70" (max 32 chars)
- long_desc: "LOYALTY REWARD" (max 32 chars)

RULES IMPLEMENTED:

Rule 1: Receipt Line Length
- All lines truncated to 32 characters
- Long text gets "..." suffix

Rule 2: Discount Breakdown
- Separate lines for: LOYALTY SAVINGS, MFG COUPON, MULTI-BUY SAVINGS, STORE SAVINGS
- TOTAL SAVINGS line at bottom

Rule 3: Locked vs Unlocked Messaging
- If eligible_for_tier3 = True AND eaiv_verified = False:
  - Show "APP BONUS AVAILABLE" and "VERIFY ID IN APP TO UNLOCK"
- This encourages EAIV verification for additional benefits

Rule 4: No Rewards Message
- If no rewards applicable, show reason:
  - "Loyalty ID not eligible"
  - "Age verification required"
  - "No eligible rewards"

INTEGRATION (app.py):
- Step 7 runs immediately after Step 6 database storage
- Enhanced rewards replace original rewards
- Receipt lines logged for debugging
- Console output: "🧾 RECEIPT: N lines generated"

CONSOLE OUTPUT:
- "🧾 RECEIPT: N lines generated"

DEBUG LOG OUTPUT:
- "handle_get_rewards: ========== STEP 7: BUILD RESPONSE =========="
- "handle_get_rewards: Receipt lines (N):"
- Each receipt line logged individually
