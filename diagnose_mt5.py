#!/usr/bin/env python
"""
MT5 Connection Diagnostic Script
"""
import MetaTrader5 as mt5
import time
import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 50)
print("MT5 CONNECTION DIAGNOSTIC")
print("=" * 50)

# Load credentials
LOGIN = int(os.getenv("MT5_LOGIN", 0))
PASSWORD = os.getenv("MT5_PASSWORD", "")
SERVER = os.getenv("MT5_SERVER", "")
SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD")

print(f"\n📋 Configuration:")
print(f"  Login: {LOGIN}")
print(f"  Server: {SERVER}")
print(f"  Symbol: {SYMBOL}")

# Test 1: Check if module is loaded
print(f"\n✓ MetaTrader5 module version: {mt5.__version__ if hasattr(mt5, '__version__') else 'Unknown'}")

# Test 2: Try initializing with timeout handling
print(f"\n🔄 Attempting connection...")
try:
    result = mt5.initialize(
        login=LOGIN,
        password=PASSWORD,
        server=SERVER,
        timeout=10000  # 10 second timeout
    )
    
    if result:
        print("✅ SUCCESS: Connected to MT5!")
        
        # Get account info
        account = mt5.account_info()
        if account:
            print(f"\n📊 Account Info:")
            print(f"  Balance: {account.balance}")
            print(f"  Equity: {account.equity}")
            print(f"  Margin Free: {account.margin_free}")
        
        # Test symbol
        symbol_info = mt5.symbol_info(SYMBOL)
        if symbol_info:
            print(f"\n📈 Symbol {SYMBOL}:")
            print(f"  Bid: {symbol_info.bid}")
            print(f"  Ask: {symbol_info.ask}")
        else:
            print(f"\n⚠️  Symbol {SYMBOL} not found")
            
        mt5.shutdown()
    else:
        error = mt5.last_error()
        print(f"❌ FAILED: {error}")
        print(f"\nError Code: {error[0]}")
        print(f"Error Message: {error[1]}")
        
        if error[0] == -10005:
            print("\n🔧 IPC TIMEOUT - Troubleshooting:")
            print("  1. Is MT5 Terminal window visible on screen?")
            print("  2. Is the terminal frozen or unresponsive?")
            print("  3. Try: Tools > Options > Expert Advisors")
            print("     - Check: 'Allow Algorithmic Trading'")
            print("  4. Try restarting MT5 Terminal completely")
            print("  5. Check Windows Firewall settings")
            
except Exception as e:
    print(f"❌ EXCEPTION: {type(e).__name__}: {e}")

print("\n" + "=" * 50)
