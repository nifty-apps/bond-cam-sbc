sudo apt update
sudo apt install -y python3-pip git
pip3 install python-dotenv
mkdir /home/nifty/Projects
cd /home/nifty/Projects
git clone https://bond-cam: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@github.com/nifty-apps/bond-cam-sbc.git /home/nifty/Projects/bondcam_streaming
chown -R nifty /home/nifty/Projects/bondcam_streaming
cd /home/nifty/Projects/bondcam_streaming
mv .env.default .env
sudo cp bondcam_streaming.service /etc/systemd/system/
sudo systemctl enable bondcam_streaming
sudo systemctl start bondcam_streaming
sudo cp bondcam_startup.service /etc/systemd/system/
sudo systemctl enable bondcam_startup.service
sudo systemctl start bondcam_startup.service