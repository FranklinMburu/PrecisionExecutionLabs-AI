import asyncio
import config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mt5_connector import MT5Connector
from strategy import StraddleStrategy
import uvicorn
import os

app = FastAPI(title="MT5 Straddle Engine")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine instances
connector = MT5Connector(config.SYMBOL, config.MAGIC_NUMBER)
strategy = StraddleStrategy(connector)

@app.on_event("startup")
async def startup_event():
    print("[INIT] Starting MT5 Engine...")
    if connector.connect():
        connector.resolve_symbol()
    
    # Run the trading loop in the background
    asyncio.create_task(trading_loop_task())

async def trading_loop_task():
    print(f"[LOOP] Engine active on {connector.symbol}. Cycles every {config.LOOP_SLEEP}s.")
    while True:
        try:
            strategy.run()
        except Exception as e:
            print(f"[RECOVERY] Strategy Loop Error: {e}")
        await asyncio.sleep(config.LOOP_SLEEP)

@app.get("/api/status")
async def get_status():
    acc = connector.get_account()
    tick = connector.get_tick()
    
    full_r = strategy.r_values
    chart_len = 100
    slice_start = max(0, len(full_r) - chart_len)
    r_slice = full_r[slice_start:]
    baseline = sum(t['r'] if isinstance(t, dict) else t for t in full_r[:slice_start])

    return {
        "engine": {
            "symbol": connector.symbol,
            "connected": connector.connected if hasattr(connector, 'connected') else True,
            "mock_mode": connector.mock_mode if hasattr(connector, 'mock_mode') else False,
            "system_halted": strategy.system_halted,
            "shock_mode": strategy.shock_mode,
            "shock_cooldown": strategy.shock_cooldown,
            "oco_lock": strategy.oco_lock,
            "execution_lock": strategy.execution_lock,
            "risk_multiplier": strategy.risk_multiplier,
            "latency": connector.last_latency
        },
        "market": {
            "bid": tick.bid if tick else 0,
            "ask": tick.ask if tick else 0,
            "range": strategy.current_range,
            "avg_candle_body": strategy.avg_candle_body,
            "avg_spread": strategy.avg_spread
        },
        "account": {
            "balance": acc.balance if acc else 0,
            "equity": acc.equity if acc else 0,
            "profit": acc.profit if acc else 0,
            "total_risk_pct": strategy.calculate_total_risk() * 100
        },
        "stats": strategy.stats,
        "performance": {
            "expectancy": strategy.calculate_expectancy(),
            "std_r": strategy.calculate_std_r(),
            "r_values": r_slice,
            "r_baseline": baseline
        },
        "active_trade": strategy.active_trade,
        "active_trade_meta": strategy.active_trade_meta,
        "raw_orders": [o._asdict() if hasattr(o, '_asdict') else o for o in connector.get_orders()] if connector.get_orders() else [],
        "logs": strategy.logs
    }

@app.get("/api/stats")
async def get_stats():
    return {
        "stats": strategy.stats,
        "expectancy": strategy.calculate_expectancy(),
        "std_r": strategy.calculate_std_r(),
        "r_values": strategy.r_values,
        "system_halted": strategy.system_halted,
        "max_drawdown": strategy.max_drawdown_observed,
        "consecutive_losses": strategy.consecutive_losses
    }

@app.post("/api/reset")
async def reset_system():
    strategy.system_halted = False
    strategy.peak_equity = 0.0 # Reset peak to current for fresh drawdown tracking
    strategy.max_drawdown_observed = 0.0
    strategy.risk_multiplier = 1.0
    strategy.save_state()
    strategy.add_log("USER ACTION: System Overriden & Reset.")
    return {"status": "reset_complete"}

if __name__ == "__main__":
    # Get port from env (Vite proxy expects 8000)
    port = int(os.getenv("PYTHON_API_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
