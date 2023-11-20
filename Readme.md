# Bond Cam SBC Setup Guide

Follow the steps below to set up Bond Cam on your Single Board Computer (SBC).

## Prerequisites

- A Unix-like operating system
- Internet connection

## Steps

1. **Update the package list and install necessary tools:**
    ```bash
    sudo apt update && sudo apt install -y python3-pip git
    sudo snap install ngrok
    ```

2. **Install the `python-dotenv` library using `pip3`:**
    ```bash
    pip3 install python-dotenv python-networkmanager
    ```

3. **Clone the Bond Cam SBC repository:**
    ```bash
    mkdir /home/nifty/Projects
    cd /home/nifty/Projects
    git clone https://bond-cam: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@github.com/nifty-apps/bond-cam-sbc.git /home/nifty/Projects/bondcam_streaming    
    ```

4. **Navigate to the cloned directory:**
    ```bash
    chown -R nifty /home/nifty/Projects/bondcam_streaming
    cd /home/nifty/Projects/bondcam_streaming
    mv .env.default .env
    ```

5. **Copy the service file and start the Bond Cam service**:
    ```bash
    sudo ln -s /home/nifty/Projects/bondcam_streaming/bondcam_streaming.service /etc/systemd/system/bondcam_streaming.service
    sudo systemctl enable bondcam_streaming
    sudo systemctl start bondcam_streaming
    sudo ln -s /home/nifty/Projects/bondcam_streaming/bondcam_startup.service /etc/systemd/system/bondcam_startup.service
    sudo systemctl enable bondcam_startup.service
    sudo systemctl start bondcam_startup.service
    ```

---

That's it! Bond Cam should now be set up and running on your SBC. If you face any issues or have additional questions, please consult the official Bond Cam documentation or contact support.
