#!/bin/bash
# Start two JVM instances with different 'fullname' values (simulate different variants)
java -Dcom.netfolio.appname=test -Dcom.netfolio.fullname=instance1 EternallyRunning &
java -Dcom.netfolio.appname=test -Dcom.netfolio.fullname=instance2 EternallyRunning &

# Optionally, wait a few seconds to let the JVMs start up
sleep 5

# Start the push metrics script
python3 jvm-pusher.py