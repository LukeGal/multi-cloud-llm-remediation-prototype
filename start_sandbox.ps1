# Automated Master Orchestration Entrypoint
Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue
Remove-Item "sme_tri_cloud_latency_metrics.csv" -ErrorAction SilentlyContinue

echo "Initializing Telemetry Engine..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python benchmark.py"

echo "Initializing Local Agentic Evaluator..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python production_orchestrator.py"