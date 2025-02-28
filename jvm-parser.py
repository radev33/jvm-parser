import os
import subprocess
import time

#functions
def getPidInfo(pid: int):
    exec = subprocess.check_output(f"jinfo -sysprops {pid}", shell=True).decode()
    print(exec)

#main body
print("Executing jps")
command = subprocess.check_output("jps", shell=True).decode()

pid_dictionary={}

print("Parsing pid")

for line in command.split('\n'):
    line = line.strip()
    if line:
        pid, processName = line.split()
        pid_dictionary[pid] = processName

print(pid_dictionary)

for pid in pid_dictionary.keys():
    if pid == list(pid_dictionary.keys())[0] or pid == list(pid_dictionary.keys())[1]:
        continue
    getPidInfo(pid)

    