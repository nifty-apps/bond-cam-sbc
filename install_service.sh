sudo apt update
sudo apt install -y python3-pip git
pip3 install python-dotenv
mkdir -p /home/nifty/Projects/bondcam_streaming/videos/
cd /home/nifty/Projects
git clone git@github.com:nifty-apps/bond-cam-sbc.git /home/nifty/Projects/bondcam_streaming
cd /home/nifty/Projects/bondcam_streaming
sudo cp bondcam_streaming.service /etc/systemd/system/
sudo systemctl enable bondcam_streaming
sudo systemctl start bondcam_streaming