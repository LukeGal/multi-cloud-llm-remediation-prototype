import urllib.request
import threading
import time
import csv
from datetime import datetime

# Target Configurations 
TARGETS = {
    "aws": "http://3.75.210.196",
    "azure": "http://68.221.69.128",
    "gcp": "http://34.159.141.48"
}

THREADS_PER_PROVIDER = 15  # Total active threads will be 15 x 3 = 45 threads
DURATION_SECONDS = 60       # How long the simulation lasts

stop_flag = False
results = []
results_lock = threading.Lock()

def hammer_server(provider_name, target_url, thread_id):
    print(f"[{provider_name.upper()}-Thread-{thread_id}] Initialized burst sequence...")
    success_count = 0
    error_count = 0
    
    while not stop_flag:
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-cache'})
            with urllib.request.urlopen(req, timeout=3) as response:
                status = response.getcode()
                latency = (time.time() - start_time) * 1000
                if status == 200:
                    success_count += 1
            time.sleep(0.1)  # Interval between rapid requests
        except Exception:
            status = "TIMEOUT/ERROR"
            latency = (time.time() - start_time) * 1000
            error_count += 1
            
        # Write metrics safely to the shared database pool
        with results_lock:
            results.append([timestamp, provider_name.upper(), thread_id, status, round(latency, 2)])
            
    print(f"[{provider_name.upper()}-Thread-{thread_id}] Halted. Successes: {success_count} | Errors: {error_count}")

print(f"==================================================")
print(f"LAUNCHING MULTI-CLOUD PARALLEL STRESS TESTER")
print(f"Simulating {THREADS_PER_PROVIDER} parallel users per cloud service provider.")
print(f"Total concurrent worker threads: {THREADS_PER_PROVIDER * len(TARGETS)}")
print(f"Execution window: {DURATION_SECONDS} seconds")
print(f"==================================================")

# Spin up independent thread pools for each provider simultaneously
all_threads = []
for provider, url in TARGETS.items():
    for i in range(THREADS_PER_PROVIDER):
        t = threading.Thread(target=hammer_server, args=(provider, url, i))
        all_threads.append(t)
        t.start()

# Hold execution main track during stress duration
time.sleep(DURATION_SECONDS)

# Trigger global shutdown sequence across all thread layers
print("\n[!] Time limit reached. Issuing cluster teardown request...")
stop_flag = True

for t in all_threads:
    t.join()

# Dump the entire unified stress dataset to a single multi-cloud CSV file
OUTPUT_FILE = "sme_multi_cloud_stress_metrics.csv"
with open(OUTPUT_FILE, mode='w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(["Timestamp", "Cloud_Provider", "Thread_ID", "HTTP_Status", "Response_Time_ms"])
    writer.writerows(results)

print("==================================================")
print("STRESS TEST COMPLETE: All environments released.")
print(f"Unified analytics ledger saved to: {OUTPUT_FILE}")
print("==================================================")
