FROM openjdk:11-jdk-slim

# Install Python3 and pip
RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the Python requirements, Java source, pusher script and entrypoint script
COPY requirements.txt .
COPY jvm-pusher.py .
COPY EternallyRunning.java .
COPY entrypoint.sh .


# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Compile the Java program
RUN javac EternallyRunning.java

# Make sure the entrypoint script is executable
RUN chmod +x entrypoint.sh

RUN ls -l /app
# Expose the metrics port
#EXPOSE 9100

# Use the entrypoint script to start JVMs and the pusher script
CMD ["/app/entrypoint.sh"]