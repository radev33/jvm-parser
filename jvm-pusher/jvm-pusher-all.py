import os
import subprocess
import traceback
import socket
import time
import signal
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from functools import lru_cache

# Configuration
PUSHGATEWAY_URL = os.getenv("PUSHGATEWAY_URL", "http://pushgateway:9091")
PUSH_INTERVAL = int(os.getenv("PUSH_INTERVAL_SECONDS", "15"))
JOB_NAME = os.getenv("JOB_NAME", "jvm_metrics_pusher")
INSTANCE = os.getenv("INSTANCE", socket.gethostname())

shutdown_flag = False

@lru_cache(maxsize=None)
def getSysprops(pid: int):
    try:
        out = subprocess.check_output(
            f"jinfo -sysprops {pid}",
            stderr=subprocess.DEVNULL, shell=True
        ).decode()
        appname = variant = "unknown"
        for line in out.splitlines():
            if "com.netfolio.appname" in line:
                appname = line.split("=",1)[1].strip()
            if "com.netfolio.fullname" in line:
                variant = line.split("=",1)[1].strip()
        return {"appname": appname, "variant": variant}
    except Exception:
        return {"appname": "unknown", "variant": "unknown"}

@lru_cache(maxsize=None)
def getHeapSize(pid: int):
    try:
        out = subprocess.check_output(
            f"jinfo -flags {pid}",
            stderr=subprocess.DEVNULL, shell=True
        ).decode()
        for line in out.splitlines():
            if line.startswith("XX:MaxHeapSize="):
                return int(line.split("=",1)[1])
    except Exception:
        pass
    return 0

def getPIDs():
    pids = {}
    try:
        lines = subprocess.check_output(["jps"]).decode().splitlines()
        for line in lines:
            parts = line.split()
            if len(parts)==2 and parts[1]!="Jps":
                pids[int(parts[0])] = parts[1]
    except Exception:
        pass
    return pids

def getGCData(pid: int):
    """Return dict of { header_lowercase: float(value) } from `jstat -gc`."""
    try:
        out = subprocess.check_output(["jstat","-gc", str(pid)],
                                      stderr=subprocess.DEVNULL).decode().splitlines()
        if len(out) < 2:
            return {}
        headers = out[0].split()
        values  = out[1].split()
        return { headers[i].lower(): float(values[i]) 
                 for i in range(min(len(headers), len(values))) }
    except Exception:
        return {}

def push_metrics():
    registry = CollectorRegistry()

    # 1) Heap gauge
    heap_g = Gauge(
        "jvm_heap_size_bytes",
        "Max JVM heap size in bytes",
        ["pid","appname","variant","instance"],
        registry=registry
    )

    # 2) Collect PIDs + each one's GC data
    pids    = getPIDs()
    gc_data = {}
    all_keys = set()

    for pid in pids:
        stats = getGCData(pid)
        gc_data[pid] = stats
        all_keys.update(stats.keys())

    # 3) Dynamically register one Gauge per GC key
    gc_gauges = {}
    for key in sorted(all_keys):
        gc_gauges[key] = Gauge(
            f"jvm_gc_{key}_bytes",
            f"JVM GC metric {key}",
            ["pid","appname","variant","instance"],
            registry=registry
        )

    # 4) Populate gauges
    for pid, stats in gc_data.items():
        props = getSysprops(pid)
        labels = {
            "pid":      str(pid),
            "appname":  props.get("appname","unknown"),
            "variant":  props.get("variant","unknown"),
            "instance": INSTANCE
        }

        heap_g.labels(**labels).set(getHeapSize(pid))

        for key, g in gc_gauges.items():
            g.labels(**labels).set(stats.get(key, 0.0))

    # 5) Push
    try:
        push_to_gateway(PUSHGATEWAY_URL, job=JOB_NAME,
                        registry=registry)
        print(f"Pushed to {PUSHGATEWAY_URL} (job={JOB_NAME})")
    except Exception as e:
        print(f"Push failed: {e}")

def handle_shutdown(signum, frame):
    global shutdown_flag
    shutdown_flag = True
    print("Shutdown requested.")

signal.signal(signal.SIGINT,  handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

if __name__ == "__main__":
    print("Starting JVM metrics pusher…")
    while not shutdown_flag:
        push_metrics()
        time.sleep(PUSH_INTERVAL)
    print("Exiting.")
