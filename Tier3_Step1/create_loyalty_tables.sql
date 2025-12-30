-- ============================================================================
-- SQLite Database Schema for Tier 3 Loyalty System
-- ============================================================================
-- This file contains SQL queries to create all necessary tables for the
-- Tier 3 Rules Engine loyalty ID validation and tracking system.
-- ============================================================================

-- ============================================================================
-- Table: customer_profiles
-- ============================================================================
-- Stores customer profile information for each Loyalty ID (LID)
-- Purpose: Track customer registration, activity, and eligibility
-- ============================================================================

CREATE TABLE IF NOT EXISTS customer_profiles (
    loyalty_id TEXT PRIMARY KEY NOT NULL,
    first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_transactions INTEGER NOT NULL DEFAULT 0,
    is_manager_card INTEGER NOT NULL DEFAULT 0,  -- 0 = false, 1 = true
    store_id TEXT,  -- Store location ID where customer was first seen
    format_type TEXT,  -- 'PHONE_NUMBER' or 'QR_CODE'
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster lookups by store_id
CREATE INDEX IF NOT EXISTS idx_customer_profiles_store_id ON customer_profiles(store_id);

-- Index for faster lookups by last_seen (for cleanup queries)
CREATE INDEX IF NOT EXISTS idx_customer_profiles_last_seen ON customer_profiles(last_seen);


-- ============================================================================
-- Table: daily_transaction_counts
-- ============================================================================
-- Tracks daily transaction counts per Loyalty ID for fraud detection
-- Purpose: Detect manager/store cards (6+ transactions per day)
-- ============================================================================

CREATE TABLE IF NOT EXISTS daily_transaction_counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loyalty_id TEXT NOT NULL,
    transaction_date DATE NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(loyalty_id, transaction_date)
);

-- Index for faster lookups by loyalty_id and date
CREATE INDEX IF NOT EXISTS idx_daily_counts_loyalty_date ON daily_transaction_counts(loyalty_id, transaction_date);

-- Index for cleanup queries (remove old records)
CREATE INDEX IF NOT EXISTS idx_daily_counts_date ON daily_transaction_counts(transaction_date);


-- ============================================================================
-- Table: loyalty_validation_log
-- ============================================================================
-- Logs all loyalty ID validation attempts for audit and debugging
-- Purpose: Track validation results, reasons, and eligibility flags
-- ============================================================================

CREATE TABLE IF NOT EXISTS loyalty_validation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loyalty_id TEXT NOT NULL,
    store_id TEXT,
    validation_timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid INTEGER NOT NULL DEFAULT 0,  -- 0 = false, 1 = true
    eligible_for_tier3 INTEGER NOT NULL DEFAULT 0,  -- 0 = false, 1 = true
    eligible_for_cid_fund INTEGER NOT NULL DEFAULT 0,  -- 0 = false, 1 = true
    is_manager_card INTEGER NOT NULL DEFAULT 0,  -- 0 = false, 1 = true
    daily_count INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    transaction_id TEXT  -- Optional: link to transaction if available
);

-- Index for faster lookups by loyalty_id
CREATE INDEX IF NOT EXISTS idx_validation_log_loyalty_id ON loyalty_validation_log(loyalty_id);

-- Index for faster lookups by timestamp (for reporting)
CREATE INDEX IF NOT EXISTS idx_validation_log_timestamp ON loyalty_validation_log(validation_timestamp);

-- Index for manager card detection queries
CREATE INDEX IF NOT EXISTS idx_validation_log_manager_card ON loyalty_validation_log(is_manager_card);


-- ============================================================================
-- Table: transactions
-- ============================================================================
-- Stores transaction records for scan data and reimbursement tracking
-- Purpose: Log all transactions with loyalty IDs for AGDC compliance
-- ============================================================================

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    loyalty_id TEXT,
    transaction_timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tender_amount REAL,
    total_discount REAL DEFAULT 0.0,
    final_amount REAL,
    age_verified INTEGER DEFAULT 0,  -- 0 = false, 1 = true
    eaiv_verified INTEGER DEFAULT 0,  -- 0 = false, 1 = true
    tier3_eligible INTEGER DEFAULT 0,  -- 0 = false, 1 = true
    cid_fund_eligible INTEGER DEFAULT 0,  -- 0 = false, 1 = true
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster lookups by transaction_id
CREATE INDEX IF NOT EXISTS idx_transactions_transaction_id ON transactions(transaction_id);

-- Index for faster lookups by loyalty_id
CREATE INDEX IF NOT EXISTS idx_transactions_loyalty_id ON transactions(loyalty_id);

-- Index for faster lookups by store_id
CREATE INDEX IF NOT EXISTS idx_transactions_store_id ON transactions(store_id);

-- Index for faster lookups by timestamp (for reporting)
CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(transaction_timestamp);


-- ============================================================================
-- Table: transaction_lines
-- ============================================================================
-- Stores line items for each transaction
-- Purpose: Track UPC, quantity, prices, discounts for scan data export
-- ============================================================================

CREATE TABLE IF NOT EXISTS transaction_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    upc TEXT NOT NULL,
    description TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    regular_unit_price REAL NOT NULL,
    discount_amount REAL DEFAULT 0.0,
    final_unit_price REAL NOT NULL,
    category TEXT,  -- CIG, MST, CIGAR, ONP, etc.
    manufacturer TEXT,  -- ATOC vs non-ATOC
    discount_type TEXT,  -- manufacturer, retailer, loyalty, coupon, multi-unit
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
);

-- Index for faster lookups by transaction_id
CREATE INDEX IF NOT EXISTS idx_transaction_lines_transaction_id ON transaction_lines(transaction_id);

-- Index for faster lookups by UPC (for product analysis)
CREATE INDEX IF NOT EXISTS idx_transaction_lines_upc ON transaction_lines(upc);


-- ============================================================================
-- VIEW: customer_summary
-- ============================================================================
-- Convenience view for customer profile with recent activity summary
-- ============================================================================

CREATE VIEW IF NOT EXISTS customer_summary AS
SELECT 
    cp.loyalty_id,
    cp.first_seen,
    cp.last_seen,
    cp.total_transactions,
    cp.is_manager_card,
    cp.store_id,
    COALESCE(dtc.count, 0) AS today_transaction_count,
    dtc.transaction_date AS last_transaction_date
FROM customer_profiles cp
LEFT JOIN (
    SELECT 
        loyalty_id,
        transaction_date,
        count,
        ROW_NUMBER() OVER (PARTITION BY loyalty_id ORDER BY transaction_date DESC) AS rn
    FROM daily_transaction_counts
) dtc ON cp.loyalty_id = dtc.loyalty_id AND dtc.rn = 1;


-- ============================================================================
-- TRIGGERS: Auto-update timestamps
-- ============================================================================

-- Trigger to update updated_at timestamp on customer_profiles
CREATE TRIGGER IF NOT EXISTS update_customer_profiles_timestamp 
AFTER UPDATE ON customer_profiles
BEGIN
    UPDATE customer_profiles 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE loyalty_id = NEW.loyalty_id;
END;

-- Trigger to update updated_at timestamp on daily_transaction_counts
CREATE TRIGGER IF NOT EXISTS update_daily_counts_timestamp 
AFTER UPDATE ON daily_transaction_counts
BEGIN
    UPDATE daily_transaction_counts 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;