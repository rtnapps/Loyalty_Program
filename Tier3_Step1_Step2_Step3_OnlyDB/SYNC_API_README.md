# AGDC API Sync Script

This script fetches product and allowance data from the AGDC API and syncs it to the local database.

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Update API parameters in `sync_agdc_api.py`:**
   ```python
   API_PARAMS = {
       "operatingCompany": "0004",  # Your operating company code
       "cycleCode": "202602",  # Current cycle code
       "accountNumber": "0000709486"  # Your account number
   }
   
   # API Authentication
   OCP_APIM_SUBSCRIPTION_KEY = "e42134d5244a4a6e966e3785e14d7f88"  # Your subscription key
   OAUTH_CLIENT_ID = None  # Optional: if OAuth requires client_id
   OAUTH_CLIENT_SECRET = None  # Optional: if OAuth requires client_secret
   ```

## Usage

### Basic Usage (uses default parameters from script):
```bash
python sync_agdc_api.py
```

### With Command-Line Arguments:
```bash
python sync_agdc_api.py <operatingCompany> <cycleCode> <accountNumber>
```

Example:
```bash
python sync_agdc_api.py 0004 202602 0000709486
```

## What It Does

1. **Fetches data from AGDC API:**
   - Products (SKUs with CARTON and PACK UPCs)
   - Loyalty Allowances (discount rules and eligibility)

2. **Updates database:**
   - `products` table: Product master data
   - `loyalty_allowances` table: Allowance rules
   - `loyalty_allowance_skus` table: Maps SKUs to allowances

3. **Handles updates:**
   - If product/SKU already exists → Updates it
   - If new → Inserts it
   - Preserves existing data and adds API metadata

## Database Tables

### `products` Table
Stores product master data from API:
- SKUGUID, SKUName, Brand
- CARTON_UPC, CARTON_SuppressedUPC, CARTON_ConversionFactor, CARTON_IsPromotionalUPC
- PACK_UPC, PACK_SuppressedUPC, PACK_ConversionFactor, PACK_IsPromotionalUPC
- manufacturer, category, program_eligibility
- API metadata: api_cycle_code, api_account_number, api_last_synced

### `loyalty_allowances` Table
Stores allowance rules from API:
- AllowanceType, RCN, EligibleUOM
- MinimumQuantity, MaximumAllowancePerTransaction
- MaximumDailyTransactionsPerLoyalty
- ManufacturerFundedAmount, LoyaltyFundPromotionCode
- Amount, StartDate, EndDate
- API metadata: api_cycle_code, api_account_number, api_last_synced

### `loyalty_allowance_skus` Table
Junction table mapping SKUs to allowances (many-to-many relationship).

## API Response Structure

The API returns:
```json
[
    {
        "Header": {...},
        "Stores": [...],
        "Products": [
            {
                "SKUGUID": "...",
                "SKUName": "...",
                "Brand": "...",
                "Packings": [
                    {
                        "UPC": "...",
                        "SuppressedUPC": "N/A" or "...",
                        "UOM": "CARTON" or "PACK",
                        "ConversionFactor": 10 or 1,
                        "IsPromotionalUPC": "Y" or "N"
                    }
                ]
            }
        ],
        "LoyaltyAllowances": [
            {
                "AllowanceType": "Loyalty Fund Allowances",
                "RCN": ["..."],
                "SKUGUID": ["..."],
                "EligibleUOM": ["CARTON", "PACK"],
                "MinimumQuantity": 2,
                "MaximumAllowancePerTransaction": 2.0,
                "MaximumDailyTransactionsPerLoyalty": 5,
                "ManufacturerFundedAmount": 2.0,
                "LoyaltyFundPromotionCode": "...",
                "PromotionalUPCsEligible": "N",
                "Allowances": [
                    {
                        "Currency": "USD",
                        "Amount": 2.0,
                        "StartDate": "2026-01-25",
                        "EndDate": "2026-02-21",
                        "ChangeFromPriorPeriod": 0.0
                    }
                ]
            }
        ]
    }
]
```

## Notes

- The script handles "N/A" values by converting them to NULL in the database
- Suppressed UPCs are stored separately (CARTON_SuppressedUPC, PACK_SuppressedUPC)
- The script tracks when data was last synced (api_last_synced)
- Cycle codes and account numbers are stored for reference

## Authentication

The API requires two authentication methods:

1. **OAuth2 Bearer Token**: Obtained from `https://api.insightsc3m.com/altria/oauth2/v2.0/token`
   - The script automatically fetches the token before making API requests
   - Token expires in ~3600 seconds (1 hour)
   - Script will fetch a new token if needed

2. **Ocp-Apim-Subscription-Key**: Header required for both OAuth and API requests
   - Set in `OCP_APIM_SUBSCRIPTION_KEY` variable in the script
   - Required for both token endpoint and data endpoint

## Troubleshooting

- **401 Access Denied**: 
  - Check your `Ocp-Apim-Subscription-Key` is correct
  - Verify OAuth endpoint is accessible
  - If OAuth requires client_id/client_secret, set them in the script
  
- **API Error**: Check your API parameters (operatingCompany, cycleCode, accountNumber)
- **Database Error**: Ensure database is initialized (`python init_database.py`)
- **Connection Error**: Check internet connection and API endpoint availability
- **Token Expired**: The script will automatically fetch a new token if the current one expires
