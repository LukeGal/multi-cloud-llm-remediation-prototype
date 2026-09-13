import time
import csv
import os  # Integrated to safely check disk state before initializing headers
import requests
from datetime import datetime
import subprocess
import re
import json

# ==========================================
# 1. TARGET LEDGER INITIALIZATION
# ==========================================
OUTPUT_FILE = "tri_cloud_latency_metrics.csv"
CONFIG_PATH = "active_endpoints.json"
DELAY_BETWEEN_REQUESTS = 3 # Seconds

def bootstrap_live_endpoints():
    """Queries live deployment state at execution startup to build a zero-hardcoded target registry."""
    print("[BOOTSTRAP] Mapping tri-cloud landscape dynamically. Interrogating state files...")
    endpoints = {}
    
    # Query AWS Declarative State Table
    res_aws = subprocess.run('terraform state show aws_instance.aws_free_vm', shell=True, capture_output=True, text=True)
    match_aws = re.search(r'public_ip\s+=\s*"([^"]+)"', res_aws.stdout)
    endpoints["aws"] = match_aws.group(1) if match_aws else "0.0.0.0"
    
    # Query Azure Declarative State Table (Unified to prevent name space resource drift)
    res_az = subprocess.run('terraform state show azurerm_linux_virtual_machine.azure_free_vm', shell=True, capture_output=True, text=True)
    match_az = re.search(r'public_ip_address\s+=\s*"([^"]+)"', res_az.stdout)
    endpoints["azure"] = match_az.group(1) if match_az else "0.0.0.0"
    
    # Query GCP Declarative State Table
    res_gcp = subprocess.run('terraform state show google_compute_instance.gcp_free_vm', shell=True, capture_output=True, text=True)
    match_gcp = re.search(r'nat_ip\s+=\s*"([^"]+)"', res_gcp.stdout)
    endpoints["gcp"] = match_gcp.group(1) if match_gcp else "0.0.0.0"
    
    return endpoints

# Force dynamic mapping synchronization at startup to prevent stale cache file drift
current_endpoints = {"aws": "0.0.0.0", "azure": "0.0.0.0", "gcp": "0.0.0.0"}
try:
    # Always poll live cloud fabrics on startup for absolute data integrity
    current_endpoints = bootstrap_live_endpoints()
    with open(CONFIG_PATH, "w") as f:
        json.dump(current_endpoints, f, indent=4)
    print(f"[SYSTEM] Central topology registry synchronized successfully: {CONFIG_PATH}")
except Exception as e:
    print(f"[!] Live Discovery Failed: {e}. Attempting local disk recovery fallback...")
    if os.path.exists(CONFIG_PATH) and os.path.getsize(CONFIG_PATH) > 0:
        try:
            with open(CONFIG_PATH, "r") as f:
                current_endpoints = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

# Establish baseline targets for the initial system greeting
AWS_URL   = f"http://{current_endpoints.get('aws', '0.0.0.0').strip()}"
AZURE_URL = f"http://{current_endpoints.get('azure', '0.0.0.0').strip()}"
GCP_URL   = f"http://{current_endpoints.get('gcp', '0.0.0.0').strip()}"

# ==========================================
# 2. FILE INITIALIZATION (Runs Once)
# ==========================================
file_exists = os.path.exists(OUTPUT_FILE)

if not file_exists:
    with open(OUTPUT_FILE, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "Timestamp",
            "AWS_Status", "AWS_Latency_ms",
            "Azure_Status", "Azure_Latency_ms",
            "GCP_Status", "GCP_Latency_ms"
        ])
    print(f"[SYSTEM] No existing log found. Created clean dataset file: {OUTPUT_FILE}")
else:
    print(f"[SYSTEM] Historical log detected. Safe mode active: Appending telemetry straight to {OUTPUT_FILE}")

print("=====================================================")
print("STARTING TRI-CLOUD TESTBED BENCHMARK (UNBUFFERED)")
print(f"AWS Target:   {AWS_URL}")
print(f"Azure Target: {AZURE_URL}")
print(f"GCP Target:   {GCP_URL}")
print("Press Ctrl + C to stop logging and save data.")
print("=====================================================\n")

request_count = 0

# ==========================================
# 3. CONTINUOUS MEASUREMENT LOOP
# ==========================================
try:
    while True:
        request_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # --- DYNAMIC TARGET RESOLUTION LAYER ---
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as config_file:
                    loaded_endpoints = json.load(config_file)
                    if isinstance(loaded_endpoints, dict):
                        AWS_URL   = f"http://{loaded_endpoints.get('aws', '0.0.0.0').strip()}"
                        AZURE_URL = f"http://{loaded_endpoints.get('azure', '0.0.0.0').strip()}"
                        GCP_URL   = f"http://{loaded_endpoints.get('gcp', '0.0.0.0').strip()}"
            except (json.JSONDecodeError, IOError):
                pass

        print(f"Cycle #{request_count} | [{timestamp}] Running Health Metrics Pings...")
        print(f"  Targeting -> AWS: {AWS_URL} | Azure: {AZURE_URL} | GCP: {GCP_URL}")

        # --- AWS Latency Measurement Block ---
        try:
            aws_start = time.time()
            aws_response = requests.get(AWS_URL, timeout=5)
            aws_latency = round((time.time() - aws_start) * 1000, 2)
            aws_status = aws_response.status_code
        except requests.RequestException:
            aws_status = 503
            aws_latency = -1.0
        print(f"  ├── AWS   -> Status: {aws_status} | Latency: {aws_latency}ms")

        # --- Azure Latency Measurement Block ---
        try:
            azure_start = time.time()
            azure_response = requests.get(AZURE_URL, timeout=5)
            azure_latency = round((time.time() - azure_start) * 1000, 2)
            azure_status = azure_response.status_code
        except requests.RequestException:
            azure_status = 503
            azure_latency = -1.0
        print(f"  ├── Azure -> Status: {azure_status} | Latency: {azure_latency}ms")

        # --- GCP Latency Measurement Block ---
        try:
            gcp_start = time.time()
            gcp_response = requests.get(GCP_URL, timeout=5)
            gcp_latency = round((time.time() - gcp_start) * 1000, 2)
            gcp_status = gcp_response.status_code
        except requests.RequestException:
            gcp_status = 503
            gcp_latency = -1.0
        print(f"  └── GCP   -> Status: {gcp_status} | Latency: {gcp_latency}ms")
        print("-" * 60)

        # --- FILE APPEND ENGINE ---
        with open(OUTPUT_FILE, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                timestamp, 
                aws_status, aws_latency, 
                azure_status, azure_latency, 
                gcp_status, gcp_latency
            ])

        time.sleep(DELAY_BETWEEN_REQUESTS)

except KeyboardInterrupt:
    print("\n=====================================================")
    print("COMPLETED: Tri-cloud telemetry collection halted.")
    print(f"Data safely finalized inside: {OUTPUT_FILE}")
    print("=====================================================")
