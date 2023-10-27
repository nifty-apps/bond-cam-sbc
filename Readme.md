# Bond Cam SBC Setup Guide

Follow the steps below to set up Bond Cam on your Single Board Computer (SBC).

## Prerequisites

- A Unix-like operating system
- Internet connection

## Steps

1. **Update the package list and install necessary tools:**
    ```bash
    sudo apt update && sudo apt install -y python3-pip git
    ```

2. **Install `pip3` using the bootstrap script:**
    ```bash
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
    python3 get-pip.py
    ```

3. **Add the local bin directory to your PATH in `.bashrc`**:

    First, open the `.bashrc` file using `nano`:
    ```bash
    nano ~/.bashrc
    ```

    Then, add the following line to the end of the file:
    ```
    export PATH="$PATH:/home/nifty/.local/bin"
    ```

    Save and exit (`CTRL` + `X`, press `Y` and then `Enter`).

    Finally, source the updated `.bashrc` to apply the changes:
    ```bash
    source ~/.bashrc
    ```

4. **Install the `python-dotenv` library using `pip3`:**
    ```bash
    pip3 install python-dotenv
    ```

5. **Clone the Bond Cam SBC repository:**
    ```bash
    git pull https://bond-cam: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@github.com/nifty-apps/bond-cam-sbc.git
    ```

6. **Navigate to the cloned directory:**
    ```bash
    cd bond-cam-sbc
    ```

7. **Copy the service file and start the Bond Cam service**:
    ```bash
    sudo cp bondcam_streaming.service /etc/systemd/system/
    sudo systemctl enable bondcam_streaming
    sudo systemctl start bondcam_streaming
    ```

---

That's it! Bond Cam should now be set up and running on your SBC. If you face any issues or have additional questions, please consult the official Bond Cam documentation or contact support.
