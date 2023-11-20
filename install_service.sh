sudo apt update
sudo apt install -y python3-pip git
sudo snap install ngrok
pip3 install python-dotenv python-networkmanager
mkdir /home/nifty/Projects
cd /home/nifty/Projects
git clone https://bond-cam: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@github.com/nifty-apps/bond-cam-sbc.git /home/nifty/Projects/bondcam_streaming
chown -R nifty /home/nifty/Projects/bondcam_streaming
cd /home/nifty/Projects/bondcam_streaming
mv .env.default .env
sudo ln -s /home/nifty/Projects/bondcam_streaming/bondcam_streaming.service /etc/systemd/system/bondcam_streaming.service
sudo systemctl enable bondcam_streaming
sudo systemctl start bondcam_streaming
sudo ln -s /home/nifty/Projects/bondcam_streaming/bondcam_startup.service /etc/systemd/system/bondcam_startup.service
sudo systemctl enable bondcam_startup.service
sudo systemctl start bondcam_startup.service