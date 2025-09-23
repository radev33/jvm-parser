import os
import subprocess
import traceback
import socket
import time
import sys
import signal
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from functools import lru_cache

# Load configurations
PUSHGATEWAY_URL = os.getenv("PUSHGATEWAY_URL", "http://pushgateway:9091")
PUSH_INTERVAL = int(os.getenv("PUSH_INTERVAL_SECONDS", "15"))  # Interval between pushes
JOB_NAME = os.getenv("JOB_NAME", "jvm_metrics_pusher")
INSTANCE = os.getenv("INSTANCE", socket.gethostname())

# GC metrics keys
GC_METRIC_KEYS = ["s0c", "s1c", "oc", "ec"]

# Signal flag for graceful shutdown
shutdown_flag = False

@lru_cache(maxsize=None)
def getSysprops(pid: int):
    try:
        output = subprocess.check_output(
            f"jinfo -sysprops {pid} | grep -E 'com\\.netfolio\\.(appname|fullname)='",
            stderr=subprocess.DEVNULL,
            shell=True
        ).decode()
        appname, variant = "unknown", "unknown"
        for line in output.splitlines():
            if "com.netfolio.appname" in line:
                appname = line.split("=")[-1].strip()
            elif "com.netfolio.fullname" in line:
                variant = line.split("=")[-1].strip()
        return {"appname": appname, "variant": variant}
    except subprocess.CalledProcessError:
        return {}
    except Exception as e:
        print(f"Error getting sysprops from PID {pid}: {e}")
        return {"appname": "unknown", "variant": "unknown"}
    
@lru_cache(maxsize=None)
def getHeapSize(pid: int):
    try:
        output = subprocess.check_output(
            f"jinfo -flags {pid} | grep -o 'XX:MaxHeapSize=[0-9]\\+'",
            stderr=subprocess.DEVNULL,
            shell=True
        ).decode()
        heapSize = 0
        for line in output.splitlines():
            if line.strip():
                heapSize = int(line.split("=")[-1])
        return {"max_heap_size": heapSize}
    except subprocess.CalledProcessError:
        return {}
    except Exception as e:
        print(f"Error getting heap size from PID {pid}: {e}")
        return {"max_heap_size": 0}

def getGCData(pid: int):
    try:
        cmd = (
            f"jstat -gc {pid} | awk 'NR==1 {{for(i=1; i<=NF; i++) header[i]=$i}} "
            "NR==2 {for(i=1; i<=NF; i++) if(header[i]==\"S0C\" || header[i]==\"S1C\" || header[i]==\"OC\" || header[i]==\"EC\") print header[i] \": \" $i}'"
        )
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, shell=True).decode()
        gcData = {}
        for line in output.splitlines():
            if ":" in line:
                key, value = line.split(":")
                gcData[key.strip().lower()] = float(value.strip())
        return gcData
    except subprocess.CalledProcessError:
        return {}
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

def push_metrics():
    registry = CollectorRegistry()

    heap_gauge = Gauge(
        "jvm_heap_size_bytes",
        "Max heap size in bytes.",
        ["pid", "appname", "variant", "instance"],
        registry=registry
    )

    gc_gauges = {
        key: Gauge(
            f"jvm_gc_{key}_bytes",
            f"GC metric for {key}.",
            ["pid", "appname", "variant", "instance"],
            registry=registry
        ) for key in GC_METRIC_KEYS
    }

    pids = getPIDs()
    for pid in pids:
        sysprops = getSysprops(pid)
        heap = getHeapSize(pid)
        gc_stats = getGCData(pid)

        appname = sysprops.get("appname", "unknown")
        variant = sysprops.get("variant", "unknown")
        pid_str = str(pid)

        heap_gauge.labels(pid=pid_str, appname=appname, variant=variant, instance=INSTANCE).set(heap.get("max_heap_size", 0))

        for key in GC_METRIC_KEYS:
            gc_gauges[key].labels(pid=pid_str, appname=appname, variant=variant, instance=INSTANCE).set(gc_stats.get(key, 0.0))

    try:
        push_to_gateway(PUSHGATEWAY_URL, job=JOB_NAME, registry=registry)
        print(f"Metrics pushed to {PUSHGATEWAY_URL} for job='{JOB_NAME}'")
    except Exception as e:
        print(f"Failed to push metrics: {e}")

def handle_shutdown(signum, frame):
    global shutdown_flag
    shutdown_flag = True
    print("Shutdown signal received. Exiting gracefully...")

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

if __name__ == '__main__':
    print("Starting Pushgateway metrics pusher...")
    while not shutdown_flag:
        push_metrics()
        time.sleep(PUSH_INTERVAL)
    print("Shutdown complete.")
