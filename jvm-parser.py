import os
import subprocess
import time

#functions
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

#main body
print("Executing jps")
command = subprocess.check_output("jps", shell=True).decode()

pid_dictionary={}

print("Parsing pid")

for line in command.split('\n'):
    line = line.strip()
    if line:
        pid, processName = line.split()
        if processName == "Jps":
            continue
        pid_dictionary[pid] = processName
print(pid_dictionary)

for pid in pid_dictionary.keys():
    getPidInfo(pid)

    