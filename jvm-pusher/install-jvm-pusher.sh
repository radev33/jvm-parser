#install dependencies
sudo dnf install -y git python3 python3-pip

#change directory to home and clone git repo
cd ~
git clone https://github.com/radev33/jvm-parser.git

#change directory to jvm-pusher
cd ~/jvm-parser/jvm-pusher/

#create python virtual environment and install dependencies
python -m venv venv
source ~/jvm-parser/jvm-pusher/venv/bin/activate
pip install -r requirements.txt
deactivate

#set environments
export PUSHGATEWAY_URL=<URL>
#create systemd service and enable it
sudo touch /etc/systemd/system/jvm-pusher/jvm-pusher.service
sudo tee /etc/systemd/system/jvm-pusher/jvm-pusher.service <<EOF
[Unit]
Description=JVM Pusher script for pushgateway
After=network.target

[Service]
Type=simple
User=geowealth
WorkingDirectory=/home/geowealth/jvm-parser/jvm-pusher  
ExecStart=/home/geowealth/jvm-parser/jvm-pusher/venv/bin/python /home/geowealth/jvm-parser/jvm-pusher/jvm-pusher-all-fix.py
Restart=on-failure

[Install]
WantedBy=multi-user.target

EOF

sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable jvm-pusher.service
sudo systemctl start jvm-pusher.service

