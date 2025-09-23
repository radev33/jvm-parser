import os
import subprocess
import traceback
import socket
import time
import signal
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from functools import lru_cache

# Load configurations
PUSHGATEWAY_URL   = os.getenv("PUSHGATEWAY_URL",   "http://pushgateway:9091")
PUSH_INTERVAL     = int(os.getenv("PUSH_INTERVAL_SECONDS", "15"))
JOB_NAME          = os.getenv("JOB_NAME",          "jvm_metrics_pusher")
INSTANCE          = os.getenv("INSTANCE",          socket.gethostname())

shutdown_flag = False

@lru_cache(maxsize=None)
def getSysprops(pid: int):
    try:
        output = subprocess.check_output(
            f"jinfo -sysprops {pid} | grep -E 'com\\.netfolio\\.(appname|fullname)='",
            stderr=subprocess.DEVNULL, shell=True
        ).decode()
        appname = variant = "unknown"
        for line in output.splitlines():
            if "com.netfolio.appname" in line:
                appname = line.split("=", 1)[1].strip()
            elif "com.netfolio.fullname" in line:
                variant = line.split("=", 1)[1].strip()
        return {"appname": appname, "variant": variant}
    except subprocess.CalledProcessError:
        return {}
    except Exception as e:
        print(f"Error getting sysprops for PID {pid}: {e}")
        return {"appname": "unknown", "variant": "unknown"}

@lru_cache(maxsize=None)
def getHeapSize(pid: int):
    try:
        output = subprocess.check_output(
            f"jinfo -flags {pid} | grep -o 'XX:MaxHeapSize=[0-9]*'",
            stderr=subprocess.DEVNULL, shell=True
        ).decode()
        size = 0
        for line in output.splitlines():
            if line.startswith("XX:MaxHeapSize="):
                size = int(line.split("=", 1)[1])
        return {"max_heap_size": size}
    except subprocess.CalledProcessError:
        return {}
    except Exception as e:
        print(f"Error getting heap size for PID {pid}: {e}")
        return {"max_heap_size": 0}

def getGCData(pid: int):
    try:
        raw = subprocess.check_output(f"jstat -gc {pid}", stderr=subprocess.DEVNULL, shell=True).decode()
        lines = raw.strip().splitlines()
        if len(lines) < 2:
            return {}
        headers = lines[0].split()
        values  = lines[1].split()
        stats = {}
        for key, val in zip(headers, values):
            try:
                stats[key.lower()] = float(val)
            except ValueError:
                stats[key.lower()] = 0.0
        return stats
    except subprocess.CalledProcessError:
        return {}
    except Exception as e:
        print(f"Error getting GC data for PID {pid}: {e}")
        traceback.print_exc()
        return {}

def getPIDs():
    pids = {}
    try:
        raw = subprocess.check_output("jps", shell=True).decode()
        for line in raw.strip().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] != "Jps":
                pid, name = parts
                pids[int(pid)] = name
    except Exception as e:
        print(f"Error retrieving PIDs: {e}")
    return pids

def push_metrics():
    pids = getPIDs()
    all_gc_keys = set()
    collected    = {}

    # collect per-PID data & discover all keys
    for pid in pids:
        sysprops = getSysprops(pid)
        heap     = getHeapSize(pid)
        gc       = getGCData(pid)

        all_gc_keys |= set(gc.keys())
        collected[pid] = {"sysprops": sysprops, "heap": heap, "gc": gc}

    # create registry & base gauges
    registry = CollectorRegistry()

    heap_gauge = Gauge(
        "jvm_heap_size_bytes",
        "Max heap size in bytes.",
        ["pid", "appname", "variant", "instance"],
        registry=registry
    )

    gc_gauges = {}
    for key in sorted(all_gc_keys):
        metric_name = f"jvm_gc_{key}_bytes"
        description = f"GC metric for {key}."
        gc_gauges[key] = Gauge(
            metric_name,
            description,
            ["pid", "appname", "variant", "instance"],
            registry=registry
        )

    # set gauge values
    for pid, stats in collected.items():
        pid_str  = str(pid)
        appname  = stats["sysprops"].get("appname",  "unknown")
        variant  = stats["sysprops"].get("variant",  "unknown")

        heap_gauge.labels(
            pid=pid_str,
            appname=appname,
            variant=variant,
            instance=INSTANCE
        ).set(stats["heap"].get("max_heap_size", 0))

        for key, gauge in gc_gauges.items():
            gauge.labels(
                pid=pid_str,
                appname=appname,
                variant=variant,
                instance=INSTANCE
            ).set(stats["gc"].get(key, 0.0))

    try:
        push_to_gateway(PUSHGATEWAY_URL, job=JOB_NAME, registry=registry)
        print(f"Metrics pushed to {PUSHGATEWAY_URL} for job='{JOB_NAME}'")
    except Exception as e:
        print(f"Failed to push metrics: {e}")

def handle_shutdown(signum, frame):
    global shutdown_flag
    shutdown_flag = True
    print("Shutdown signal received. Exiting gracefully...")

signal.signal(signal.SIGINT,  handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

if __name__ == '__main__':
    print("Starting Pushgateway metrics pusher...")
    while not shutdown_flag:
        push_metrics()
        time.sleep(PUSH_INTERVAL)
    print("Shutdown complete.")
