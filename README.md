# Multi-Cloud LLM Remediation Prototype

A localised, open-weight Large Language Model (LLM) prototype for controlled multi-cloud infrastructure remediation across Amazon Web Services (AWS), Microsoft Azure, and Google Cloud Platform (GCP).

This prototype was developed as part of a **Bachelor of Science (Honours) in Computer Systems and Networks** dissertation.

---

## Overview

The system continuously monitors cloud endpoint telemetry, including:

- HTTP status
- Response latency

The telemetry is fed to a locally hosted LLM, which classifies the current infrastructure state and may recommend provider-specific remediation.

The LLM itself does **not** directly control the cloud infrastructure. A Python orchestration layer checks its recommendation against deterministic safety conditions before allowing any infrastructure action.

When remediation is approved:

- AWS and GCP use scoped Terraform re-provisioning.
- Azure uses a hybrid Terraform and Azure CLI process.
- The system continues monitoring the affected endpoint until recovery has been validated.

Apache JMeter was used to perform stress tests on the prototype, while **Mean Time to Remediate (MTTR)** was used to examine remediation performance.

---

## Technologies Used

### Software

- Python 3
- Terraform
- Apache JMeter
- Ollama
- Microsoft Azure CLI
- Microsoft OpenJDK 21

### Cloud Platforms

- Amazon Web Services (AWS)
- Microsoft Azure
- Google Cloud Platform (GCP)

### Local LLM

The local LLM used by the prototype is:

**Qwen2.5-Coder 7B**

The model is executed locally through Ollama.

Before starting the remediation orchestrator, ensure that Ollama is installed and that the required model is available locally.

Install the model using:

```bash
ollama pull qwen2.5-coder:7b
```

Python dependencies can be installed using:

```bash
pip install -r requirements.txt
```

---

## Main Prototype Components

### `main.tf`

Contains the Terraform configuration used to provision and manage the multi-cloud infrastructure.

### `variables.tf`

Contains Terraform variable definitions required by the infrastructure configuration.

### `benchmark.py`

Continuously sends requests to the AWS, Azure, and GCP endpoints and records telemetry including:

- Timestamp
- HTTP status
- Response latency

The generated telemetry is written to a CSV file and is used by the orchestration system.

### `production_orchestrator.py`

Implements the main closed-loop remediation process.

The orchestrator:

1. Reads the latest cloud telemetry.
2. Sends the telemetry context to the local LLM.
3. Receives a constrained classification from the LLM.
4. Validates the recommendation using deterministic safety checks.
5. Checks the configured remediation threshold.
6. Applies provider-specific remediation where appropriate.
7. Monitors the affected endpoint following remediation.
8. Confirms recovery only after the configured recovery criteria are satisfied.
9. Records remediation and recovery events in the audit log.

The LLM produces classification outputs such as:

```text
CLEAR
DESTROY_AWS
DESTROY_AZURE
DESTROY_GCP
```

These values are internal recommendations only and are **not direct Terraform commands**.

### `stress_test.py`

Contains the earlier Python-based stress-testing implementation used during prototype development.

### `TriCloud_Baseline.jmx`

Apache JMeter test configuration used to generate controlled workloads against the three cloud endpoints.

### `start_sandbox.ps1`

Launches both:

```text
benchmark.py
production_orchestrator.py
```

at the same time.

### `automation_audit_log.txt`

Contains recorded events from the automated remediation workflow, including:

- Threshold breaches
- Safety-gate decisions
- Circuit-breaker events
- Remediation actions
- Successful recovery events

### `tri_cloud_latency_metrics.csv`

Contains cloud endpoint telemetry collected during prototype execution.

### `Test Results/`

Contains experimental output collected during prototype testing, including CSV and spreadsheet results from the automated workload tests.

---

## Execution Order

The execution sequence is as follows.

### 1. Configure cloud credentials

Configure valid credentials for AWS, Azure, and GCP using the appropriate provider tools or environment configuration.

Credentials are **not included** with this repository.

---

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

---

### 3. Initialise Terraform

```bash
terraform init
```

---

### 4. Review the Terraform configuration

```bash
terraform plan
```

---

### 5. Provision the infrastructure

```bash
terraform apply
```

---

### 6. Verify the active cloud endpoints

Ensure the initial AWS, Azure, and GCP endpoint information is correctly configured before starting the monitoring process.

When remediation re-provisions a cloud node and assigns a new public IP address, the orchestration system automatically updates the active endpoint information.

---

### 7. Start Ollama

Ensure the local Ollama service and Qwen2.5-Coder 7B model are available.

Example:

```bash
ollama run qwen2.5-coder:7b
```

---

### 8. Start telemetry monitoring and the remediation orchestrator

Run:

```powershell
.\start_sandbox.ps1
```

`start_sandbox.ps1` launches both `benchmark.py` and `production_orchestrator.py` at the same time.

`benchmark.py` begins collecting cloud endpoint telemetry while `production_orchestrator.py` simultaneously monitors the generated telemetry and manages the remediation workflow.

---

### 9. Run the JMeter workload

Open the supplied JMeter `.jmx` test plan or execute it using JMeter in non-GUI mode.

The workload generates HTTP traffic against the three cloud endpoints while the telemetry and remediation systems remain active.

---

### 10. Review the results

Following testing, review:

- Telemetry CSV files
- `automation_audit_log.txt`
- JMeter results
- Recovery events
- MTTR measurements

---

## Safety Mechanisms

The prototype deliberately separates LLM recommendations from infrastructure execution.

A model-generated remediation recommendation cannot directly modify cloud infrastructure.

Before remediation is permitted, the Python orchestration layer independently checks the current telemetry against the configured remediation conditions.

The prototype also includes a **circuit-breaker mechanism** to prevent repeated remediation cycles after the configured remediation allowance has been reached.

This architecture ensures that the LLM acts as a decision-support component rather than being given unrestricted control over infrastructure execution.

---

## Recovery Validation

Terraform completion alone is **not** treated as successful recovery.

Following remediation, the affected endpoint continues to be monitored.

Recovery is only confirmed when:

- The endpoint returns HTTP 200.
- Response latency returns within the configured recovery threshold.
- The healthy condition is observed for two consecutive telemetry samples.

This reduces the chance that a temporary improvement is incorrectly treated as a successful recovery.

---

## Credentials and Sensitive Information

For security reasons, cloud credentials, API keys, secrets, authentication tokens, and other sensitive information have intentionally been removed from the submitted prototype files.

Anyone attempting to reproduce the prototype must configure their own:

- AWS credentials and resources
- Microsoft Azure credentials and resources
- GCP credentials and resources
- Cloud endpoint addresses
- Required notification-service credentials

No valid private credentials are required to understand or review the submitted source code.

---

## Research Context

This prototype was developed as a controlled experimental system and is **not intended to represent a production-ready enterprise remediation platform**.

The submitted files are intended to demonstrate the:

- Architecture
- Implementation
- Experimental workflow
- Safety mechanisms
- Remediation logic
- Recovery-validation process

evaluated within the accompanying dissertation.

---

## Author

**Luke Galea**  
Bachelor of Science (Honours) in Computer Systems and Networks  
MCAST
