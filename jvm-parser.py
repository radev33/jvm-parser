import os
import subprocess
import requests
import traceback
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway


#declarations
pid_dictionary={}
PUSHGATEWAY_HOST="http://pushgateway:9091"

#functions
def getSysprops(pid: int):
    try:
        exec1 = subprocess.check_output(f"jinfo -sysprops {pid} | grep -E 'com\\.netfolio\\.(appname|fullname)='", shell=True).decode()
        print(f"Info from pid {pid} \n")
        print("jinfo -sysprops")
        print(exec1)

        print("Retrieved data:")
        #format data for json as dictionary
        for line in exec1.split("\n"):
            if "com.netfolio.appname" in line:
                appname = line.split("=")[-1].strip()
                print(f"appname: {appname}")
            elif "com.netfolio.fullname" in line:
                variant = line.split("=")[-1].strip()
                print(f"variant: {variant}")
            # else:
            #     raise Exception("Could not find needed parameters.")
            
        return {"appname": appname, "variant": variant}

    except Exception as e:
        print(f"Error getting jinfo -sysprops from pid {pid}: {e} \n")
        return {}
    
def getHeapSize(pid: int):
    try:
        exec2 = subprocess.check_output(f"jinfo -flags {pid} | grep -o 'XX:MaxHeapSize=[0-9]\\+'", shell=True).decode()
        print("jinfo -flags")
        print(exec2)

        print("Retrieved data:")
        #format data for json as dictionary
        for line in exec2.split("\n"):
            if not line.strip() or "=" not in line:
                continue
            heapSize = line.split("=")[-1].strip()
            print(f"Heap size: {heapSize}")
        return {"max_heap_size": int(heapSize)}
    except Exception as e:
        print(f"Error getting jinfo -flags from pid {pid}: {e} \n")
        return {}

def getGCData(pid: int):
    try:
        print("jstat -gc")
        cmd1 = f"jstat -gc {pid} | awk 'NR==1 {{for(i=1; i<=NF; i++) header[i]=$i}} NR==2 {{for(i=1; i<=NF; i++) if(header[i]==\"S0C\" || header[i]==\"S1C\" || header[i]==\"OC\" || header[i]==\"EC\") print header[i] \": \" $i}}'"
        exec3 = subprocess.check_output(cmd1, shell=True).decode()
        print(exec3)

        gcData = {}
        print("Retrieved data:")
        #format data for json as dictionary
        for line in exec3.split("\n"):
            if not line.strip() or ":" not in line:
                continue
            key, value = line.split(":")
            gcData[key.lower()] = float(value)
        print(gcData)
        return gcData
    except Exception as e:
        print(f"Error getting jstat -gc from pid {pid}: {traceback.print_exc()}")
        return {}

def getPidInfo(pid: int):
    try:
        exec1 = subprocess.check_output(f"jinfo -sysprops {pid} | grep -E 'com\\.netfolio\\.(appname|fullname)='", shell=True).decode()
        print(f"Info fromfrom pid {pid} \n")
        print("jinfo -sysprops")
        print(exec1)
    except:
        print(f"Error getting jinfo -sysprops from pid {pid} \n")
    try:
        exec2 = subprocess.check_output(f"jinfo -flags {pid} | grep -o 'XX:MaxHeapSize=[0-9]\\+'", shell=True).decode()
        print("jinfo -flags")
        print(exec2)
    except:
        print(f"Error getting jinfo -flags from pid {pid}")
    try:
        cmd1 = f"jstat -gc {pid} | awk 'NR==1 {{for(i=1; i<=NF; i++) header[i]=$i}} NR==2 {{for(i=1; i<=NF; i++) if(header[i]==\"S0C\" || header[i]==\"S1C\" || header[i]==\"OC\" || header[i]==\"EC\") print header[i] \": \" $i}}'"
        exec3 = subprocess.check_output(cmd1, shell=True).decode()
        print(exec3)
    except:
        print(f"Error getting jstat -gc from pid {pid}")


def getPid():
    pids={}
    print("Executing jps")
    command = subprocess.check_output("jps", shell=True).decode()

    for line in command.split('\n'):
        line = line.strip()
        if line:
            pid, processName = line.split()
            if processName == "Jps":
                continue
            pids[pid] = processName
    print(pids)
    return pids

def sendMetrics():
    global pid_dictionary
    try:
        for pid in pid_dictionary.keys():
            #get data
            sysprops = getSysprops(pid)
            heap = getHeapSize(pid)
            gc_stats = getGCData(pid)

            #get labels
            appname = sysprops.get("appname")
            variant = sysprops.get("variant")

            #create registry
            registry = CollectorRegistry()
            #create max heap gauge
            heap_gauge = Gauge("heap_size_bytes", "Max Heap Size in bytes", ["appname", "variant"], registry=registry)
            heap_gauge.labels(appname=appname, variant=variant).set(heap.get("max_heap_size"))
            #create GC gauges
            for key, value in gc_stats.items():
                gc_gauge = Gauge(key, f"Garbage collector metric for {key}", ["appname", "variant"], registry=registry)
                gc_gauge.labels(appname=appname, variant=variant).set(value)
            
            #push metrics to pushgateway
            push_to_gateway(PUSHGATEWAY_HOST, job="jvm_metrics", registry=registry)
            print(f"Metrics pushed for pid {pid} successfully.")


            
    except Exception as e:
        print(f"Failed to push metrics to {PUSHGATEWAY_HOST}: {e}:")
        traceback.print_exc()
        

    
    

print("Parsing pid")
pid_dictionary = getPid()
if not pid_dictionary:
    print("No active Java processes")
else:
    sendMetrics()


# for pid in pid_dictionary.keys():
#     getPidInfo(pid)

    