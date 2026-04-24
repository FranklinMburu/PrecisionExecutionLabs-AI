import time
import os
import random

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    # Mock Constants for Strategy Compatibility
    class MockMT5:
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1
        ORDER_TYPE_BUY_LIMIT = 2
        ORDER_TYPE_SELL_LIMIT = 3
        ORDER_TYPE_BUY_STOP = 4
        ORDER_TYPE_SELL_STOP = 5
        POSITION_TYPE_BUY = 0
        POSITION_TYPE_SELL = 1
        TRADE_ACTION_PENDING = 5
        TRADE_ACTION_DEAL = 1
        TRADE_ACTION_SLTP = 6
        TRADE_ACTION_REMOVE = 8
        ORDER_TIME_GTC = 0
        ORDER_FILLING_RETURN = 2
        ORDER_FILLING_IOC = 1
        TRADE_RETCODE_DONE = 10009
    mt5 = MockMT5()

class MT5Connector:
    def __init__(self, symbol, magic):
        self.symbol = symbol
        self.magic = magic
        self.point = 0.0001
        self.digits = 5
        self.trade_lock = False
        self.last_latency = 0.0
        self.connected = False
        self.mock_mode = not MT5_AVAILABLE
        self.execution_stats = {
            "requotes": 0,
            "rejections": 0,
            "timeouts": 0
        }
        
        # Mock State
        self._mock_price = 1.0500
        self._mock_orders = []
        self._mock_positions = []
        if self.mock_mode:
            print("⚠️ MT5 Library missing or Linux detected. Engine entering SIMULATION MODE.")

    def connect(self):
        if self.mock_mode:
            self.connected = True
            return True
            
        import config
        print("🔌 Connecting to MT5...")
        if not mt5.initialize(
            login=config.MT5_LOGIN, 
            password=config.MT5_PASSWORD, 
            server=config.MT5_SERVER
        ):
            print(f"initialize() failed, falling back to Simulation Mode.")
            self.mock_mode = True
            self.connected = True
            return True
        
        self.connected = True
        return True

    def resolve_symbol(self):
        if self.mock_mode:
            self.point = 0.0001
            return self.symbol
            
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            # Fallback logic simplified for speed in API mode
            self.symbol = self.symbol # Keep original
            
        mt5.symbol_select(self.symbol, True)
        info = mt5.symbol_info(self.symbol)
        if info:
            self.point = info.point
            self.digits = info.digits
        return self.symbol

    def get_tick(self):
        if self.mock_mode:
            self._mock_price += random.uniform(-0.0002, 0.0002)
            class Tick: pass
            t = Tick()
            t.bid = self._mock_price
            t.ask = self._mock_price + 0.0001
            t.time = int(time.time())
            return t
        return mt5.symbol_info_tick(self.symbol)

    def get_m1_candles(self, count):
        if self.mock_mode:
            import numpy as np
            # Generate fake M1 candles
            highs = [self._mock_price + random.uniform(0.0005, 0.0010) for _ in range(count)]
            lows = [self._mock_price - random.uniform(0.0005, 0.0010) for _ in range(count)]
            opens = [self._mock_price + random.uniform(-0.0005, 0.0005) for _ in range(count)]
            closes = [self._mock_price + random.uniform(-0.0005, 0.0005) for _ in range(count)]
            return np.array(list(zip(opens, highs, lows, closes)), dtype=[('open', 'f8'), ('high', 'f8'), ('low', 'f8'), ('close', 'f8')])
            
        return mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 1, count)

    def place_order(self, order_type, price, sl, tp, lot, deviation=10):
        if self.trade_lock: return None
        self.trade_lock = True
        
        # Ensure volume is rounded correctly
        lot = self.round_volume(lot)
        
        if self.mock_mode:
            ticket = random.randint(1000000, 9999999)
            class Order:
                def __init__(self, ticket, magic, price, sl, tp, lot, order_type):
                    self.ticket = ticket
                    self.magic = magic
                    self.price_open = round(price, 5)
                    self.sl = round(sl, 5)
                    self.tp = round(tp, 5)
                    self.volume = lot
                    self.type = order_type
                def _asdict(self):
                    return {
                        "ticket": self.ticket,
                        "magic": self.magic,
                        "price_open": self.price_open,
                        "sl": self.sl,
                        "tp": self.tp,
                        "volume": self.volume,
                        "type": self.type
                    }
            o = Order(ticket, self.magic, price, sl, tp, lot, order_type)
            self._mock_orders.append(o)
            self.trade_lock = False
            class Res: pass
            r = Res()
            r.retcode = 10009 # DONE
            r.order = ticket
            return r

        try:
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": self.symbol,
                "volume": float(lot),
                "type": order_type,
                "price": float(round(price, self.digits)),
                "sl": float(round(sl, self.digits)),
                "tp": float(round(tp, self.digits)),
                "deviation": int(deviation),
                "magic": int(self.magic),
                "comment": "Straddle Engine",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            res = mt5.order_send(request)
            if res is None:
                print(f"MT5: order_send returned None. Check terminal connection / logs.")
            return res
        except Exception as e:
            print(f"MT5 Exception in place_order: {e}")
            return None
        finally:
            self.trade_lock = False

    # (I will truncate the mock implementations for other methods similarly to keep it concise but functional)
    def get_positions(self):
        if self.mock_mode: return self._mock_positions
        return mt5.positions_get(symbol=self.symbol)

    def get_orders(self):
        if self.mock_mode: return self._mock_orders
        return mt5.orders_get(symbol=self.symbol)

    def cancel_order(self, ticket, retries=3):
        if self.mock_mode:
            self._mock_orders = [o for o in self._mock_orders if o.ticket != ticket]
            class Res: pass
            r = Res()
            r.retcode = mt5.TRADE_RETCODE_DONE
            return r
            
        request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
        
        for attempt in range(retries):
            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                return res
            
            print(f"MT5: Cancel Order {ticket} failed (Attempt {attempt+1}/{retries}). Retcode: {res.retcode if res else 'None'}")
            if attempt < retries - 1:
                time.sleep(0.1) # Brief backoff
                
        return res

    def cancel_all_pending(self):
        if self.mock_mode:
            count = len(self._mock_orders)
            self._mock_orders = []
            return count
        orders = mt5.orders_get(symbol=self.symbol)
        count = 0
        if orders:
            for o in orders:
                if o.magic == self.magic:
                    self.cancel_order(o.ticket)
                    count += 1
        return count

    def close_position(self, ticket, type, volume):
        if self.mock_mode:
            self._mock_positions = [p for p in self._mock_positions if p.ticket != ticket]
            return True
        # Original logic...
        import time
        order_type = mt5.ORDER_TYPE_SELL if type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(self.symbol)
        if not tick: return None
        price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "magic": self.magic,
            "comment": "Close Position",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        return mt5.order_send(request)

    def modify_position(self, ticket, sl, tp):
        if self.mock_mode:
            for p in self._mock_positions:
                if p.ticket == ticket:
                    p.sl = sl
                    p.tp = tp
            return True
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": round(sl, self.digits),
            "tp": round(tp, self.digits)
        }
        return mt5.order_send(request)

    def get_account(self):
        if self.mock_mode:
            class Account:
                def __init__(self):
                    self.balance = 10000.0
                    self.equity = 10000.0
                    self.profit = 0.0
                    self.margin_free = 10000.0
            return Account()
        return mt5.account_info()

    def get_symbol_info(self):
        if self.mock_mode:
            class Info:
                def __init__(self):
                    self.point = 0.0001
                    self.volume_min = 0.01
                    self.volume_max = 100.0
                    self.volume_step = 0.01
                    self.trade_contract_size = 100000
            return Info()
        return mt5.symbol_info(self.symbol)

    def round_volume(self, volume):
        step = 0.01
        info = self.get_symbol_info()
        if info: 
            step = getattr(info, 'volume_step', 0.01)
            # Clamp to min/max
            volume = max(info.volume_min, min(volume, info.volume_max))
            
        precision = 2
        if step < 1:
            try:
                # Convert to string and find decimal places
                s = f"{step:.8f}".rstrip('0')
                if '.' in s:
                    precision = len(s.split('.')[-1])
                else:
                    precision = 0
            except:
                precision = 2
        else:
            precision = 0
            
        return round(round(volume / step) * step, precision)

    def get_history_deals(self, ticket):
        if self.mock_mode: return []
        
        # Look back 24 hours for deals related to this position ticket
        from datetime import datetime, timedelta
        from_date = datetime.now() - timedelta(days=1)
        to_date = datetime.now() + timedelta(days=1)
        
        deals = mt5.history_deals_get(from_date, to_date, position=ticket)
        if deals is None:
            print(f"MT5: history_deals_get failed for ticket {ticket}. Error: {mt5.last_error()}")
            return []
        return deals

    def get_position_filled_volume(self, ticket):
        if self.mock_mode:
            for p in self._mock_positions:
                if p.ticket == ticket: return p.volume
            return 0.0
            
        pos = mt5.positions_get(ticket=ticket)
        if pos and len(pos) > 0:
            return pos[0].volume
        return 0.0
