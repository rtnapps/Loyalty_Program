#!/usr/bin/env python3
"""
skupos_server_debug_full.py

Fully instrumented SKUPOS replacement debug server.
- LISTEN on TCP (default 0.0.0.0:9000)
- Accepts POSLOYALTY-framed messages with binary prefix + XML payload(s)
- Very verbose debugging prints + file log
- Extracts fields to CSV
- Configurable duplicate responses and control-only ACKs
"""

import socket
import threading
import traceback
import re
import csv
from xml.etree import ElementTree as ET
from datetime import datetime
import os
import time
import random
import string
import zlib

# Import Tier 3 Rules Engine modules
import tier3_step1

# --------------------------
# Config
# --------------------------
# HOST = "0.0.0.0"
HOST = '192.168.41.103'
PORT = 9000
# PORT = 8000


LOG_FILE = "skupos_server_debug_full.log"
CSV_FILE = "skupos_server_parsed_full.csv"

# Exact frame format based on SKUPOS application log analysis:
# Header is ALWAYS 28 bytes before payload, with CRC32 checksums.
#   signature (12): b"POSLOYALTY\x00\x00"
#   action    (4):  little-endian uint32 (usually 1)
#   dataLength(4):  little-endian uint32 (payload length in bytes)
#   checkSumData (4): little-endian uint32 = CRC32(payload_bytes)
#   checkSumHeader(4): little-endian uint32 = CRC32(header_bytes[0:24])  # up to and including checkSumData
# Then payload bytes (often XML, sometimes plain text like "Not Found").
FRAME_SIGNATURE = b"POSLOYALTY\x00\x00"
FRAME_ACTION = 1

# Behavioral toggles
# Note: SKUPOS typically writes one response; in some cases it appears to write twice.
# Keep this off by default for POS compatibility, enable only if your POS needs it.
DUPLICATE_RESPONSES = False    # send duplicates for responses (rare; mimic observed occasional double replies)
DUPLICATE_COUNT = 2           # number of times to send duplicate frames when enabled
REPLY_TO_CONTROL_ONLY = False # if True, reply to payloads that contain no '<' (control-only)

# Max buffer size to avoid runaway memory
MAX_BUFFER_BYTES = 20000
TRIM_TO_BYTES = 10000

# Dummy in-memory loyalty DB (replace with Mongo as needed)
LOYALTY_DB = {
    "5551239876": {"points": 100, "name": "Test Customer"},
    "9876543210": {"points": 250, "name": "Alice"},
}

# --------------------------
# Tier 3 Rules Engine - Step 1: Loyalty ID Validation
# --------------------------
# Step 1 is now implemented in tier3_step1.py module
# Import and use: tier3_step1.validate_loyalty_id()

# Ensure log file exists (append mode will create)
open(LOG_FILE, "a").close()

# Ensure CSV header exists
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "client_addr", "msg_type", "StoreLocationID",
            "POSTransactionID", "TenderAmount", "UPC", "Description"
        ])


# --------------------------
# Debug logging helper
# --------------------------
def dbg(msg):
    """Detailed logging - writes to file only, not console"""
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # best-effort logging
        pass


def console(msg):
    """Console output - shows clean messages in terminal"""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}")


def console_request(xml_text: str, client_addr):
    """Show clean request in terminal"""
    try:
        root = ET.fromstring(xml_text)
        tag = root.tag
        # Extract key info
        pos_seq = ""
        store_id = ""
        hdr = root.find(".//RequestHeader")
        if hdr is not None:
            p = hdr.find("POSSequenceID")
            if p is not None and p.text:
                pos_seq = p.text.strip()
            sl = hdr.find("StoreLocationID")
            if sl is not None and sl.text:
                store_id = sl.text.strip()
        
        # Show loyalty ID for GetRewardsRequest
        loyalty_id = ""
        if "GetRewards" in tag:
            lid = root.find(".//LoyaltyID")
            if lid is not None and lid.text:
                loyalty_id = f" | LoyaltyID: {lid.text.strip()}"
        
        console(f"⬇️  REQUEST: {tag} | Store: {store_id} | Seq: {pos_seq}{loyalty_id}")
    except Exception:
        # Fallback if parsing fails
        console(f"⬇️  REQUEST: {xml_text[:100]}...")


