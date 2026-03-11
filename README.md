# Jukebox

MIDI to Roblox Piano !  

Supports Windows, macOS, and Linux  
Requires Python 3.9+


[Discord](https://discord.gg/jaxgETk5Em) | [LICENSE](LICENSE)
# Usage
## Method 1 (Recommend)
```bash
# Install
git clone https://github.com/x15rte/Jukebox.git
cd Jukebox/
sudo apt install libasound2-dev libjack-dev (Linux)
pip install -r ./requirements.txt (Mac/Linux)
pip install -r ./requirements-windows.txt (Windows)

# Run
python ./main.py

# Update
git pull
```
## Method 2  
Download and run the latest release from the [Releases page](https://github.com/x15rte/Jukebox/releases).

# Freeze to exe
```bash
pyinstaller ./Jukebox.spec
```
# Tips
Use MIDI output to support velocity  
KEY Mode: 88-Key -> Ctrl    
Pedal -> Space  

Open config dir  
`cd ~/.jukebox_piano/`


# Screenshots

![1](images/1.png)
![2](images/2.png)
![3](images/3.png)
![4](images/4.png)
![5](images/5.png)





