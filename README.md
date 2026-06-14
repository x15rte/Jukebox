# Jukebox 🎹

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://python.org) 
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/x15rte/Jukebox/blob/main/LICENSE) 
[![Discord](https://img.shields.io/discord/1475355729056764066)](https://discord.gg/jaxgETk5Em)  
MIDI to Roblox Piano!  

Supports Windows, macOS, and Linux  

# 📖 Wiki
[![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/x15rte/Jukebox)  [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/x15rte/Jukebox)  

# 🚀 Usage 

**Do not use IME during playback. Use US-QWERTY direct input only.**

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
[![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/x15rte/Jukebox)](https://github.com/x15rte/Jukebox) 
![GitHub last commit](https://img.shields.io/github/last-commit/x15rte/Jukebox)


## Method 2  
Download and run the latest release from the [Releases page](https://github.com/x15rte/Jukebox/releases).  
> the frozen exe may show the window with a random delay;if nothing appears, wait a bit longer or run via Method1

[![GitHub All Releases](https://img.shields.io/github/downloads/x15rte/Jukebox/total?label=downloads-total&logo=github)](https://github.com/x15rte/Jukebox/releases) 
[![GitHub Release](https://img.shields.io/github/v/release/x15rte/Jukebox)](https://github.com/x15rte/Jukebox/releases/latest)
[![GitHub commits since latest release](https://img.shields.io/github/commits-since/x15rte/Jukebox/latest)](https://github.com/x15rte/Jukebox/commits/main/)

# 💡 Tips 

**Use MIDI output to support velocity**

KEY Mode: 88-Key -> Ctrl ; Pedal -> Space   

Open config dir  
`cd ~/.jukebox_piano/`

# 🙋 FAQ

## How can I be sure this isn’t a malware?
You can verify it in several ways:
- Review the source code yourself (it’s fully open source).
- Use AI tools like [Claude](https://claude.com/product/claude-code) or [DeepWiki](https://deepwiki.com/x15rte/Jukebox) to analyze the code.
- Run it directly with `python main.py` without downloading any executable. (Recommended method)

Alternatively, if you prefer to use the pre-built executable from the **Immutable** release:
- It is **built automatically via GitHub Actions** (see [build.yml](https://github.com/x15rte/Jukebox/blob/main/.github/workflows/build.yml)).
- [Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
- You can scan it on [VirusTotal](https://www.virustotal.com/gui/home/upload) before running.

# 📦 Freeze to exe 
```bash
pyinstaller ./Jukebox.spec
```

# 📸 Screenshots (out of date)
<img alt="Image" src="https://github.com/user-attachments/assets/f0b03367-02f4-4b12-92e8-3d5695be2742" />
<img alt="Image" src="https://github.com/user-attachments/assets/99e310f9-cac9-4dfa-810b-479f93d9f961" />
<img alt="Image" src="https://github.com/user-attachments/assets/93c3ab54-2e89-4a4a-b13b-1339f3806aa9" />
<img alt="Image" src="https://github.com/user-attachments/assets/ac579db3-0bb0-49d4-8912-7402ffeb215b" />
<img alt="Image" src="https://github.com/user-attachments/assets/7058ab68-e43a-413a-9e9a-1a57dc56b259" />

## ✨ Credits
- [HuMidi](https://github.com/smyGitt/HuMidi-Roblox-Piano-Autoplayer)
- [RobloxMidiConnect](https://github.com/LordHenryVonHenry/RobloxMidiConnect)
- [miditoqwerty-rs](https://github.com/ArijanJ/miditoqwerty-rs)

---
This project is based on [HuMidi](https://github.com/smyGitt/HuMidi-Roblox-Piano-Autoplayer)