def console_response(xml_text: str, client_addr):
    """Show clean response in terminal"""
    try:
        root = ET.fromstring(xml_text)
        tag = root.tag
        # Extract key info
        pos_seq = ""
        hdr = root.find(".//ResponseHeader")
        if hdr is not None:
            p = hdr.find("POSSequenceID")
            if p is not None and p.text:
                pos_seq = p.text.strip()
        
        # Show special response info
        extra_info = ""
        if "GetLoyaltyOnlineStatusResponse" in tag:
            flag = root.find(".//PromptForLoyaltyFlag")
            if flag is not None:
                prompt = flag.attrib.get("value", "")
                extra_info = f" | Prompt: {prompt}"
        elif "GetRewardsResponse" in tag:
            rewards = root.findall(".//AddReward")
            if rewards:
                extra_info = f" | Rewards: {len(rewards)}"
        elif "FinalizeRewardsResponse" in tag:
            status = root.find(".//Status")
            if status is not None and status.text:
                extra_info = f" | Status: {status.text}"
        elif xml_text == "Not Found":
            tag = "Not Found"
        
        console(f"⬆️  RESPONSE: {tag} | Seq: {pos_seq}{extra_info}")
    except Exception:
        # Handle "Not Found" or other non-XML responses
        if xml_text == "Not Found":
            console(f"⬆️  RESPONSE: Not Found")
        else:
            console(f"⬆️  RESPONSE: {xml_text[:100]}...")


