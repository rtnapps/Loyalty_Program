# Setup and Run Instructions

## Proper Workflow

### Step 1: Initialize Database
```bash
python init_database.py
```
**Purpose:** Creates all required database tables and enables WAL mode for performance.

**Expected Output:**
- ✅ Database created/updated successfully
- ✅ WAL mode enabled
- List of created tables

---

### Step 2: Enable WAL Mode (if database already exists)
```bash
python enable_wal_mode.py
```
**Purpose:** Enables WAL mode on existing databases for better performance (especially for phone number transactions).

**Note:** This step is optional if you just ran `init_database.py` (WAL mode is already enabled).

---

### Step 3: Sync AGDC API Data

You need to run this **for EACH store account** to populate product and allowance data.

#### For Stop N Save (Account: 0000473527):
```bash
python sync_agdc_api.py 0004 202602 0000473527
```

#### For SAMS (Account: 0000709486):
```bash
python sync_agdc_api.py 0004 202602 0000709486
```

**Command Format:**
```
python sync_agdc_api.py <operatingCompany> <cycleCode> <accountNumber>
```

**Parameters:**
- `operatingCompany`: "0004" (your operating company code)
- `cycleCode`: "202602" (current cycle code - update as needed)
- `accountNumber`: Store account number
  - Stop N Save: `0000473527`
  - SAMS: `0000709486`

**Expected Output:**
- ✅ Bearer token obtained
- ✅ Products synced: X products
- ✅ Allowances synced: X allowances
- Summary of synced data

**Important:** Run this for **BOTH** accounts to ensure all store data is available.

---

### Step 4: Run the Main Server
```bash
python app.py
```

**Purpose:** Starts the loyalty server that:
- Listens on `192.168.41.103:9000` (configured in app.py)
- Automatically runs Tier 3 Steps 1-7 when POS sends requests
- Processes loyalty ID validation, age gating, discount calculation, etc.

**Expected Output:**
```
Starting SKUPOS DEBUG FULL server on 192.168.41.103:9000
Server listening; waiting for incoming POS connections...
```

**Note:** The server will automatically execute:
- Step 1: Validate Loyalty ID
- Step 2: Age Gating
- Step 3: Normalize Basket
- Step 4: Identify Discount Types
- Step 5: Eligibility Gating
- Step 6: Pricing Calculation
- Step 7: Build Response Payload

---

## Complete Setup Sequence

```bash
# 1. Initialize database (first time only, or after schema changes)
python init_database.py

# 2. Enable WAL mode (if database already existed)
python enable_wal_mode.py

# 3. Sync data for Stop N Save
python sync_agdc_api.py 0004 202602 0000473527

# 4. Sync data for SAMS
python sync_agdc_api.py 0004 202602 0000709486

# 5. Start the server
python app.py
```

---

## Verification

After setup, you should have:
- ✅ Database file: `loyalty.db` (with WAL mode enabled)
- ✅ Product data synced for both stores
- ✅ Allowance data synced for both stores
- ✅ Server running and listening for POS connections

---

## Troubleshooting

### If sync_agdc_api.py fails:
- Check your OAuth credentials in `sync_agdc_api.py`
- Verify the cycle code is current
- Ensure account numbers are correct
- Check network connectivity to AGDC API

### If app.py fails to start:
- Ensure database exists (run `init_database.py`)
- Check that port 9000 is not in use
- Verify all tier3_step*.py files are present

### If phone numbers are still slow:
- Verify WAL mode is enabled: `python enable_wal_mode.py`
- Check database file permissions
- Ensure no other processes are locking the database
