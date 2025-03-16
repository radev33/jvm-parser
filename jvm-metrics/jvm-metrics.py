import os
import subprocess
import traceback
import socket
import sys
import signal
import requests
from flask import Flask, Response
from prometheus_client import CollectorRegistry, Gauge, generate_latest

app = Flask(__name__)

# Load configurations from environment variables
SD_API_URL = os.getenv("SD_API_URL", "http://flask-service-discovery:8000/sd")
SERVICE_PORT = os.getenv("SERVICE_PORT", "9100")

# Automatically detect the container's internal IP
SERVICE_HOST = os.getenv("SERVICE_HOST", socket.gethostbyname(socket.gethostname()))



# For GC metrics, we assume keys like s0c, s1c, oc, and ec
GC_METRIC_KEYS = ["s0c", "s1c", "oc", "ec"]

def getSysprops(pid: int):
    try:
        output = subprocess.check_output(
            f"jinfo -sysprops {pid} | grep -E 'com\\.netfolio\\.(appname|fullname)='",
            shell=True
        ).decode()
        appname, variant = "unknown", "unknown"
        for line in output.splitlines():
            if "com.netfolio.appname" in line:
                appname = line.split("=")[-1].strip()
            elif "com.netfolio.fullname" in line:
                variant = line.split("=")[-1].strip()
        return {"appname": appname, "variant": variant}
    except Exception as e:
        print(f"Error getting sysprops from PID {pid}: {e}")
        return {"appname": "unknown", "variant": "unknown"}

def getHeapSize(pid: int):
    try:
        output = subprocess.check_output(
            f"jinfo -flags {pid} | grep -o 'XX:MaxHeapSize=[0-9]\\+'",
            shell=True
        ).decode()
        heapSize = 0
        for line in output.splitlines():
            if line.strip():
                heapSize = int(line.split("=")[-1])
        return {"max_heap_size": heapSize}
    except Exception as e:
        print(f"Error getting heap size from PID {pid}: {e}")
        return {"max_heap_size": 0}

def getGCData(pid: int):
    try:
        # The following command extracts GC metrics (s0c, s1c, oc, ec)
        cmd = (
            f"jstat -gc {pid} | awk 'NR==1 {{for(i=1; i<=NF; i++) header[i]=$i}} "
            "NR==2 {for(i=1; i<=NF; i++) if(header[i]==\"S0C\" || header[i]==\"S1C\" || header[i]==\"OC\" || header[i]==\"EC\") print header[i] \": \" $i}'"
        )
        output = subprocess.check_output(cmd, shell=True).decode()
        gcData = {}
        for line in output.splitlines():
            if ":" in line:
                key, value = line.split(":")
                # Normalize key to lowercase (e.g. S0C -> s0c)
                gcData[key.strip().lower()] = float(value.strip())
        return gcData
    except Exception as e:
        print(f"Error getting GC data from PID {pid}: {e}")
        traceback.print_exc()
        return {}

def getPIDs():
    pids = {}
    try:
        output = subprocess.check_output("jps", shell=True).decode()
        for line in output.strip().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] != "Jps":
                pid, process_name = parts
                pids[int(pid)] = process_name
    except Exception as e:
        print(f"Error retrieving PIDs: {e}")
    return pids

def register_service():
    """Register this service with the Flask HTTP-SD API."""
    data = {
        "targets": [f"{SERVICE_HOST}:{SERVICE_PORT}"],
        "labels": {"job": "docker-metrics-service"}
    }
    try:
        requests.post(SD_API_URL, json=data)
        print(f"✅ Registered {SERVICE_HOST}:{SERVICE_PORT} with service discovery at {SD_API_URL}")
    except Exception as e:
        print(f"❌ Failed to register service: {e}")

def deregister_service():
    """Deregister this service from the Flask HTTP-SD API."""
    data = {"targets": [f"{SERVICE_HOST}:{SERVICE_PORT}"]}
    try:
        requests.delete(SD_API_URL, json=data)
        print(f"🔴 Deregistered {SERVICE_HOST}:{SERVICE_PORT}")
    except Exception as e:
        print(f"⚠️ Failed to deregister service: {e}")

def handle_shutdown(signal, frame):
    """Handle shutdown (SIGTERM, SIGINT) and deregister the service."""
    deregister_service()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, handle_shutdown)  # Ctrl+C
signal.signal(signal.SIGTERM, handle_shutdown)  # Container shutdown

@app.route('/metrics')
def metrics():
    registry = CollectorRegistry()  # Create a custom registry

    # Define the heap size gauge in the custom registry
    heap_gauge = Gauge(
        "jvm_heap_size_bytes",
        "Max heap size in bytes.",
        ["pid", "appname", "variant"],
        registry=registry
    )

    # Define GC metrics gauges in the custom registry
    gc_gauges = {}
    for key in GC_METRIC_KEYS:
        gc_gauges[key] = Gauge(
            f"jvm_gc_{key}_bytes",
            f"GC metric for {key}.",
            ["pid", "appname", "variant"],
            registry=registry
        )

    pids = getPIDs()
    for pid in pids:
        sysprops = getSysprops(pid)
        heap = getHeapSize(pid)
        gc_stats = getGCData(pid)

        appname = sysprops.get("appname", "unknown")
        variant = sysprops.get("variant", "unknown")
        pid_str = str(pid)

        # Set the heap size metric
        heap_gauge.labels(pid=pid_str, appname=appname, variant=variant).set(heap.get("max_heap_size", 0))

        # Set GC metrics
        for key in GC_METRIC_KEYS:
            gc_gauges[key].labels(pid=pid_str, appname=appname, variant=variant).set(gc_stats.get(key, 0.0))

    return Response(generate_latest(registry), mimetype='text/plain')

if __name__ == '__main__':
    try:
        register_service()
        app.run(host='0.0.0.0', port=int(SERVICE_PORT))
    finally:
        deregister_service()