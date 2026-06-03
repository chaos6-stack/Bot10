# AI-Assisted Synth Index Spike Agent 🤖📈

An advanced, statistical tick-by-tick paper-trading execution system specifically optimized for **Deriv Boom & Crash synthetic markets**. 

This system connects to the live, high-frequency **Deriv WebSockets API**, performs real-time indicator extraction (compression ratios, Z-Scores, RSI, and momentums), assesses statistical entry/exit conditions, manages risk profiles, logs performance histories to persistent file storage, and is structured for plug-and-play AI model integrations.

---

## 🧩 Architectural Directory Layout

```text
/trading_bot/
├── main.py            # Bot master manager & streaming orchestrator
├── config.py          # Settings (risk caps, symbols, windows, limits)
├── data_stream.py    # Deriv WebSocket networking (reconnection logic)
├── strategy.py        # Spike detection strategy (volatility & mean reversion)
├── ml_features.py     # Feature extraction (SMA, EMA, RSI, Standard Dev, Z-Score)
├── trader.py          # Virtual execution ledger (trade entry/exits, virtual cash)
├── risk_manager.py    # Session safety rules (daily drawdowns, cooldown blocks)
├── logger.py          # JSON / CSV disk logging managers
├── backtester.py      # Offline synthetic price-path simulator
├── requirements.txt   # Pip installation listing
└── README.md          # Guides & Setup documentation (this file)
```

---

## 🎯 Technical Capabilities Summary

1. **Sub-second WebSocket Streaming**: Pulls ticks directly from `wss://ws.derivws.com` using the public trade API.
2. **Volatility Squeeze Modeling**: Trades Boom/Crash indices by identifying low-volatility price compression ranges ("coils"), where spikes are statistically prone to build pressure.
3. **Realistic Virtual Execution Engine**: Runs a state machine for virtual entries, tracking the holding tick length, capturing exit prices instantly when a positive spike triggers, or closing at an $N$-tick timeout block if a spike fails.
4. **Defensive Risk Guarding**: Restricts trading after hitting consecutive loss thresholds (lockout cooling-offs), protects virtual capital with daily drawdown ceilings, and shuts down safely to prevent overtrading.
5. **No Expensive Dependencies**: Functions out-of-the-box using python's built-in mathematical libraries, ensuring rapid start-ups on lightweight processors.

---

## 📱 Running on Android (Step-by-Step Termux Setup)

To execute this trading system natively on your Android device (such as the Samsung A21S) without needing an external computer, use **Termux**.

### Step 1: Install Termux
* Download and install the latest Termux APK directly from [F-Droid](https://f-droid.org/en/packages/com.termux/). Do *not* use the outdated version on the Google Play Store.

### Step 2: System Bootstrapping
Launch Termux and run the following packages configuration:
```bash
# Update repositories and upgrade core tools
pkg update && pkg upgrade -y

# Install Python 3 and Git to pull code
pkg install python -y
pkg install git -y
```

### Step 3: Load the Bot Project
Create a working workspace and copy the Python bot files onto your device screen:
```bash
mkdir -y ~/deriv_bot
cd ~/deriv_bot
# (Copy or transfer the bot scripts into this directory)
```

### Step 4: Install Python Dependencies
```bash
# Install the web socket packages listed in requirements.txt
pip install -r requirements.txt
```

### Step 5: Start the Bot
```bash
# Run the main orchestrator to stream live indices
python main.py
```
*To test performance offline with a synthetic backtester generator:*
```bash
python backtester.py
```

---

## 📦 Packaging to Android APK (WebView & API Wrapper Wrapper)

If you would like to run this trading dashboard as a native standalone Android `.apk` app, here are the two standard approaches:

### Option A: The Cordova / Capacitor WebView Wrapper (Recommended for Visuals)
You can build a React utility dashboard (like the webpage preview included here), and package it as a modern WebView application:
1. Initialize a **Capacitor** or **Cordova** shell around your web project:
   ```bash
   npm install @capacitor/core @capacitor/cli
   npx cap init "Synthetic Trading UI" "com.derivbot.app"
   ```
2. Build your React static exports (`dist` output folder):
   ```bash
   npm run build
   ```
3. Sync static HTML assets into Capacitor and launch in Android Studio to export an APK:
   ```bash
   npx cap add android
   npx cap copy
   npx cap open android
   ```

### Option B: The Python-to-APK Wrapper (Kivy / Buildozer)
If you want the Python bot CLI interface itself wrapped into an APK with a simple graphic overlay:
1. Install **Buildozer** in a Linux workspace (or Google Colab cell):
   ```bash
   pip install buildozer
   buildozer init
   ```
2. Configure `buildozer.spec` requirements to include `websocket-client` and compile:
   ```bash
   buildozer -v android debug
   ```
3. Find the compiled APK in your `bin/` directory and transfer it to your Samsung A21S for installation!

