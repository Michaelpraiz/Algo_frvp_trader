import MetaTrader5 as mt5
from dotenv import load_dotenv
import os

# Load credentials
load_dotenv()
account = os.getenv("MT5_LOGIN")
password = os.getenv("MT5_PASSWORD")
server = os.getenv("MT5_SERVER")

# Connect to MT5
if not mt5.initialize():
    print("MT5 initialization failed")
    exit()

if not mt5.login(int(account), password, server):
    print("Login failed")
    exit()

# Get all symbols
symbols = mt5.symbols_get()

print("\n" + "="*60)
print("AVAILABLE TRADING PAIRS IN YOUR MT5 ACCOUNT")
print("="*60 + "\n")

pair_list = []
for symbol in symbols:
    if symbol.visible:  # Only show visible symbols
        pair_list.append(symbol.name)

# Sort and display
pair_list.sort()
for i, pair in enumerate(pair_list, 1):
    print(f"{i:3}. {pair}")

print("\n" + "="*60)
print(f"Total Pairs Available: {len(pair_list)}")
print("="*60 + "\n")

mt5.shutdown()
