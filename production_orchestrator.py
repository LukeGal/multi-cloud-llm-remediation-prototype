import time
import csv
import os
import subprocess
import smtplib
from email.message import EmailMessage
from openai import OpenAI
import tkinter as tk
from tkinter import messagebox
import threading
import json
import re
from datetime import datetime

# --- Configuration & Local API Hooks ---
client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"  # Required by the library structure, but ignored locally by Ollama
)

MODEL_NAME = "qwen2.5-coder:7b"
ALLOWED_DECISIONS = {
    "CLEAR",
    "DESTROY_AWS",
    "DESTROY_AZURE",
    "DESTROY_GCP"
    }
CSV_FILE_PATH = "tri_cloud_latency_metrics.csv"  # Synced with benchmark output target
INCIDENT_LOG_PATH = "automation_audit_log.txt"
CONFIG_PATH = "active_endpoints.json"

AZURE_ADMIN_PASSWORD = os.environ.get("AZURE_ADMIN_PASSWORD")

if not AZURE_ADMIN_PASSWORD:
    raise RuntimeError(
        "AZURE_ADMIN_PASSWORD environment variable is not set."
    )

# Set to True to maintain the MFA-compliant native CLI fallback pathway
ENABLE_AZURE_HYBRID_FALLBACK = True

# --- Enterprise Alert Email Settings ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "doe958923@gmail.com"       # Test/alerts sender account
SENDER_PASSWORD = os.environ.get("ORCHESTRATOR_EMAIL_PASSWORD")   # Secure Gmail App Password

if not SENDER_PASSWORD:
    raise RuntimeError(
        "ORCHESTRATOR_EMAIL_PASSWORD environment variable is not set."
    )

RECEIVER_EMAIL = "galea.luke2210@gmail.com" # Primary admin inbox

# --- Provider-Specific Latency Baselines ---
# Healthy pre-load p95 latency derived from experimental telemetry
BASELINES_P95_MS = {
    "aws": 133.0565,
    "azure": 149.8660,
    "gcp": 130.2545
}

# Severe degradation requires latency to reach 2x healthy baseline p95
REMEDIATION_MULTIPLIER = 2.0

# Recovery must return to within 15% above healthy baseline p95
RECOVERY_TOLERANCE_MULTIPLIER = 1.15

# --- Autonomic Circuit Breaker Tracking ---
MAX_REMEDIATION_LIMIT = 1  # Limits live self-healing to 1 cycle per provider to protect the budget
remediation_counts = {"aws": 0, "azure": 0, "gcp": 0}
cloud_status = {"aws": "ACTIVE", "azure": "ACTIVE", "gcp": "ACTIVE"}

RECOVERY_SAMPLES_REQUIRED = 2

recovery_streak = {
    "aws": 0,
    "azure": 0,
    "gcp": 0
}

#T0 - When bad telemetry triggers remediation
incident_start_times = {
    "aws": None,
    "azure": None,
    "gcp": None
}

# =========================================================================
# SYSTEM UTILITIES & CONFIGURATION REGISTRY LAYER
# =========================================================================

def fetch_live_ip(provider):
    """
    Queries the active cloud fabric or local declarative state tables 
    to fetch the current running IP dynamically with no hardcoding.
    """
    try:
        if provider.lower() == "azure":
            cmd = 'az network public-ip show --resource-group "testbed-resources" --name "azure-vm-pip" --query "ipAddress" -o tsv'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        elif provider.lower() == "aws":
            cmd = 'terraform state show aws_instance.aws_free_vm'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            match = re.search(r'public_ip\s+=\s*"([^"]+)"', res.stdout)
            if match:
                return match.group(1)
        elif provider.lower() == "gcp":
            cmd = 'terraform state show google_compute_instance.gcp_free_vm'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            match = re.search(r'nat_ip\s+=\s*"([^"]+)"', res.stdout)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"[!] Live Discovery Warning: Unable to parse real-time state for {provider.upper()}: {e}")
    return "0.0.0.0"  # Safe network structural fallback

def update_active_endpoint(provider, new_ip):
    """Dynamically updates the shared single source of truth configuration ledger without mutating other targets."""
    endpoints = {}
    
    # 1. Ingest existing entries if the file is present
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as config_file:
                endpoints = json.load(config_file)
        except (json.JSONDecodeError, IOError):
            pass
            
    # 2. Dynamic Guardrail: If any sibling cloud provider keys are missing, discover them live
    for platform in ["aws", "azure", "gcp"]:
        if platform not in endpoints or endpoints[platform] == "0.0.0.0":
            print(f"[REGISTRY PRE-FLIGHT] Pulling missing baseline mapping for {platform.upper()} dynamically...")
            endpoints[platform] = fetch_live_ip(platform)
            
    # 3. Inject the newly self-healed instance endpoint parameters
    endpoints[provider.lower()] = new_ip
    
    try:
        with open(CONFIG_PATH, "w") as config_file:
            json.dump(endpoints, config_file, indent=4)
        print(f"  └─ [DYNAMIC REGISTRY] {provider.upper()} endpoint synchronized on disk: {new_ip}")
    except IOError as e:
        print(f"[!] Registry Update Exception: Failure writing to configuration ledger: {e}")