def log_message(direction, client_addr, server_addr, data_bytes):
    """
    Log message in network capture format matching SKUPOS log style:
    [timestamp] client_ip:port -> server_ip:port
    POSLOYALTY ... <XML>...
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    if direction == "IN":
        arrow = "->"
        src = f"{client_addr[0]}:{client_addr[1]}"
        dst = f"{server_addr[0]}:{server_addr[1]}"
    else:  # OUT
        arrow = "->"
        src = f"{server_addr[0]}:{server_addr[1]}"
        dst = f"{client_addr[0]}:{client_addr[1]}"
    
    # Convert bytes to readable format - match original SKUPOS log style
    # Control bytes 0x01, 0x02 should be visible, null bytes as spaces, other binary as dots
    readable = ""
    for byte in data_bytes:
        if byte == 0:
            readable += " "  # Null bytes as spaces
        elif byte == 1:
            readable += "\x01"  # Control byte 0x01 (will display as special char)
        elif byte == 2:
            readable += "\x02"  # Control byte 0x02 (will display as special char)
        elif 32 <= byte <= 126:  # Printable ASCII
            readable += chr(byte)
        else:
            readable += "."  # Other non-printable as dots
    
    # Try to extract XML portion for cleaner display
    xml_start = data_bytes.find(b"<")
    if xml_start != -1:
        # Show prefix + control bytes + XML (preserve binary bytes before XML)
        prefix_part = readable[:xml_start]
        xml_part = data_bytes[xml_start:].decode('utf-8', errors='ignore')
        display = prefix_part + xml_part
    else:
        display = readable
    
    log_line = f"--------------------------------------------------------------------------------\n"
    log_line += f"[{ts}] {src} {arrow} {dst}\n"
    log_line += f"{display}\n"
    log_line += f"--------------------------------------------------------------------------------\n"
    
    # Write to file only (detailed network capture format)
    # Console output is handled separately by console_request/console_response
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass



# --------------------------
# Payload cleaning & XML fragmentation
# --------------------------
def clean_xml_fragments(raw_bytes: bytes):
    """
    Heuristic: find first '<' and split the blob into likely XML messages using
    common top-level tags. Returns list of decoded XML strings.
    """
    dbg(f"clean_xml_fragments: RAW LEN={len(raw_bytes)}")
    dbg(f"clean_xml_fragments: RAW HEX PREVIEW: {raw_bytes[:200].hex()} ...")
    try:
        dbg(f"clean_xml_fragments: RAW ASCII PREVIEW: {raw_bytes[:200].decode('utf-8','ignore')}")
    except Exception:
        dbg("clean_xml_fragments: RAW ASCII PREVIEW decode failed")

    start = raw_bytes.find(b"<")
    if start == -1:
        dbg("clean_xml_fragments: NO '<' FOUND -> no XML in payload")
        return []

    if start > 0:
        dbg(f"clean_xml_fragments: Stripping {start} leading bytes before '<'")

    clean = raw_bytes[start:]
    dbg(f"clean_xml_fragments: Cleaned len={len(clean)}; bytes hex preview: {clean[:200].hex()}")

    # Split on top-level request/response tags we expect; include more tags if needed
    pattern = re.compile(
    rb'(?=<(?:GetLoyaltyOnlineStatusRequest|GetLoyaltyOnlineStatusResponse|BeginCustomerRequest|EndCustomerRequest|FinalizeRewardsRequest|FinalizeRewardsResponse|BeginCustomerResponse|EndCustomerResponse|PromptForLoyaltyFlag|GetRewardsRequest|GetRewardsResponse|CancelTransactionRequest|CancelTransactionResponse))'
    )
    # Fallback split regex: split where a top-level "<" appears that starts a known tag
    try:
        parts = pattern.split(clean)
    except re.error:
        # if pattern malfunction, simple split on '<' and re-add '<' for each fragment (less ideal)
        dbg("clean_xml_fragments: regex split failed; falling back to simple split")
        tmp = clean.split(b"<")
        parts = [b"<" + p for p in tmp if p.strip()]

    xmls = []
    for idx, p in enumerate(parts):
        p = p.strip()
        if not p:
            continue
        try:
            s = p.decode("utf-8", errors="ignore").strip()
            if s:
                # Filter out invalid XML fragments (too short or don't look like valid XML)
                # Valid XML should start with a known tag and be reasonably long
                if len(s) < 10:
                    dbg(f"clean_xml_fragments: Fragment[{idx}] too short ({len(s)} chars), skipping: {s[:50]}")
                    continue
                # Check if it starts with a known request/response tag
                known_tags = ["GetLoyaltyOnlineStatus", "GetRewards", "FinalizeRewards", 
                             "BeginCustomer", "EndCustomer", "CancelTransaction"]
                if not any(tag in s[:100] for tag in known_tags):
                    dbg(f"clean_xml_fragments: Fragment[{idx}] doesn't match known tags, skipping: {s[:100]}")
                    continue
                dbg(f"clean_xml_fragments: Fragment[{idx}] (len={len(s)}):\n{s[:1000]}")
                xmls.append(s)
        except Exception as e:
            dbg(f"clean_xml_fragments: decode fragment error: {e}")
            dbg(traceback.format_exc())
    return xmls


# --------------------------
# Field extraction from XML
# --------------------------
def extract_fields(xml_text: str):
    fields = {
        "msg_type": None,
        "StoreLocationID": "",
        "POSTransactionID": "",
        "TenderAmount": "",
        "UPC": "",
        "Description": "",
    }
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        dbg(f"extract_fields: XML ParseError: {e}")
        return fields
    except Exception as e:
        dbg(f"extract_fields: unexpected error: {e}")
        dbg(traceback.format_exc())
        return fields

    fields["msg_type"] = root.tag
    dbg(f"extract_fields: root.tag = {root.tag}")

    # RequestHeader -> StoreLocationID
    hdr = root.find(".//RequestHeader")
    if hdr is not None:
        sl = hdr.find("StoreLocationID")
        if sl is not None and sl.text:
            fields["StoreLocationID"] = sl.text.strip()
            dbg(f"extract_fields: StoreLocationID = {fields['StoreLocationID']}")

    # POSTransactionID
    ptrans = root.find(".//POSTransactionID")
    if ptrans is not None and ptrans.text:
        fields["POSTransactionID"] = ptrans.text.strip()
        dbg(f"extract_fields: POSTransactionID = {fields['POSTransactionID']}")

    # TenderAmount
    tender = root.find(".//TenderInfo/TenderAmount")
    if tender is not None and tender.text:
        fields["TenderAmount"] = tender.text.strip()
        dbg(f"extract_fields: TenderAmount = {fields['TenderAmount']}")

    # UPC
    upc = root.find(".//ItemCode/POSCode")
    if upc is not None and upc.text:
        fields["UPC"] = upc.text.strip()
        dbg(f"extract_fields: UPC = {fields['UPC']}")

    # Description
    desc = root.find(".//Description")
    if desc is not None and desc.text:
        fields["Description"] = desc.text.strip()
        dbg(f"extract_fields: Description = {fields['Description']}")

    return fields




# --------------------------
# Utility helpers
# --------------------------
def generate_loyalty_sequence_id():
    """
    Generate a unique LoyaltySequenceID (mimics SKUPOS format like 'wSh8W6_3y' or 'XJLLZLaPq').
    Format varies: sometimes has dash/underscore, sometimes doesn't.
    """
    chars = string.ascii_letters + string.digits
    # Randomly choose format: with separator or without
    if random.random() < 0.5:
        # Format: XXXX-XXXXX or XXXX_XXXX
        sep = random.choice(['-', '_'])
        return ''.join(random.choice(chars) for _ in range(3)) + sep + ''.join(random.choice(chars) for _ in range(5))
    else:
        # Format: XXXXXXXXX (no separator, like 'XJLLZLaPq')
        return ''.join(random.choice(chars) for _ in range(9))


# --------------------------
# Response builders
# --------------------------
def build_get_loyalty_online_status_response(pos_seq_id: str, prompt_flag: bool):
    prompt = "yes" if prompt_flag else "no"
    xml = (
        f"<GetLoyaltyOnlineStatusResponse>"
        f"<ResponseHeader>"
        f"<POSLoyaltyInterfaceVersion>1.2</POSLoyaltyInterfaceVersion>"
        f"<VendorName>Gilbarco</VendorName>"
        f"<VendorModelVersion>12.23.03.02</VendorModelVersion>"
        f"<POSSequenceID>{pos_seq_id}</POSSequenceID>"
        f"<LoyaltySequenceID></LoyaltySequenceID>"
        f"</ResponseHeader>"
        f"<PromptForLoyaltyFlag value=\"{prompt}\"></PromptForLoyaltyFlag>"
        f"</GetLoyaltyOnlineStatusResponse>"
    )
    return xml


def build_finalize_rewards_response(success=True):
    if success:
        return "<FinalizeRewardsResponse><ResponseHeader><Status>Success</Status></ResponseHeader></FinalizeRewardsResponse>"
    else:
        return "Not Found"


def build_get_rewards_response(pos_seq_id: str, loyalty_id: str, rewards: list, loyalty_seq_id: str = None, remove_rewards: list = None):
    """
    Build GetRewardsResponse XML.
    rewards: list of dicts with keys: reward_id, value, target_line, discount_method (for AddReward)
    loyalty_seq_id: Optional LoyaltySequenceID to reuse from request. If None, generates new one.
    remove_rewards: list of reward IDs to include as RemoveReward
    """
    if loyalty_seq_id is None:
        loyalty_seq_id = generate_loyalty_sequence_id()
    
    reward_actions = ""
    
    # Add RemoveReward actions first (if any)
    if remove_rewards:
        for reward_id in remove_rewards:
            reward_actions += f"<RemoveReward><LoyaltyRewardID>{reward_id}</LoyaltyRewardID></RemoveReward>"
    
    # Add AddReward actions
    for reward in rewards:
        reward_id = reward.get("reward_id", "")
        value = reward.get("value", "0")
        target_line = reward.get("target_line", "1")
        discount_method = reward.get("discount_method", "amountOff")
        instant = reward.get("instant", True)
        limit_type = reward.get("limit_type", "quantity")
        limit_value = reward.get("limit_value", "1")
        short_desc = reward.get("short_desc", "LOYALTY REWARD")
        long_desc = reward.get("long_desc", "LOYALTY REWARD")
        
        instant_flag = "yes" if instant else "no"
        reward_actions += (
            f"<AddReward>"
            f"<LoyaltyRewardID>{reward_id}</LoyaltyRewardID>"
            f"<InstantRewardFlag value=\"{instant_flag}\"></InstantRewardFlag>"
            f"<RewardTargetLineNumber>{target_line}</RewardTargetLineNumber>"
            f"<RewardDiscountMethod>{discount_method}</RewardDiscountMethod>"
            f"<RewardValue>{value}</RewardValue>"
            f"<RewardLimit type=\"{limit_type}\">{limit_value}</RewardLimit>"
            f"<RewardReceiptDescShort>{short_desc}</RewardReceiptDescShort>"
            f"<RewardReceiptDescLong>{long_desc}</RewardReceiptDescLong>"
            f"</AddReward>"
        )
    
    xml = (
        f"<GetRewardsResponse>"
        f"<ResponseHeader>"
        f"<POSLoyaltyInterfaceVersion>1.2</POSLoyaltyInterfaceVersion>"
        f"<VendorName>Gilbarco</VendorName>"
        f"<VendorModelVersion>12.23.03.02</VendorModelVersion>"
        f"<POSSequenceID>{pos_seq_id}</POSSequenceID>"
        f"<LoyaltySequenceID>{loyalty_seq_id}</LoyaltySequenceID>"
        f"</ResponseHeader>"
        f"<LoyaltyIDValidFlag value=\"yes\">{loyalty_id}</LoyaltyIDValidFlag>"
        f"<RewardActions>{reward_actions}</RewardActions>"
        f"</GetRewardsResponse>"
    )
    return xml


def build_cancel_transaction_response(pos_seq_id: str):
    """Build CancelTransactionResponse XML"""
    xml = (
        f"<CancelTransactionResponse>"
        f"<ResponseHeader>"
        f"<POSLoyaltyInterfaceVersion>1.2</POSLoyaltyInterfaceVersion>"
        f"<VendorName>Gilbarco</VendorName>"
        f"<VendorModelVersion>12.23.03.02</VendorModelVersion>"
        f"<POSSequenceID>{pos_seq_id}</POSSequenceID>"
        f"</ResponseHeader>"
        f"</CancelTransactionResponse>"
    )
    return xml


def build_generic_ok(tag):
    return f"<{tag}Response><ResponseHeader><Status>OK</Status></ResponseHeader></{tag}Response>"


# --------------------------
# Framing and sending helpers
# --------------------------
def frame_response_bytes(xml_payload: str):
    """
    Return framed bytes matching exact SKUPOS format from application log analysis.
    Format:
      POSLOYALTY\\x00\\x00 (12) +
      action (4, LE uint32) +
      dataLength (4, LE uint32) +
      checkSumData (4, LE uint32 = CRC32(payload)) +
      checkSumHeader (4, LE uint32 = CRC32(header[:24])) +
      payload bytes (XML or plain text like 'Not Found')
    
    If DUPLICATE_RESPONSES is enabled, caller should be prepared to receive a list of identical frames.
    """
    dbg("frame_response_bytes: framing payload...")
    payload_bytes = xml_payload.encode("utf-8")
    payload_len = len(payload_bytes)

    # CRC32 of payload
    checksum_data = zlib.crc32(payload_bytes) & 0xFFFFFFFF

    header_24 = (
        FRAME_SIGNATURE +
        int(FRAME_ACTION).to_bytes(4, byteorder="little", signed=False) +
        int(payload_len).to_bytes(4, byteorder="little", signed=False) +
        int(checksum_data).to_bytes(4, byteorder="little", signed=False)
    )
    checksum_header = zlib.crc32(header_24) & 0xFFFFFFFF

    framed = header_24 + int(checksum_header).to_bytes(4, byteorder="little", signed=False) + payload_bytes

    dbg(f"frame_response_bytes: payload len={payload_len}, total frame len={len(framed)}, header=28 bytes")
    dbg(f"frame_response_bytes: action={FRAME_ACTION} checksum_data=0x{checksum_data:08x} checksum_header=0x{checksum_header:08x}")
    dbg(f"frame_response_bytes: framed len={len(framed)}; hex preview: {framed[:200].hex()} ...")
    try:
        dbg(f"frame_response_bytes: ascii preview: {framed[:200].decode('utf-8','ignore')}")
    except Exception:
        dbg("frame_response_bytes: ascii preview decode failed")
    if DUPLICATE_RESPONSES and DUPLICATE_COUNT > 1:
        return [framed] * DUPLICATE_COUNT
    return framed


# --------------------------
# Request-specific handlers
# --------------------------
def handle_get_loyalty_online_status(root: ET.Element):
    # extract POSSequenceID
    pos_seq = ""
    hdr = root.find(".//RequestHeader")
    if hdr is not None:
        p = hdr.find("POSSequenceID")
        if p is not None and p.text:
            pos_seq = p.text.strip()
    # Example logic: always prompt yes for this debug server (mirror logs)
    prompt = True
    dbg(f"handle_get_loyalty_online_status: POSSequenceID={pos_seq} prompt={prompt}")
    return build_get_loyalty_online_status_response(pos_seq, prompt)


def handle_get_rewards(root: ET.Element):
    """
    Handle GetRewardsRequest - calculate and return rewards for a transaction.
    Extracts loyalty ID and transaction details, then calculates applicable rewards.
    Matches SKUPOS behavior: reuses LoyaltySequenceID from request, and includes
    RemoveReward if reward was already applied.
    
    Now includes Step 1: Loyalty ID validation per Tier 3 requirements.
    """
    # Extract POSSequenceID
    pos_seq = ""
    loyalty_seq_id_request = None
    store_id = ""
    hdr = root.find(".//RequestHeader")
    if hdr is not None:
        p = hdr.find("POSSequenceID")
        if p is not None and p.text:
            pos_seq = p.text.strip()
        # Extract StoreLocationID for validation context
        sl = hdr.find("StoreLocationID")
        if sl is not None and sl.text:
            store_id = sl.text.strip()
        # Extract LoyaltySequenceID from request (may be reused from previous response)
        ls = hdr.find("LoyaltySequenceID")
        if ls is not None and ls.text and ls.text.strip():
            loyalty_seq_id_request = ls.text.strip()
    
    # Extract LoyaltyID
    loyalty_id_elem = root.find(".//LoyaltyID")
    loyalty_id = ""
    if loyalty_id_elem is not None and loyalty_id_elem.text:
        loyalty_id = loyalty_id_elem.text.strip()
    
    dbg(f"handle_get_rewards: POSSequenceID={pos_seq}, LoyaltyID={loyalty_id}, StoreID={store_id}, LoyaltySequenceID={loyalty_seq_id_request}")
    
    # ============================================
    # STEP 1: Validate the Loyalty ID (CID/LID)
    # ============================================
    validation_result = tier3_step1.validate_loyalty_id(loyalty_id, store_id, logger=dbg)
    
    # If LoyaltyID is missing or invalid → return "No loyalty" response (no Tier 3 benefits)
    if not validation_result["valid"]:
        dbg(f"handle_get_rewards: Step 1 validation failed - {validation_result['reason']}")
        console(f"⚠️  VALIDATION: {validation_result['reason']} - No Tier 3 benefits")
        # Return empty rewards response (no Tier 3 benefits)
        return build_get_rewards_response(pos_seq, loyalty_id, [], loyalty_seq_id_request, None)
    
    # Log validation result
    if validation_result["is_manager_card"]:
        console(f"⚠️  VALIDATION: Manager/store card detected ({validation_result['daily_count']} transactions today) - CID fund ineligible")
    elif not validation_result["eligible_for_cid_fund"]:
        console(f"⚠️  VALIDATION: Daily cap reached - CID fund ineligible for this transaction")
    else:
        console(f"✅ VALIDATION: LoyaltyID valid - Tier 3 eligible, CID fund eligible")
    
    dbg(f"handle_get_rewards: Step 1 validation passed - valid={validation_result['valid']}, tier3_eligible={validation_result['eligible_for_tier3']}, cid_eligible={validation_result['eligible_for_cid_fund']}")
    
    # Check if transaction already has a Promotion with LoyaltyRewardID (reward already applied)
    # This happens when POS sends a second GetRewardsRequest with the same LoyaltySequenceID
    existing_reward_ids = []
    promotions = root.findall(".//Promotion[@status='normal']")
    for promo in promotions:
        lrid_elem = promo.find("LoyaltyRewardID")
        if lrid_elem is not None and lrid_elem.text and lrid_elem.text.strip():
            existing_reward_id = lrid_elem.text.strip()
            # Check if this promotion has reason="loyaltyOffer" (loyalty reward)
            reason_elem = promo.find("PromotionReason")
            if reason_elem is not None and reason_elem.text and "loyalty" in reason_elem.text.lower():
                existing_reward_ids.append(existing_reward_id)
                dbg(f"handle_get_rewards: Found existing loyalty reward {existing_reward_id} in transaction")
    
    # Extract transaction details for reward calculation
    transaction_lines = root.findall(".//TransactionLine/ItemLine")
    rewards = []
    remove_rewards = []
    
    # If we found existing rewards and have a LoyaltySequenceID from request, 
    # we should return RemoveReward + AddReward (matching SKUPOS behavior)
    if existing_reward_ids and loyalty_seq_id_request:
        remove_rewards = existing_reward_ids
        dbg(f"handle_get_rewards: Will include RemoveReward for existing rewards: {remove_rewards}")
    
    # Reward logic: Only apply rewards if validation passed (Step 1)
    # Note: validation_result["valid"] is already True at this point (we returned early if not)
    # Continue with reward calculation for validated LIDs
    if validation_result["eligible_for_tier3"]:
        if transaction_lines:
            # Find the first transaction line number
            line_num_elem = None
            for tx_line in root.findall(".//TransactionLine"):
                if tx_line.find("ItemLine") is not None:
                    line_num_elem = tx_line.find("LineNumber")
                    break
            
            line_number = "1"
            if line_num_elem is not None and line_num_elem.text:
                line_number = line_num_elem.text.strip()
            
            # Use existing reward ID if found, otherwise generate new one
            # SKUPOS seems to use format like "1421-1-B2_S150" or similar
            if existing_reward_ids:
                reward_id = existing_reward_ids[0]  # Reuse the existing reward ID
            else:
                reward_id = f"{line_number}-1-B2_S150"  # Consistent format matching logs
            
            rewards.append({
                "reward_id": reward_id,
                # "value": "1.5",  # $1.50 discount
                "value": "0.97",  # $0.97 discount
                "target_line": line_number,
                "discount_method": "amountOff",
                "instant": True,
                "limit_type": "quantity",
                "limit_value": "1",
                # "short_desc": "LOYALTY REWARD",
                "short_desc": "RTN LOYALTY REWARD",
                # "long_desc": "LOYALTY REWARD"
                "long_desc": "RTN LOYALTY REWARD"
            })
            dbg(f"handle_get_rewards: Generated reward {reward_id} for line {line_number}")
        else:
            dbg("handle_get_rewards: No transaction lines found, no rewards")
    else:
        dbg(f"handle_get_rewards: Tier 3 not eligible - no rewards")
    
    return build_get_rewards_response(pos_seq, loyalty_id, rewards, loyalty_seq_id_request, remove_rewards if remove_rewards else None)


def handle_finalize_rewards(root: ET.Element):
    # Heuristic: if LoyaltyOfflineFlag="yes" and no loyalty id, return Not Found (match logs)
    offline_flag = root.find(".//LoyaltyOfflineFlag")
    offline_yes = False
    if offline_flag is not None and offline_flag.attrib.get("value", "").lower() == "yes":
        offline_yes = True
    # Look for LoyaltyRewardID (or similar tags)
    lrid = root.find(".//LoyaltyRewardID")
    has_loyalty_id = lrid is not None and (lrid.text and lrid.text.strip())
    dbg(f"handle_finalize_rewards: offline_yes={offline_yes}, has_loyalty_id={bool(has_loyalty_id)}")
    if offline_yes and not has_loyalty_id:
        dbg("handle_finalize_rewards: returning Not Found (offline with no loyalty id)")
        return build_finalize_rewards_response(success=False)
    # Otherwise success
    dbg("handle_finalize_rewards: returning Success")
    return build_finalize_rewards_response(success=True)


def handle_cancel_transaction(root: ET.Element):
    """Handle CancelTransactionRequest"""
    pos_seq = ""
    hdr = root.find(".//RequestHeader")
    if hdr is not None:
        p = hdr.find("POSSequenceID")
        if p is not None and p.text:
            pos_seq = p.text.strip()
    dbg(f"handle_cancel_transaction: POSSequenceID={pos_seq}")
    return build_cancel_transaction_response(pos_seq)


# --------------------------
# Client handler
# --------------------------
def handle_client(conn: socket.socket, addr):
    console(f"🔌 NEW CONNECTION from {addr[0]}:{addr[1]}")
    dbg(f"=== NEW CONNECTION from {addr} ===")
    buffer = b""
    try:
        request_count = 0
        while True:
            dbg(f"=== LOOP ITERATION: Waiting for request #{request_count + 1} ===")
            try:
                data = conn.recv(4096)
                dbg(f"recv() returned {len(data) if data else 0} bytes")
            except socket.timeout:
                dbg("socket.timeout in recv() (no data for 60s) -> closing connection")
                # POS might have finished or connection is dead
                break
            except Exception as e:
                dbg(f"recv() exception: {e}")
                dbg(traceback.format_exc())
                break

            if not data:
                dbg("Client closed connection (zero-length recv)")
                break

            request_count += 1
            dbg(f"RECV {len(data)} bytes from {addr} (request #{request_count})")
            
            # Log incoming message in network format
            if data:
                server_addr = (HOST, PORT)
                log_message("IN", addr, server_addr, data)

            if not data:
                dbg("Client closed connection (zero-length recv)")
                break

            buffer += data
            dbg(f"BUFFER size now: {len(buffer)} bytes")

            # Guard buffer growth
            if len(buffer) > MAX_BUFFER_BYTES:
                dbg(f"Buffer exceeded {MAX_BUFFER_BYTES} bytes; trimming to last {TRIM_TO_BYTES} bytes")
                buffer = buffer[-TRIM_TO_BYTES:]

            # Try to find XML fragments
            xml_list = clean_xml_fragments(buffer)
            dbg(f"Found {len(xml_list)} XML fragments in buffer")

            # Handle control-only (no xml) scenario
            if not xml_list:
                dbg("No XML fragments found in buffer.")
                # Log empty/control-only messages
                if buffer:
                    server_addr = (HOST, PORT)
                    log_message("IN", addr, server_addr, buffer)
                if REPLY_TO_CONTROL_ONLY:
                    dbg("REPLY_TO_CONTROL_ONLY enabled -> sending small framed ACK")
                    ack_payload = ""  # empty payload; you can change to a specific string if needed
                    frames = frame_response_bytes(ack_payload)
                    server_addr = (HOST, PORT)
                    if isinstance(frames, list):
                        for i, fr in enumerate(frames, start=1):
                            dbg(f"Sending duplicate control-only ACK {i}/{len(frames)} ({len(fr)} bytes)")
                            conn.sendall(fr)
                            log_message("OUT", addr, server_addr, fr)
                            time.sleep(0.005)
                    else:
                        dbg(f"Sending single control-only ACK ({len(frames)} bytes)")
                        conn.sendall(frames)
                        log_message("OUT", addr, server_addr, frames)
                # continue reading more data
                continue

            # Process each XML fragment
            for xml_text in xml_list:
                dbg(f"--- PROCESSING XML FRAGMENT START ---\n{xml_text[:3000]}\n--- PROCESSING XML FRAGMENT END ---")
                fields = extract_fields(xml_text)
                dbg(f"Extracted fields: {fields}")

                # Append to CSV
                try:
                    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            datetime.now().isoformat(),
                            f"{addr}",
                            fields.get("msg_type"),
                            fields.get("StoreLocationID"),
                            fields.get("POSTransactionID"),
                            fields.get("TenderAmount"),
                            fields.get("UPC"),
                            fields.get("Description"),
                        ])
                        dbg("Wrote parsed row to CSV")
                except Exception as e:
                    dbg(f"Failed to write CSV row: {e}")
                    dbg(traceback.format_exc())

                # Try to parse XML element tree to route the request
                try:
                    root = ET.fromstring(xml_text)
                except ET.ParseError:
                    dbg("ET.ParseError while routing; will send Not Found mimic")
                    response_payload = "Not Found"
                else:
                    tag = root.tag
                    dbg(f"Routing based on tag: {tag}")
                    # Route to handlers (match by tag or substring)
                    if tag.endswith("GetLoyaltyOnlineStatusRequest") or "GetLoyaltyOnlineStatusRequest" in tag:
                        response_payload = handle_get_loyalty_online_status(root)
                    elif tag.endswith("GetRewardsRequest") or "GetRewardsRequest" in tag:
                        response_payload = handle_get_rewards(root)
                    elif tag.endswith("FinalizeRewardsRequest") or "FinalizeRewardsRequest" in tag:
                        response_payload = handle_finalize_rewards(root)
                    elif tag.endswith("CancelTransactionRequest") or "CancelTransactionRequest" in tag:
                        response_payload = handle_cancel_transaction(root)
                    elif tag.endswith("BeginCustomerRequest") or "BeginCustomerRequest" in tag:
                        # SKUPOS log shows: "No response required for request type..."
                        # Do NOT write anything to socket for this request.
                        dbg("BeginCustomerRequest: no response required (SKUPOS behavior)")
                        console("⬆️  RESPONSE: (none) BeginCustomerRequest (SKUPOS: no response required)")
                        response_payload = None
                    elif tag.endswith("EndCustomerRequest") or "EndCustomerRequest" in tag:
                        # SKUPOS log shows: "No response required for request type..."
                        # Do NOT write anything to socket for this request.
                        dbg("EndCustomerRequest: no response required (SKUPOS behavior)")
                        console("⬆️  RESPONSE: (none) EndCustomerRequest (SKUPOS: no response required)")
                        response_payload = None
                    else:
                        dbg(f"No specific handler for tag '{tag}'. Sending generic OK.")
                        # generic ack
                        stripped_tag = tag.replace("Request", "") if tag.endswith("Request") else tag
                        response_payload = build_generic_ok(stripped_tag)

                if response_payload is None:
                    dbg("No response payload (intentional) -> skipping socket write")
                    continue

                # Show clean response in terminal (before framing)
                console_response(response_payload, addr)

                # Frame and send; frame_response_bytes may return bytes or list of bytes
                frames_or_bytes = frame_response_bytes(response_payload)
                server_addr = (HOST, PORT)
                if isinstance(frames_or_bytes, list):
                    dbg(f"Prepared {len(frames_or_bytes)} duplicate frames to send")
                    for i, frame in enumerate(frames_or_bytes, start=1):
                        try:
                            dbg(f"Sending duplicate {i}/{len(frames_or_bytes)} ({len(frame)} bytes) to {addr}")
                            conn.sendall(frame)
                            # Log outgoing message in network format
                            log_message("OUT", addr, server_addr, frame)
                            dbg(f"Sent duplicate {i}")
                            # mimic small timing gap seen in some logs
                            time.sleep(0.01)
                        except Exception as e:
                            dbg(f"Error while sending duplicate {i}: {e}")
                            dbg(traceback.format_exc())
                else:
                    try:
                        dbg(f"Sending single frame ({len(frames_or_bytes)} bytes) to {addr}")
                        conn.sendall(frames_or_bytes)
                        # Log outgoing message in network format
                        log_message("OUT", addr, server_addr, frames_or_bytes)
                        dbg("Send complete")
                    except Exception as e:
                        dbg(f"Error sending frame: {e}")
                        dbg(traceback.format_exc())

            # After processing fragments, clear buffer (we assume fragments correspond to complete messages)
            # But keep connection open for next request - POS may send multiple requests on same connection
            # NOTE: BeginCustomerRequest only comes when a customer transaction starts on the POS.
            # It is NOT automatic after GetLoyaltyOnlineStatusResponse - the POS waits for a transaction.
            dbg("Clearing buffer after processing fragments (keeping connection open for next request)")
            buffer = b""
            # Continue loop to wait for next request from POS
            dbg("Waiting for next request on same connection... (BeginCustomerRequest will come when transaction starts)")
            # Check if socket is still connected by trying a peek (non-blocking check would be better, but this works)
            try:
                # Small delay to let POS process our response
                time.sleep(0.1)
            except Exception:
                pass

    except Exception as e:
        dbg(f"EXCEPTION in handle_client: {e}")
        dbg(traceback.format_exc())
    finally:
        try:
            conn.close()
        except Exception:
            pass
        console(f"🔌 CONNECTION CLOSED for {addr[0]}:{addr[1]}")
        dbg(f"=== CONNECTION CLOSED for {addr} ===")


# --------------------------
# Server bootstrap
# --------------------------
def start_server(host=HOST, port=PORT):
    dbg(f"Starting SKUPOS DEBUG FULL server on {host}:{port}")
    # Cleanup old daily counts on startup
    tier3_step1.cleanup_old_daily_counts(logger=dbg)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(50)
    dbg("Server listening; waiting for incoming POS connections...")
    console("✅ Tier 3 Rules Engine - Step 1: Loyalty ID Validation enabled")

    try:
        while True:
            try:
                conn, addr = s.accept()
                # Set a longer timeout - POS may wait between requests
                # Original SKUPOS keeps connections open for multiple requests
                conn.settimeout(60)  # Increased from 10 to 60 seconds
                # Enable TCP keepalive to detect dead connections
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
                t.start()
            except KeyboardInterrupt:
                dbg("KeyboardInterrupt received -> shutting down server")
                break
            except Exception as e:
                dbg(f"Error accepting connection: {e}")
                dbg(traceback.format_exc())
                # continue accepting other connections
    finally:
        try:
            s.close()
        except Exception:
            pass
        dbg("Server socket closed. Exiting.")


if __name__ == "__main__":
    start_server()