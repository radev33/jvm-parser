import os
import subprocess
import traceback
import socket
import time
import signal
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

# Load configurations
PUSHGATEWAY_URL   = os.getenv("PUSHGATEWAY_URL",   "http://pushgateway:9091")
PUSH_INTERVAL     = int(os.getenv("PUSH_INTERVAL_SECONDS", "15"))
JOB_NAME          = os.getenv("JOB_NAME",          "jvm_metrics_pusher")
INSTANCE          = os.getenv("INSTANCE",          socket.gethostname())

shutdown_flag = False

# Cache for sysprops and heap size (cleared each cycle to avoid stale data)
_sysprops_cache = {}
_heap_cache = {}

def getSysprops(pid: int):
    # Check if PID still exists before using cache
    if pid not in _sysprops_cache:
        try:
            # Use list-based subprocess call instead of shell=True for security
            jinfo_proc = subprocess.Popen(
                ["jinfo", "-sysprops", str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            grep_proc = subprocess.Popen(
                ["grep", "-E", r"com\.netfolio\.(appname|fullname)="],
                stdin=jinfo_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            jinfo_proc.stdout.close()
            output, _ = grep_proc.communicate()
            
            appname = variant = "unknown"
            for line in output.decode().splitlines():
                if "com.netfolio.appname" in line:
                    appname = line.split("=", 1)[1].strip()
                elif "com.netfolio.fullname" in line:
                    variant = line.split("=", 1)[1].strip()
            _sysprops_cache[pid] = {"appname": appname, "variant": variant}
        except (subprocess.CalledProcessError, FileNotFoundError):
            _sysprops_cache[pid] = {"appname": "unknown", "variant": "unknown"}
        except Exception as e:
            print(f"Error getting sysprops for PID {pid}: {e}")
            _sysprops_cache[pid] = {"appname": "unknown", "variant": "unknown"}
    return _sysprops_cache.get(pid, {"appname": "unknown", "variant": "unknown"})

def getHeapSize(pid: int):
    # Check if PID still exists before using cache
    if pid not in _heap_cache:
        try:
            # Use list-based subprocess call instead of shell=True for security
            jinfo_proc = subprocess.Popen(
                ["jinfo", "-flags", str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            grep_proc = subprocess.Popen(
                ["grep", "-o", r"XX:MaxHeapSize=[0-9]*"],
                stdin=jinfo_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            jinfo_proc.stdout.close()
            output, _ = grep_proc.communicate()
            
            size = 0
            for line in output.decode().splitlines():
                if line.startswith("XX:MaxHeapSize="):
                    size = int(line.split("=", 1)[1])
            _heap_cache[pid] = {"max_heap_size": size}
        except (subprocess.CalledProcessError, FileNotFoundError):
            _heap_cache[pid] = {"max_heap_size": 0}
        except Exception as e:
            print(f"Error getting heap size for PID {pid}: {e}")
            _heap_cache[pid] = {"max_heap_size": 0}
    return _heap_cache.get(pid, {"max_heap_size": 0})

def getGCData(pid: int):
    try:
        # Use list-based subprocess call instead of shell=True for security
        raw = subprocess.check_output(
            ["jstat", "-gc", str(pid)],
            stderr=subprocess.DEVNULL
        ).decode()
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
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    except Exception as e:
        print(f"Error getting GC data for PID {pid}: {e}")
        traceback.print_exc()
        return {}

def getPIDs():
    pids = {}
    try:
        # Use list-based subprocess call instead of shell=True for security
        raw = subprocess.check_output(["jps"], stderr=subprocess.DEVNULL).decode()
        for line in raw.strip().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] != "Jps":
                pid, name = parts
                pids[int(pid)] = name
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error retrieving PIDs: {e}")
    except Exception as e:
        print(f"Unexpected error retrieving PIDs: {e}")
    return pids

def push_metrics():
    # Clear caches at the start of each cycle to avoid stale data
    global _sysprops_cache, _heap_cache
    current_pids = getPIDs()
    
    # Remove entries for PIDs that no longer exist
    _sysprops_cache = {pid: _sysprops_cache[pid] for pid in current_pids if pid in _sysprops_cache}
    _heap_cache = {pid: _heap_cache[pid] for pid in current_pids if pid in _heap_cache}
    
    pids = current_pids
    all_gc_keys = set()
    collected    = {}

    # collect per-PID data & discover all keys
    for pid in pids:
        try:
            sysprops = getSysprops(pid)
            appname = sysprops.get("appname", "unknown")
            variant = sysprops.get("variant", "unknown")
            
            # Skip PIDs with unknown appname or variant
            if appname == "unknown" or variant == "unknown":
                print(f"Skipping PID {pid}: appname={appname}, variant={variant} (unknown values)")
                continue
            
            heap     = getHeapSize(pid)
            gc       = getGCData(pid)

            all_gc_keys |= set(gc.keys())
            collected[pid] = {"sysprops": sysprops, "heap": heap, "gc": gc}
        except Exception as e:
            # Skip this PID if there's an error, but continue with others
            print(f"Error collecting metrics for PID {pid}: {e}")
            continue

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
    print(f"Pushgateway URL: {PUSHGATEWAY_URL}, Interval: {PUSH_INTERVAL}s, Job: {JOB_NAME}, Instance: {INSTANCE}")
    
    while not shutdown_flag:
        try:
            push_metrics()
        except KeyboardInterrupt:
            # Handle keyboard interrupt gracefully
            shutdown_flag = True
            break
        except Exception as e:
            # Log error but continue running
            print(f"Unexpected error in push_metrics: {e}")
            traceback.print_exc()
        
        if not shutdown_flag:
            time.sleep(PUSH_INTERVAL)   
    
    print("Shutdown complete.")