def show_destruction_popup(platform_name, latency_value):
    """Fires a graphical desktop warning popup in an isolated background thread."""
    def trigger():
        root = tk.Tk()
        root.withdraw() # Hides the blank main tkinter master window
        root.attributes("-topmost", True) # Forces the alert box to pop up over everything else
        
        # Adjust warning language dynamically based on governance rules
        alert_body = (
            f"CRITICAL REMEDIATION THRESHOLD BREACH DETECTED BY LOCAL AI!\n\n"
            f"Cloud Platform: {platform_name.upper()}\n"
            f"Observed Metric: {latency_value}ms\n\n"
            f"Action: Initiating live 'terraform apply -replace' autonomic protocol."
        )
        messagebox.showwarning("AUTONOMOUS POLICY ENGINE ALERT", alert_body)
        root.destroy()
        
    # Launch via threading to prevent freezing the main telemetry script execution
    threading.Thread(target=trigger, daemon=True).start()

def log_incident(event_type, message):
    """Securely writes operational anomalies and system errors to an unalterable audit file."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] [{event_type.upper()}] {message}\n"
    try:
        with open(INCIDENT_LOG_PATH, "a") as log_file:
            log_file.write(log_entry)
        print(f"  └─ [AUDIT LOCKED] Written to {INCIDENT_LOG_PATH}")
    except Exception as e:
        print(f"[Internal Logger Error] Failed to commit to disk: {e}")

def send_alert_email(provider, latency, status_code):
    """Dispatches a proactive automated email alert to the system administrator."""
    msg = EmailMessage()
    msg["Subject"] = f"CRITICAL ALERT: Remediation Threshold Breach Detected on {provider.upper()}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    action_text = (
        "Operational Action: The node has exceeded the configured remediation threshold. "
        "The system has initiated a scoped remediation sequence to isolate the affected "
        "cloud resource and restore the endpoint to its defined recovery state."
    )
    status_text = "Status: AUTONOMOUS REMEDIATION INITIATED"

    body = (
        f"Attention System Administrator,\n\n"
        f"This is an automated notification from your Local Agentic Cloud Orchestration Engine.\n\n"
        f"CRITICAL ANOMALY DETECTED:\n"
        f"---------------\n"
        f"Cloud Platform: {provider.upper()}\n"
        f"Observed Latency: {latency}ms\n"
        f"HTTP Status Code: {status_code}\n"
        f"---------------\n\n"
        f"{action_text}\n\n"
        f"Please inspect the local audit logs at: '{INCIDENT_LOG_PATH}' for full details.\n\n"
        f"{status_text}"
    )
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()  # Secure the connection using TLS
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        print(f"  └─ [EMAIL SENT] Proactive alert safely dispatched to {RECEIVER_EMAIL}")
    except Exception as e:
        error_msg = f"Email dispatch engine failure during {provider.upper()} breach: {e}"
        print(f"  └─ [ALERT FAILURE] {error_msg}")
        log_incident("ERROR", error_msg)

# =========================================================================
# TELEMETRY EVALUATION AND AI MODEL COGNITION LAYER
# =========================================================================

def ask_local_llm_to_evaluate(timestamp, aws, azure, gcp):
    """Queries your local Ollama instance to dynamically evaluate telemetry profiles."""
    system_prompt = (
            "You are a cloud optimization engineer evaluating multi-cloud node telemetry "
            "within a controlled test environment.\n"
            "Analyze the provided performance snapshot variables against active node statuses.\n"
            "Determine if any platform displays critical degradation signatures or severe latency deviations.\n"
           "Your response must be exactly one of the following strings, with no additional text, formatting, markdown, or punctuation:\n"
            "CLEAR\n"
            "DESTROY_AWS\n"
            "DESTROY_AZURE\n"
            "DESTROY_GCP"
    )
    
    user_data = (
        f"Snapshot Time: {timestamp}\n"
        f"Metrics -> AWS: {aws}ms | Azure: {azure}ms | GCP: {gcp}ms\n"
        f"Current Status: {cloud_status}"
    )

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_data}
            ],
            temperature=0.0  # Reduces sampling variability for more repeatable classification
        )
        
        decision = response.choices[0].message.content.strip().upper()

        if decision not in ALLOWED_DECISIONS:
            log_incident(
                "INVALID_AI_OUTPUT",
                f"Rejected unrecognised model output: {decision}"
            )
            return "INVALID"
        
        return decision
    
    except Exception as e:
        error_msg = f"Local Ollama connection lost or model failed: {e}"
        log_incident("ERROR", error_msg)
        return "MODEL_ERROR"

def validate_remediation_decision(provider, decision, latency, status_code):
    """
    Deterministically validates an LLM remediation recommendation
    against provider-specific telemetry thresholds before actuation.
    """

    expected_decision = f"DESTROY_{provider.upper()}"

    # Ensure the LLM action matches the provider being evaluated
    if decision != expected_decision:
        return False

    # Retrieve the provider-specific healthy baseline p95
    baseline_p95 = BASELINES_P95_MS[provider]

    # Calculate severe-degradation threshold dynamically
    remediation_threshold = baseline_p95 * REMEDIATION_MULTIPLIER

    # Deterministic failure conditions
    status_failure = status_code != 200
    timeout_failure = latency < 0
    latency_failure = latency >= remediation_threshold

    # Reject the LLM recommendation if telemetry does not confirm a breach
    if not status_failure and not timeout_failure and not latency_failure:
        log_incident(
            "SAFETY_GATE_REJECTION",
            f"Rejected {decision}: telemetry does not confirm a breach "
            f"(HTTP={status_code}, latency={latency}ms, "
            f"threshold={remediation_threshold:.2f}ms)."
        )

        print(
            f"    └─ [SAFETY GATE] Rejected {decision}: "
            f"{provider.upper()} latency {latency}ms is below "
            f"{remediation_threshold:.2f}ms and HTTP status is {status_code}."
        )

        return False

    print(
        f"    └─ [SAFETY GATE] {decision} independently validated "
        f"(HTTP={status_code}, latency={latency}ms, "
        f"threshold={remediation_threshold:.2f}ms)."
    )

    return True

# =========================================================================
# AUTONOMOUS CLOSED-LOOP REMEDIATION ENGINE
# =========================================================================

def is_recovery_verified(provider, latency, status_code):
    """
    Confirms that a remediated provider has returned to an acceptable
    application-level service state.
    """

    baseline_p95 = BASELINES_P95_MS[provider]
    recovery_threshold = (
        baseline_p95 * RECOVERY_TOLERANCE_MULTIPLIER
    )

    return (
        status_code == 200
        and latency >= 0
        and latency <= recovery_threshold
    )

def execute_autonomous_action(provider, target_resource, latency, status_code):
    """
    Executes a live, autonomous self-healing loop protected by an architectural circuit breaker.
    Handles cloud-specific dependencies, native API bypasses, and state synchronization.
    """
    # 1. State Guardrail
    if cloud_status[provider] != "ACTIVE":
        return False

    # 2. Budget Guardrail (Circuit Breaker Check)
    if remediation_counts[provider] >= MAX_REMEDIATION_LIMIT:
        trip_msg = f"CRITICAL: Circuit breaker tripped for {provider.upper()}. Maximum budget protection limit reached."
        print(f"\n[CIRCUIT BREAKER] {trip_msg}")
        log_incident("CIRCUIT_BREAKER_TRIPPED", trip_msg)
        cloud_status[provider] = "LOCKOUT"
        return False

    # Transition state to lock concurrent execution loops
    cloud_status[provider] = "HEALING"
    remediation_counts[provider] += 1

    alert_msg = f"Remediation threshold breach on {provider.upper()} ({latency}ms). Attempt {remediation_counts[provider]} of {MAX_REMEDIATION_LIMIT}. Processing alert pipeline."
    print(f"\n[LOCAL AGENT OPTIMIZATION] {alert_msg}")
    
    # Trigger warning GUI, commit audit logs, and dispatch administrator email
    show_destruction_popup(provider, latency)
    log_incident("HEALING_INITIATED", alert_msg)
    send_alert_email(provider, latency, status_code)
    
    # Baseline Declarative Command Strings
    destroy_cmd = f'terraform destroy -target="{target_resource}" -auto-approve'
    apply_cmd   = f'terraform apply -target="{target_resource}" -auto-approve'
    
    # =========================================================================
    # =========================================================================
    # HYBRID EXECUTION VECTOR FOR AZURE (MFA COMPLIANT Fallback Pathway)
    # =========================================================================
    if provider.lower() == "azure" and ENABLE_AZURE_HYBRID_FALLBACK:
        # --- Programmatic Networking Requirements Built In ---
        az_vnet_cmd = (
            'az network vnet create '
            '--resource-group "testbed-resources" '
            '--name "testbed-vnet" '
            '--address-prefixes "10.0.0.0/16" '
            '--subnet-name "testbed-subnet" '
            '--subnet-prefixes "10.0.1.0/24"'
        )
        az_pip_cmd = (
            'az network public-ip create '
            '--resource-group "testbed-resources" '
            '--name "azure-vm-pip" '
            '--sku "Standard" '
            '--allocation-method "Static" '
            '--location "spaincentral"'
        )
        az_nsg_cmd = (
            'az network nsg create '
            '--resource-group "testbed-resources" '
            '--name "azure-testbed-nsg" '
            '--location "spaincentral"'
        )
        az_nsg_rule_cmd = (
            'az network nsg rule create '
            '--resource-group "testbed-resources" '
            '--nsg-name "azure-testbed-nsg" '
            '--name "AllowTestingTrafficInbound" '
            '--priority 1000 '
            '--destination-port-ranges 80 443 22 '
            '--access Allow '
            '--protocol Tcp '
            '--direction Inbound'
        )
        az_nic_cmd = (
            'az network nic create '
            '--resource-group "testbed-resources" '
            '--name "azure-vm-nic" '
            '--vnet-name "testbed-vnet" '
            '--subnet "testbed-subnet" '
            '--public-ip-address "azure-vm-pip" '
            '--network-security-group "azure-testbed-nsg"'
        )
        # -----------------------------------------------------
        az_delete_cmd = 'az vm delete --resource-group "testbed-resources" --name "Testbed-Azure" --yes'
        
        # Patched Creation String incorporating dynamic provisioning scripts via custom-data
        az_create_cmd = (
            'az vm create '
            '--resource-group "testbed-resources" '
            '--name "Testbed-Azure" '
            '--image "Ubuntu2204" '
            '--size "Standard_B2s_v2" '
            '--admin-username "azureuser" '
            f'--admin-password "{AZURE_ADMIN_PASSWORD}" '
            '--nics "azure-vm-nic" '
            '--custom-data "azure_bootstrap.sh"'
        )
        az_import_cmd = (
            'terraform import azurerm_linux_virtual_machine.azure_free_vm '
            '/subscriptions/812c910c-bb86-4084-bcdc-8c674f2bc0ee/resourceGroups/testbed-resources/providers/Microsoft.Compute/virtualMachines/Testbed-Azure'
        )
        
        try:
            remediation_start = time.time()
            
            # Programmatically write the automated cloud-init bootstrap script to local disk execution space
            print("[AZURE PROVISIONER] Injecting automated software configuration manifests...")
            with open("azure_bootstrap.sh", "w", newline='\n') as bootstrap_file:
                bootstrap_file.write(
                    "#!/bin/bash\n"
                    "sudo apt-get update -y\n"
                    "sudo apt-get install apache2 -y\n"
                    "sudo systemctl enable apache2\n"
                    "sudo systemctl start apache2\n"
                    "echo 'Hello from Azure Spain' | sudo tee /var/www/html/index.html\n"
                )

            print(f"\n[AZURE MFA VECTOR] Executing physical teardown via state machine: {destroy_cmd}\n")
            subprocess.run(destroy_cmd, shell=True, check=True)
            
            print(f"[AZURE FALLBACK] Ensuring complete instance evacuation via native CLI...")
            subprocess.run(az_delete_cmd, shell=True, check=True)
            
            time.sleep(25)

            nic_check = subprocess.run('az network nic show --resource-group "testbed-resources" --name "azure-vm-nic"', shell=True, capture_output=True, text=True)
            if nic_check.returncode != 0:
                print(f"Provisioning VNet and Subnet parameters: {az_vnet_cmd}\n")
                subprocess.run(az_vnet_cmd, shell=True, check=True)
                
                print(f"Provisioning External Public IP Resource: {az_pip_cmd}\n")
                subprocess.run(az_pip_cmd, shell=True, check=True)
                
                print(f"Provisioning Network Security Group container: {az_nsg_cmd}\n")
                subprocess.run(az_nsg_cmd, shell=True, check=True)
                
                print(f"Injecting Inbound Allow Rules for Web/Telemetry: {az_nsg_rule_cmd}\n")
                subprocess.run(az_nsg_rule_cmd, shell=True, check=True)
                
                print(f"Provisioning Network Interface Card with Security Policies: {az_nic_cmd}\n")
                subprocess.run(az_nic_cmd, shell=True, check=True)
                print("[+] Networking security fabric successfully deployed.\n")
            
            print("[AZURE FALLBACK] Triggering provisioned emergency native CLI build...")
            subprocess.run(az_create_cmd, shell=True, check=True)

            # --- DYNAMIC AZURE IP DISCOVERY LAYER ---
            print("[AZURE OPTIMIZATION] Querying live regional boundary for newly allocated public interface...")
            ip_query_cmd = 'az network public-ip show --resource-group "testbed-resources" --name "azure-vm-pip" --query "ipAddress" -o tsv'
            ip_result = subprocess.run(ip_query_cmd, shell=True, capture_output=True, text=True, check=True)
            discovered_ip = ip_result.stdout.strip()
            update_active_endpoint("azure", discovered_ip)
            
            print(f"\n[AZURE LEDGER RECONCILIATION] Synchronizing state directory tables: {az_import_cmd}\n")
            subprocess.run(az_import_cmd, shell=True, check=True)
            
            # Clear the temporary script file from disk cleanly
            if os.path.exists("azure_bootstrap.sh"):
                os.remove("azure_bootstrap.sh")

            remediation_duration = round(time.time() - remediation_start, 2)
            print(f"\n[SUCCESS] Azure environment fully restored and provisioned.")
            log_incident("HEALING_SUCCESS", f"Azure node provisioned via Hybrid CLI-Import vector. Time: {remediation_duration}s")
            cloud_status[provider] = "RECOVERING"
            return True
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Azure Hybrid Recovery execution branch failed: {e}"
            print(f"[System Error] {error_msg}")
            log_incident("ERROR", error_msg)
            cloud_status[provider] = "DEGRADED"
            return False
            
    # =========================================================================
    # MULTI-CLOUD DECLARATIVE RECONSTITUTION ENGINE (AWS, GCP, & Standard Azure) 
    # =========================================================================
    try:
        print(f"\n[PHASE 1: LIVE DECOMMISSIONING STARTING]: {destroy_cmd}\n")
        remediation_start = time.time()
        
        # Execute total destruction of underperforming instance (streams live to console)
        subprocess.run(destroy_cmd, shell=True, check=True)

        print(f"[PHASE 2: LIVE RECONSTITUTION STARTING]: {apply_cmd}\n")

        subprocess.run(apply_cmd, shell=True, check=True)

        # --- DYNAMIC MULTI-CLOUD TELEMETRY ACQUISITION LAYER ---
        print(f"[{provider.upper()} OPTIMIZATION] Interrogating declarative state mappings for runtime endpoints...")
        state_cmd = f'terraform state show {target_resource}'
        state_result = subprocess.run(state_cmd, shell=True, capture_output=True, text=True, check=True)
        
        discovered_ip = None
        ip_match = None
        if provider.lower() == "aws":
            ip_match = re.search(r'public_ip\s+=\s*"([^"]+)"', state_result.stdout)
        elif provider.lower() == "gcp":
            ip_match = re.search(r'nat_ip\s+=\s*"([^"]+)"', state_result.stdout)
        elif provider.lower() == "azure":
            ip_match = re.search(r'public_ip_address\s+=\s*"([^"]+)"', state_result.stdout)
            
        if ip_match:
            discovered_ip = ip_match.group(1)
            update_active_endpoint(provider, discovered_ip)
        else:
            print(f"[!] Warning: Subprocess state parsing complete, but runtime IP attribute was null.")
        
        remediation_duration = round(time.time() - remediation_start, 2)
        
        print(f"\n[SUCCESS] Local loop successfully isolated and restored underperforming {provider.upper()} resource.")
        print(f"Total Lifecycle Multi-Cloud Overhead: {remediation_duration} seconds")
        
        success_msg = f"{provider.upper()} node fully cycled. Total Lifecycle Time: {remediation_duration}s"
        log_incident("HEALING_SUCCESS", success_msg)
        
        # Restore status to active for subsequent system monitoring cycles
        cloud_status[provider] = "RECOVERING"
        return True
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Two-phase execution pipeline collapsed while processing {provider.upper()}: {e}"
        print(f"[System Error] {error_msg}")
        log_incident("ERROR", error_msg)
        cloud_status[provider] = "DEGRADED"
        return False

# =========================================================================
# AUTONOMOUS PRE-FLIGHT STATE INGESTION ENGINE (ANTI SPLIT-BRAIN SHIELD)
# =========================================================================

def ingest_multi_cloud_network_state_preflight():
    """
    Autonomic Pre-Flight State Ingestion Engine for Azure, AWS, and GCP.
    Programmatically detects if network fabric components exist out-of-band across
    all active hypervisors and syncs them into the local Terraform state ledger.
    """
    # --- Multi-Cloud Environment Specifications ---
    azure_sub_id  = "812c910c-bb86-4084-bcdc-8c674f2bc0ee"
    azure_rg      = "testbed-resources"
    azure_vnet    = "testbed-vnet"
    azure_subnet  = "testbed-subnet"

    gcp_project   = "quick-hangout-477408-g8"
    gcp_region    = "europe-west3"
    gcp_network   = "testbed-network"
    gcp_subnet    = "testbed-subnet"

    aws_vpc_tag   = "testbed-vpc"
    aws_sub_tag   = "testbed-subnet"

    def is_tracked_by_terraform(resource_address):
        """Helper to determine if a resource address is already mapped in the local state table."""
        check_res = subprocess.run(
            f'terraform state show {resource_address}', 
            shell=True, capture_output=True, text=True
        )
        return check_res.returncode == 0

    print("\n=================================================================")
    print("[AUTONOMIC GUARD] Initializing Global Tri-Cloud Pre-Flight Sweep...")
    print("=================================================================")

    # -------------------------------------------------------------------------
    # LOGIC GATE 1: AZURE METADATA SYNC
    # -------------------------------------------------------------------------
    az_vnet_addr = "azurerm_virtual_network.testbed_vnet"
    if not is_tracked_by_terraform(az_vnet_addr):
        print(f"[-] {az_vnet_addr} untracked. Scanning Azure perimeter...")
        vnet_scan = subprocess.run(f'az network vnet show --resource-group "{azure_rg}" --name "{azure_vnet}"', shell=True, capture_output=True, text=True)
        if vnet_scan.returncode == 0:
            print(f"[!] Split-Brain Detected: Live VNet '{azure_vnet}' exists. Syncing ledger...")
            vnet_import_id = f"/subscriptions/{azure_sub_id}/resourceGroups/{azure_rg}/providers/Microsoft.Network/virtualNetworks/{azure_vnet}"
            try:
                subprocess.run(f'terraform import {az_vnet_addr} {vnet_import_id}', shell=True, check=True)
                log_incident("STATE_INGESTION", f"Programmatically imported untracked Azure VNet: {azure_vnet}")
            except subprocess.CalledProcessError:
                pass

    az_subnet_addr = "azurerm_subnet.testbed_subnet"
    if not is_tracked_by_terraform(az_subnet_addr):
        print(f"[-] {az_subnet_addr} untracked. Scanning Azure perimeter...")
        sub_scan = subprocess.run(f'az network subnet show --resource-group "{azure_rg}" --vnet-name "{azure_vnet}" --name "{azure_subnet}"', shell=True, capture_output=True, text=True)
        if sub_scan.returncode == 0:
            print(f"[!] Split-Brain Detected: Live Subnet '{azure_subnet}' exists. Syncing ledger...")
            sub_import_id = f"/subscriptions/{azure_sub_id}/resourceGroups/{azure_rg}/providers/Microsoft.Network/virtualNetworks/{azure_vnet}/subnets/{azure_subnet}"
            try:
                subprocess.run(f'terraform import {az_subnet_addr} {sub_import_id}', shell=True, check=True)
                log_incident("STATE_INGESTION", f"Programmatically imported untracked Azure Subnet: {azure_subnet}")
            except subprocess.CalledProcessError:
                pass

    # -------------------------------------------------------------------------
    # LOGIC GATE 2: AWS METADATA SYNC
    # -------------------------------------------------------------------------
    aws_vpc_addr = "aws_vpc.testbed_vpc"
    if not is_tracked_by_terraform(aws_vpc_addr):
        print(f"[-] {aws_vpc_addr} untracked. Scanning AWS perimeter...")
        vpc_query = subprocess.run(f'aws ec2 describe-vpcs --filters "Name=tag:Name,Values={aws_vpc_tag}" --query "Vpcs[0].VpcId" --output text', shell=True, capture_output=True, text=True)
        vpc_id = vpc_query.stdout.strip()
        if vpc_id and vpc_id != "None" and not vpc_id.startswith("An error"):
            print(f"[!] Split-Brain Detected: Live AWS VPC '{vpc_id}' exists. Syncing ledger...")
            try:
                subprocess.run(f'terraform import {aws_vpc_addr} {vpc_id}', shell=True, check=True)
                log_incident("STATE_INGESTION", f"Programmatically imported untracked AWS VPC: {vpc_id}")
            except subprocess.CalledProcessError:
                pass

    aws_sub_addr = "aws_subnet.testbed_subnet"
    if not is_tracked_by_terraform(aws_sub_addr):
        print(f"[-] {aws_subnet_addr} untracked. Scanning AWS perimeter...")
        sub_query = subprocess.run(f'aws ec2 describe-subnets --filters "Name=tag:Name,Values={aws_sub_tag}" --query "Subnets[0].SubnetId" --output text', shell=True, capture_output=True, text=True)
        subnet_id = sub_query.stdout.strip()
        if subnet_id and subnet_id != "None" and not subnet_id.startswith("An error"):
            print(f"[!] Split-Brain Detected: Live AWS Subnet '{subnet_id}' exists. Syncing ledger...")
            try:
                subprocess.run(f'terraform import {aws_sub_addr} {subnet_id}', shell=True, check=True)
                log_incident("STATE_INGESTION", f"Programmatically imported untracked AWS Subnet: {subnet_id}")
            except subprocess.CalledProcessError:
                pass

    # -------------------------------------------------------------------------
    # LOGIC GATE 3: GCP METADATA SYNC
    # -------------------------------------------------------------------------
    gcp_net_addr = "google_compute_network.testbed_network"
    if not is_tracked_by_terraform(gcp_net_addr):
        print(f"[-] {gcp_net_addr} untracked. Scanning GCP perimeter...")
        net_scan = subprocess.run(f'gcloud compute networks describe {gcp_network} --project={gcp_project} --format="value(name)"', shell=True, capture_output=True, text=True)
        if net_scan.returncode == 0 and net_scan.stdout.strip():
            print(f"[!] Split-Brain Detected: Live GCP Network '{gcp_network}' exists. Syncing ledger...")
            gcp_net_import = f"projects/{gcp_project}/global/networks/{gcp_network}"
            try:
                subprocess.run(f'terraform import {gcp_net_addr} {gcp_net_import}', shell=True, check=True)
                log_incident("STATE_INGESTION", f"Programmatically imported untracked GCP Network: {gcp_network}")
            except subprocess.CalledProcessError:
                pass

    gcp_sub_addr = "google_compute_subnetwork.testbed_subnetwork"
    if not is_tracked_by_terraform(gcp_sub_addr):
        print(f"[-] {gcp_sub_addr} untracked. Scanning GCP perimeter...")
        sub_scan = subprocess.run(f'gcloud compute networks subnets describe {gcp_subnet} --region={gcp_region} --project={gcp_project} --format="value(name)"', shell=True, capture_output=True, text=True)
        if sub_scan.returncode == 0 and sub_scan.stdout.strip():
            print(f"[!] Split-Brain Detected: Live GCP Subnetwork '{gcp_subnet}' exists. Syncing ledger...")
            gcp_sub_import = f"projects/{gcp_project}/regions/{gcp_region}/subnetworks/{gcp_subnet}"
            try:
                subprocess.run(f'terraform import {gcp_sub_addr} {gcp_sub_import}', shell=True, check=True)
                log_incident("STATE_INGESTION", f"Programmatically imported untracked GCP Subnetwork: {gcp_subnet}")
            except subprocess.CalledProcessError:
                pass

    print("=================================================================")
    print("[+] Global Pre-Flight Sweep Complete. System Parity Restored.")
    print("=================================================================\n")

print("=================================================================")
print("=== LOCALIZED AGENTIC MULTI-CLOUD ORCHESTRATOR PIPELINE ACTIVE ===")
print("=================================================================\n")

try:
    with open(INCIDENT_LOG_PATH, "a") as f:
        f.write(f"=== NEW TESTING RUN INITIALIZED AT {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    print(f"[SYSTEM] Clean runtime snapshot cleared. '{INCIDENT_LOG_PATH}' reset complete.")
except Exception as e:
    print(f"[SYSTEM WARNING] Failed to reset audit file: {e}")

# Start monitoring from the current end of the telemetry log.
# Historical rows are retained for analysis but are not reprocessed.
if os.path.exists(CSV_FILE_PATH) and os.path.getsize(CSV_FILE_PATH) > 0:
    with open(CSV_FILE_PATH, "r") as f:
        last_processed_line = len(list(csv.reader(f)))
else:
    # Skip the CSV header when the benchmark creates the file later
    last_processed_line = 1

print(
    f"[TELEMETRY] Runtime cursor initialized at row "
    f"{last_processed_line}. Historical samples will not be replayed."
)


while True:
    if os.path.exists(CSV_FILE_PATH) and os.path.getsize(CSV_FILE_PATH) > 0:
        with open(CSV_FILE_PATH, "r") as f:
            rows = list(csv.reader(f))
            current_total_lines = len(rows)
            
            while last_processed_line < current_total_lines:
                latest_entry = rows[last_processed_line]
                try:
                    timestamp = latest_entry[0]
                    aws_status = int(latest_entry[1])
                    aws_lat = float(latest_entry[2])

                    azure_status = int(latest_entry[3])
                    azure_lat = float(latest_entry[4])

                    gcp_status = int(latest_entry[5])
                    gcp_lat = float(latest_entry[6])
                    
                except (ValueError, IndexError) as e:
                    log_incident("ERROR", f"Failed to parse CSV log row index {last_processed_line}: {e}")
                    last_processed_line += 1
                    continue

                print(f"[{timestamp}] Processing -> AWS: {aws_lat}ms | Azure: {azure_lat}ms | GCP: {gcp_lat}ms")

                provider_metrics = {
                    "aws": (aws_lat, aws_status),
                    "azure": (azure_lat, azure_status),
                    "gcp": (gcp_lat, gcp_status)
                }

                for provider, (latency, status_code) in provider_metrics.items():
                    if cloud_status[provider] == "RECOVERING":

                        recovery_threshold = (
                            BASELINES_P95_MS[provider]
                            * RECOVERY_TOLERANCE_MULTIPLIER
                        )

                        if is_recovery_verified(
                            provider,
                            latency,
                            status_code
                        ):
                            recovery_streak[provider] += 1

                            print(
                                f"[RECOVERY CHECK] "
                                f"{provider.upper()} healthy sample "
                                f"{recovery_streak[provider]}/"
                                f"{RECOVERY_SAMPLES_REQUIRED} "
                                f"(HTTP={status_code}, "
                                f"latency={latency}ms, "
                                f"threshold={recovery_threshold:.2f}ms)"
                            )

                            if recovery_streak[provider] >= RECOVERY_SAMPLES_REQUIRED:

                                recovery_verified_time = datetime.fromisoformat(timestamp)
                                incident_start = incident_start_times[provider]

                                if incident_start is not None:
                                    recovery_duration_seconds = (
                                        recovery_verified_time - incident_start
                                    ).total_seconds()

                                    print(
                                        f"    └─ [RECOVERY TIME] "
                                        f"{provider.upper()} recovered in "
                                        f"{recovery_duration_seconds:.2f} seconds."
                                    )

                                    log_incident(
                                        "RECOVERY_TIME",
                                        f"{provider.upper()} incident recovery time: "
                                        f"{recovery_duration_seconds:.2f}s "
                                        f"(breach={incident_start}, "
                                        f"recovery={recovery_verified_time})."
                                    )

                                cloud_status[provider] = "ACTIVE"
                                recovery_streak[provider] = 0
                                incident_start_times[provider] = None

                                log_incident(
                                    "RECOVERY_VERIFIED",
                                    f"{provider.upper()} application recovery verified: "
                                    f"HTTP={status_code}, "
                                    f"latency={latency}ms, "
                                    f"threshold={recovery_threshold:.2f}ms."
                                )

                                print(
                                    f"[RECOVERY VERIFIED] "
                                    f"{provider.upper()} returned to ACTIVE."
                                )

                        else:
                            recovery_streak[provider] = 0

                            print(
                                f"[RECOVERY PENDING] "
                                f"{provider.upper()} has not yet satisfied "
                                f"the recovery policy "
                                f"(HTTP={status_code}, "
                                f"latency={latency}ms, "
                                f"threshold={recovery_threshold:.2f}ms)."
                            )
                                
                ai_decision = ask_local_llm_to_evaluate(timestamp, aws_lat, azure_lat, gcp_lat)
                print(f"Local Model Verdict: {ai_decision}")

                # Route inference outputs straight to updated action wrapper
                if ai_decision == "DESTROY_AZURE":
                    if validate_remediation_decision(
                        "azure",
                        ai_decision,
                        azure_lat,
                        azure_status
                    ):
                        if incident_start_times["azure"] is None:
                            incident_start_times["azure"] = datetime.fromisoformat(timestamp)

                            log_incident(
                                "INCIDENT_START",
                                f"AZURE confirmed remediation threshold breach at telemetry timestamp {timestamp}."
                            )
                        remediation_succeeded = execute_autonomous_action(
                            "azure",
                            "azurerm_linux_virtual_machine.azure_free_vm",
                            azure_lat,
                            azure_status
                        )

                        if remediation_succeeded:
                            with open(CSV_FILE_PATH, "r") as f:
                                last_processed_line = len(list(csv.reader(f)))

                            print(
                                f"[TELEMETRY] Remediation completed. "
                                f"Runtime cursor advanced to row {last_processed_line}; "
                                f"telemetry accumulated during remediation was discarded."
                            )

                            log_incident(
                                "TELEMETRY_BACKLOG_FLUSHED",
                                f"Post-remediation telemetry cursor advanced to row "
                                f"{last_processed_line} after AZURE recovery."
                            )

                            break

                elif ai_decision == "DESTROY_GCP":
                    if validate_remediation_decision(
                        "gcp",
                        ai_decision,
                        gcp_lat,
                        gcp_status
                    ):
                        if incident_start_times["gcp"] is None:
                            incident_start_times["gcp"] = datetime.fromisoformat(timestamp)

                            log_incident(
                                "INCIDENT_START",
                                f"GCP confirmed remediation threshold breach at telemetry timestamp {timestamp}."
                            )
                        remediation_succeeded = execute_autonomous_action(
                            "gcp",
                            "google_compute_instance.gcp_free_vm",
                            gcp_lat,
                            gcp_status
                        )

                        if remediation_succeeded:
                            with open(CSV_FILE_PATH, "r") as f:
                                last_processed_line = len(list(csv.reader(f)))

                            print(
                                f"[TELEMETRY] Remediation completed. "
                                f"Runtime cursor advanced to row {last_processed_line}; "
                                f"telemetry accumulated during remediation was discarded."
                            )

                            log_incident(
                                "TELEMETRY_BACKLOG_FLUSHED",
                                f"Post-remediation telemetry cursor advanced to row "
                                f"{last_processed_line} after GCP recovery."
                            )

                            break

                elif ai_decision == "DESTROY_AWS":
                    if validate_remediation_decision(
                        "aws",
                        ai_decision,
                        aws_lat,
                        aws_status
                    ):
                        if incident_start_times["aws"] is None:
                            incident_start_times["aws"] = datetime.fromisoformat(timestamp)

                            log_incident(
                                "INCIDENT_START",
                                f"AWS confirmed remediation threshold breach at telemetry timestamp {timestamp}."
                            )
                        remediation_succeeded = execute_autonomous_action(
                            "aws",
                            "aws_instance.aws_free_vm",
                            aws_lat,
                            aws_status
                        )

                        if remediation_succeeded:
                            with open(CSV_FILE_PATH, "r") as f:
                                last_processed_line = len(list(csv.reader(f)))

                            print(
                                f"[TELEMETRY] Remediation completed. "
                                f"Runtime cursor advanced to row {last_processed_line}; "
                                f"telemetry accumulated during remediation was discarded."
                            )

                            log_incident(
                                "TELEMETRY_BACKLOG_FLUSHED",
                                f"Post-remediation telemetry cursor advanced to row "
                                f"{last_processed_line} after AWS recovery."
                            )

                            break

                elif ai_decision in {"INVALID", "MODEL_ERROR"}:
                    print(
                        f"[SAFETY GATE] "
                        f"No autonomous action permitted: {ai_decision}"
                    )

                last_processed_line += 1
                
    time.sleep(1)
