import config
from mt5_connector import mt5
import time
import math
import json
import os

class StraddleStrategy:
    def __init__(self, connector):
        self.connector = connector
        self.active_trade = None
        self.current_range = None
        self.active_trade_meta = {}
        
        # Survival & Validation Specs
        self.consecutive_losses = 0
        self.cooldown_counter = 0
        self.day_start_balance = None
        self.last_day_check = 0 
        
        self.peak_equity = 0.0
        self.max_drawdown_observed = 0.0
        self.system_halted = False
        self.risk_multiplier = 1.0 # Current multiplier
        
        # Institutional Locks
        self.oco_lock = False
        self.execution_lock = False
        self.range_history = []
        self.candle_body_history = [] # For shock detection
        self.avg_candle_body = 0.0
        
        self.last_known_activity_time = time.time()
        self.shock_mode = False
        self.shock_cooldown = 0
        
        # Stats & Adaptive Specs
        self.spread_history = []
        self.avg_spread = 0.0
        self.r_values = []
        
        self.stats = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_r": 0.0,
            "win_r_sum": 0.0,
            "loss_r_sum": 0.0
        }
        
        self.state_file = f"state_{self.connector.magic}.json"
        self.logs = []
        self.load_state()

    def add_log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.insert(0, log_entry)
        if len(self.logs) > 100:
            self.logs.pop()
        print(log_entry)

    def save_state(self):
        state = {
            "stats": self.stats,
            "r_values": self.r_values,
            "active_trade": self.active_trade,
            "active_trade_meta": self.active_trade_meta,
            "peak_equity": self.peak_equity,
            "max_drawdown_observed": self.max_drawdown_observed,
            "consecutive_losses": self.consecutive_losses,
            "risk_multiplier": self.risk_multiplier,
            "system_halted": self.system_halted,
            "oco_lock": self.oco_lock,
            "execution_lock": self.execution_lock,
            "current_range": self.current_range
        }
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"Persistence Error (Save): {e}")

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.stats = state.get("stats", self.stats)
                    self.r_values = state.get("r_values", self.r_values)
                    self.active_trade = state.get("active_trade")
                    self.active_trade_meta = state.get("active_trade_meta", {})
                    self.peak_equity = state.get("peak_equity", 0.0)
                    self.max_drawdown_observed = state.get("max_drawdown_observed", 0.0)
                    self.consecutive_losses = state.get("consecutive_losses", 0)
                    self.risk_multiplier = state.get("risk_multiplier", 1.0)
                    self.system_halted = state.get("system_halted", False)
                    self.oco_lock = state.get("oco_lock", False)
                    self.execution_lock = state.get("execution_lock", False)
                    self.current_range = state.get("current_range")
                print(f"System State Recovered: {self.state_file}")
            except Exception as e:
                print(f"Persistence Error (Load): {e}")

    def update_daily_balance(self):
        now = time.time()
        if self.day_start_balance is None or (now - self.last_day_check > 86400):
            acc = self.connector.get_account()
            if acc:
                self.day_start_balance = acc.balance
                self.last_day_check = now
                
                # If current equity is much lower than peak, but we aren't in a massive trade,
                # it's likely a withdrawal or account change. Sync peak to avoid false HALT.
                if self.peak_equity > acc.equity:
                    print(f"Equity Sync: Adjusting peak {self.peak_equity:.2f} to {acc.equity:.2f} to prevent false drawdown halt.")
                    self.peak_equity = acc.equity
                    self.max_drawdown_observed = 0.0
                
                print(f"Daily Baseline Reset: {self.day_start_balance:.2f}")
                self.save_state()

    def update_spread_rolling(self, current_spread):
        self.spread_history.append(current_spread)
        if len(self.spread_history) > 20:
            self.spread_history.pop(0)
        self.avg_spread = sum(self.spread_history) / len(self.spread_history)

    def calculate_dynamic_buffer(self, range_pts):
        # Range size determines buffer percentage
        if range_pts < 500:
            buffer_pts = range_pts * 0.20    # 20% for small ranges (noise protection)
        elif range_pts < 2000:
            buffer_pts = range_pts * 0.15    # 15% for medium ranges
        else:
            buffer_pts = range_pts * 0.12    # 12% for large ranges (tight entries)

        # Enforce constraints
        buffer_pts = max(buffer_pts, 15)                    # Minimum 15 points
        buffer_pts = min(buffer_pts, range_pts * 0.25)     # Maximum 25% of range

        return buffer_pts

    def calculate_lot_size(self, entry, sl):
        acc = self.connector.get_account()
        sym_info = self.connector.get_symbol_info()
        if not acc or not sym_info: return 0.01
        
        # Effective Basis: Use the lowest of balance or equity to be conservative
        effective_basis = min(acc.balance, acc.equity)
        
        # Guard: If equity is extremely low, return minimum lot
        if effective_basis < 10: return sym_info.volume_min 

        # Risk amount based on equity and risk buffer
        # config.RISK_PER_TRADE = 0.02 (2%)
        risk_amount = (effective_basis * config.RISK_PER_TRADE * self.risk_multiplier) / config.SLIPPAGE_RISK_BUFFER
        
        sl_dist = abs(entry - sl)
        if sl_dist == 0: return sym_info.volume_min
        
        # Standard FX/Metal lot formula: Lot = Risk / (Distance * Contract Size)
        raw_lot = risk_amount / (sl_dist * sym_info.trade_contract_size)
        
        # Clamp to broker limits
        lot = max(sym_info.volume_min, min(raw_lot, sym_info.volume_max))
        
        return self.connector.round_volume(lot)

    def track_drawdown(self, equity):
        if equity > self.peak_equity:
            self.peak_equity = equity
            self.save_state()
        
        if self.peak_equity > 0:
            dd = (self.peak_equity - equity) / self.peak_equity
            if dd > self.max_drawdown_observed:
                self.max_drawdown_observed = dd
                self.save_state()
            
            # STICKY RISK REDUCTION
            if dd >= config.SOFT_DRAWDOWN_LIMIT:
                if self.risk_multiplier > 0.5:
                    self.risk_multiplier = 0.5
                    self.save_state()
            elif dd <= 0.05: 
                if self.risk_multiplier < 1.0:
                    self.risk_multiplier = 1.0
                    self.save_state()

            if dd >= config.MAX_DRAWDOWN_STOP:
                self.add_log(f"CRITICAL: Max Drawdown Reached ({dd:.2%}). System Halted.")
                self.system_halted = True
                self.save_state()

    def calculate_std_r(self):
        if len(self.r_values) < 2: return 0.0
        mean = sum(self.r_values) / len(self.r_values)
        variance = sum((x - mean) ** 2 for x in self.r_values) / len(self.r_values)
        return math.sqrt(variance)

    def calculate_expectancy(self):
        if self.stats["total_trades"] == 0: return 0.0
        total = self.stats["total_trades"]
        win_rate = self.stats["wins"] / total
        loss_rate = self.stats["losses"] / total
        avg_win_r = (self.stats["win_r_sum"] / self.stats["wins"]) if self.stats["wins"] > 0 else 0
        avg_loss_r = (abs(self.stats["loss_r_sum"]) / self.stats["losses"]) if self.stats["losses"] > 0 else 0
        return (win_rate * avg_win_r) - (loss_rate * avg_loss_r)

    def calculate_total_risk(self):
        acc = self.connector.get_account()
        sym_info = self.connector.get_symbol_info()
        if not acc or not sym_info: return 0.00
        
        total_risk = 0.0
        
        # Open positions risk (with slippage factor)
        positions = self.connector.get_positions()
        if positions:
            for p in positions:
                if p.magic == self.connector.magic and p.sl > 0:
                    risk = abs(p.price_open - p.sl) * p.volume * sym_info.trade_contract_size
                    total_risk += (risk * config.SLIPPAGE_RISK_BUFFER)
        
        # Pending orders risk
        orders = self.connector.get_orders()
        if orders:
            for o in orders:
                if o.magic == self.connector.magic and o.sl > 0:
                    risk = abs(o.price_open - o.sl) * o.volume_initial * sym_info.trade_contract_size
                    total_risk += (risk * config.SLIPPAGE_RISK_BUFFER)
                        
        return total_risk / acc.balance

    def check_survival_rules(self, range_points):
        if self.system_halted: return False
        
        self.update_daily_balance()
        acc = self.connector.get_account()
        if not acc: return False
        
        # 1. Equity & Drawdown Check
        effective_equity = min(acc.equity, acc.balance)
        self.track_drawdown(effective_equity)
        if self.system_halted: return False

        # 2. Market Shock Detection
        candles_m1 = self.connector.get_m1_candles(10)
        if candles_m1 is not None and len(candles_m1) >= 10:
            bodies = [abs(c['close'] - c['open']) for c in candles_m1]
            self.avg_candle_body = sum(bodies) / len(bodies)
            last_body = bodies[-1]
            
            if last_body > config.MARKET_SHOCK_MULTIPLIER * self.avg_candle_body:
                self.add_log(f"MARKET SHOCK DETECTED → Cooldown active.")
                self.shock_mode = True
                self.shock_cooldown = config.SHOCK_STABILIZATION_CYCLES
            
        if self.shock_cooldown > 0:
            self.shock_cooldown -= 1
            if self.shock_cooldown == 0: 
                self.add_log("SHOCK: Stabilization complete.")
                self.shock_mode = False
            return False

        # 3. Daily Loss Limit
        if (self.day_start_balance - effective_equity) / self.day_start_balance >= config.DAILY_LOSS_LIMIT:
            print("CRITICAL: Daily Loss Limit. Stopping.")
            return False

        # 4. Open Risk Exposure Control
        risk_pct = self.calculate_total_risk()
        if risk_pct >= config.MAX_TOTAL_EXPOSURE:
            print(f"Exposure at limit ({risk_pct:.2%}). Skip.")
            return False

        # 5. Minimum Range Size
        if range_points < config.MIN_RANGE_POINTS:
            return False
            
        # 6. Spread vs Profit Ratio (Friction Shield)
        tick = self.connector.get_tick()
        if tick:
            spread_pts = (tick.ask - tick.bid) / self.connector.point
            tp_dist_est = range_points * 3 
            friction_ratio = spread_pts / tp_dist_est if tp_dist_est > 0 else 1.0
            if friction_ratio > config.MAX_FRICTION_RATIO:
                print(f"Friction Shield: Spread/TP ratio too high ({friction_ratio:.2f}). Skip.")
                return False

        # 7. Market Compression Detection
        self.range_history.append(range_points)
        if len(self.range_history) > config.RANGE_SHRINK_CHECK_WINDOW:
            self.range_history.pop(0)

        if len(self.range_history) == config.RANGE_SHRINK_CHECK_WINDOW:
            if all(self.range_history[i] < self.range_history[i-1] for i in range(1, len(self.range_history))):
                print("Market Compression Detected → Wait for expansion.")
                return False
                
        # 8. Spread Spike Filter
        if tick:
            spread_pts = (tick.ask - tick.bid) / self.connector.point
            self.update_spread_rolling(spread_pts)
            
            spread_ratio = spread_pts / range_points
            if spread_ratio > config.MAX_SPREAD_RATIO:
                return False

            if len(self.spread_history) >= 10:
                if spread_pts > self.avg_spread * 2:
                    print("Spread spike detected → Skip.")
                    return False

        # 9. Rollover Hours Filter
        if tick:
            hour = time.gmtime(tick.time).tm_hour
            if hour in config.ROLLOVER_HOURS_UTC:
                return False

        # 10. Expectancy & Performance Kill Switch
        if self.stats["total_trades"] >= config.EXPECTANCY_VALIDATION_WINDOW:
            exp = self.calculate_expectancy()
            if exp <= 0:
                print(f"Negative Expectancy ({exp:.2f}) → System halted.")
                self.system_halted = True
                self.save_state()
                return False

        return True

    def record_performance(self, ticket):
        deals = self.connector.get_history_deals(ticket)
        if not deals: return
        
        total_p = sum(d.profit + d.commission + d.swap for d in deals)
        risk_at_entry = self.active_trade.get('risk_at_entry', 1.0)
        
        r_multiple = total_p / risk_at_entry if risk_at_entry > 0 else 0
        
        self.stats["total_trades"] += 1
        self.stats["total_r"] += r_multiple
        self.r_values.append(r_multiple)
        
        if total_p > 0:
            self.stats["wins"] += 1
            self.stats["win_r_sum"] += r_multiple
            self.consecutive_losses = 0
            print(f"WIN | Profit: {total_p:.2f} | R: {r_multiple:.2f}")
        else:
            self.stats["losses"] += 1
            self.stats["loss_r_sum"] += r_multiple
            self.consecutive_losses += 1
            self.cooldown_counter = min(3, self.consecutive_losses * 2) # Weighted cooling
            print(f"LOSS | R: {r_multiple:.2f} | Consecutive Losses: {self.consecutive_losses}")

        self.save_state()

    def manage_position(self, pos):
        # 1. IMMEDIATE OCO (Priority #1)
        # Kill all pending orders immediately if a position is live
        # Enhanced to ensure it keeps trying until all pending magic-matched orders are gone
        if not self.oco_lock:
            self.add_log("OCO: Trigger detected. Purging non-triggered side...")
            attempts = 0
            while attempts < 3:
                count = self.connector.cancel_all_pending()
                orders = self.connector.get_orders()
                matched_orders = [o for o in orders if o.magic == self.connector.magic] if orders else []
                if not matched_orders:
                    self.oco_lock = True
                    break
                attempts += 1
                time.sleep(0.05) # Micro-sleep for MT5 state sync
            
            if not self.oco_lock:
                self.add_log("WARNING: OCO failed to clear all pending orders after retries.")
            self.save_state()

        tick = self.connector.get_tick()
        if not tick: return
        live_price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
        
        # Realized Volume Verification
        real_vol = self.connector.get_position_filled_volume(pos.ticket)
        if real_vol <= 0:
            real_vol = pos.volume # Fallback

        # 2. HARD SL ENFORCEMENT (Broker Safety Fix)
        # CRITICAL: This MUST NOT be skipped by latency filters
        if pos.sl == 0:
            self.add_log(f"CRITICAL: Ticket {pos.ticket} has NO SL. Attempting emergency enforcement...")
            
            # Calculate emergency SL based on context
            emergency_sl = self.active_trade_meta.get('range_low') if pos.type == mt5.POSITION_TYPE_BUY else self.active_trade_meta.get('range_high')
            
            # Fallback to current range if meta is missing
            if not emergency_sl and self.current_range:
                emergency_sl = self.current_range['low'] if pos.type == mt5.POSITION_TYPE_BUY else self.current_range['high']
            
            # Absolute last resort fallback (e.g., 500 points)
            if not emergency_sl:
                pts = 500 * self.connector.point
                emergency_sl = pos.price_open - pts if pos.type == mt5.POSITION_TYPE_BUY else pos.price_open + pts

            if emergency_sl:
                success = False
                # Institutional Loop: Phase 1 - Try to set SL directly
                for attempt in range(3):
                    res_mod = self.connector.modify_position(pos.ticket, emergency_sl, pos.tp)
                    if res_mod and res_mod.retcode == mt5.TRADE_RETCODE_DONE:
                        self.add_log(f"Emergency SL applied successfully on attempt {attempt+1}.")
                        success = True
                        break
                    time.sleep(0.1 * (attempt + 1)) # Small linear backoff

                # Phase 2: If Phase 1 failed, reduce exposure and try again
                if not success:
                    self.add_log("Emergency SL Phase 1 failed. Reducing exposure by 50%...")
                    half_vol = self.connector.round_volume(real_vol * 0.5)
                    self.connector.close_position(pos.ticket, pos.type, half_vol)
                    
                    for attempt in range(3):
                        res_mod = self.connector.modify_position(pos.ticket, emergency_sl, pos.tp)
                        if res_mod and res_mod.retcode == mt5.TRADE_RETCODE_DONE:
                            self.add_log(f"Emergency SL applied after reduction on attempt {attempt+1}.")
                            success = True
                            break
                        time.sleep(0.2)

                # Phase 3: Fatal Failure Guard - Flatten Everything
                if not success:
                    self.add_log("CRITICAL: ALL EMERGENCY SL ATTEMPTS FAILED. Flattening position immediately.")
                    self.connector.close_position(pos.ticket, pos.type, pos.volume)
                    self.system_halted = True
                    self.save_state()
        
        # Latency Awareness: Skip only non-critical updates if lagging
        is_lagging = self.connector.last_latency > 0.8
        if is_lagging:
            print(f"LATE UPDATE ({self.connector.last_latency:.3f}s) → Skipping non-critical trailing.")

        # State Recovery & Slippage Guard
        if self.active_trade is None or self.active_trade['ticket'] != pos.ticket:
            sym_info = self.connector.get_symbol_info()
            expected_entry = self.active_trade_meta.get('buy_entry') if pos.type == mt5.POSITION_TYPE_BUY else self.active_trade_meta.get('sell_entry')
            if expected_entry is None: expected_entry = pos.price_open
            
            risk_at_entry = abs(pos.price_open - pos.sl) * pos.volume * sym_info.trade_contract_size if pos.sl > 0 else 0
            r_dist = abs(pos.price_open - pos.sl)

            slippage = abs(pos.price_open - expected_entry)
            if r_dist > 0 and slippage > (0.3 * r_dist):
                print(f"CRITICAL SLIPPAGE ({slippage / self.connector.point:.0f} pts) → Exit.")
                self.connector.close_position(pos.ticket, pos.type, pos.volume)
                return

            self.active_trade = {
                "ticket": pos.ticket,
                "type": "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL",
                "entry": pos.price_open,
                "initial_sl": pos.sl if pos.sl > 0 else (self.active_trade_meta.get('range_low') if pos.type == mt5.POSITION_TYPE_BUY else self.active_trade_meta.get('range_high')),
                "risk_at_entry": risk_at_entry,
                "tp": pos.tp,
                "breakeven_moved": False,
                "partial_closed": False,
                "highest_price": live_price if pos.type == mt5.POSITION_TYPE_BUY else 0.0,
                "lowest_price": live_price if pos.type == mt5.POSITION_TYPE_SELL else 999999.0,
                "last_trail_time": 0
            }
            self.save_state()

        if self.active_trade['type'] == "BUY":
            if live_price > self.active_trade['highest_price']:
                self.active_trade['highest_price'] = live_price
        else:
            if live_price < self.active_trade['lowest_price']:
                self.active_trade['lowest_price'] = live_price

        # Fake Breakout Logic (Buffered)
        r_dist_val = abs(self.active_trade['entry'] - self.active_trade['initial_sl'])
        if r_dist_val <= 0: return
        
        # Get recent candles
        candles = self.connector.get_m1_candles(3)
        if candles is not None and len(candles) >= 3:
            last_closed = candles[-1]['close']
            
            # Use adaptive buffer (same as entry buffer)
            entry_buffer = self.active_trade_meta.get('buffer_size', 100)
            price_buffer = entry_buffer * self.connector.point
            
            if self.current_range and 'high' in self.current_range and 'low' in self.current_range:
                if self.active_trade['type'] == "BUY" and last_closed < (self.current_range['high'] - price_buffer):
                    self.add_log("Fake breakout detected → Exit trade.")
                    self.connector.close_position(pos.ticket, pos.type, pos.volume)
                    return
                elif self.active_trade['type'] == "SELL" and last_closed > (self.current_range['low'] + price_buffer):
                    self.add_log("Fake breakout detected → Exit trade.")
                    self.connector.close_position(pos.ticket, pos.type, pos.volume)
                    return

        if is_lagging: return # End of critical section

        # Continuous Trailing Logic (Institutional Ladder)
        profit_points = abs(live_price - self.active_trade['entry'])
        r_multiple = profit_points / r_dist_val

        # 1. 1R PARTIAL CLOSE (Primary Risk Off)
        if not self.active_trade['partial_closed'] and r_multiple >= 1.0:
            current_vol = self.connector.get_position_filled_volume(pos.ticket)
            if current_vol <= 0: current_vol = pos.volume 
            
            half_vol = self.connector.round_volume(current_vol / 2)
            self.add_log(f"1R Target Hit: Closing {half_vol} and moving to BE.")
            res_close = self.connector.close_position(pos.ticket, pos.type, half_vol)
            res_mod = self.connector.modify_position(pos.ticket, self.active_trade['entry'], pos.tp)
            
            if res_close:
                self.active_trade['partial_closed'] = True
                if res_mod: self.active_trade['breakeven_moved'] = True
            else:
                self.active_trade['failure_count'] = self.active_trade.get('failure_count', 0) + 1
            self.save_state()

        # 2. PROGRESSION TRAILING (Step Logic)
        if self.active_trade['partial_closed']:
            new_step_sl = 0.0
            move_step_sl = False
            
            # Simple steps if momentum isn't explosive
            if r_multiple >= 1.5 and r_multiple < 2.0:
                new_step_sl = self.active_trade['entry'] + (0.5 * r_dist_val) if self.active_trade['type'] == "BUY" else self.active_trade['entry'] - (0.5 * r_dist_val)
                move_step_sl = True
            elif r_multiple >= 2.0:
                new_step_sl = self.active_trade['entry'] + (1.2 * r_dist_val) if self.active_trade['type'] == "BUY" else self.active_trade['entry'] - (1.2 * r_dist_val)
                move_step_sl = True
                
            if move_step_sl:
                is_better = (new_step_sl > pos.sl) if self.active_trade['type'] == "BUY" else (new_step_sl < pos.sl or pos.sl == 0)
                if is_better:
                    # self.add_log(f"Trailing Progression: SL to {new_step_sl:.5f} ({r_multiple:.2f}R)")
                    self.connector.modify_position(pos.ticket, new_step_sl, pos.tp)

        # 3. INTELLIGENT TRAILING STOP ENGINE (Primary Active Trailing)
        # Activation: Only trail if min profit R is reached AND one leg has been purged (oco_lock)
        is_trail_active = getattr(config, 'TRAILING_STOP_ENABLE', False)
        if is_trail_active and self.oco_lock and r_multiple >= getattr(config, 'TRAILING_STOP_MIN_PROFIT_R', 0.5):
            
            # Layer A: 1-Minute Intelligence Filter (Intelligence Layer)
            candles_m1 = self.connector.get_m1_candles(10)
            vol_mult = 1.0
            momentum_mult = 1.0
            confirmed_breakout = False
            
            if candles_m1 is not None and len(candles_m1) >= 5:
                # 1. Volatility (ATR-based)
                tr = [max(c['high'] - c['low'], abs(c['high'] - candles_m1[i-1]['close'])) for i, c in enumerate(candles_m1) if i > 0]
                atr = sum(tr) / len(tr)
                
                # 2. Trend Strength Analysis
                last_3 = candles_m1[-3:]
                trend_dir = 0
                for c in last_3:
                    if self.active_trade['type'] == "BUY" and c['close'] > c['open']: trend_dir += 1
                    if self.active_trade['type'] == "SELL" and c['close'] < c['open']: trend_dir += 1
                
                # Slower/Wider trail in weak trends, tighter in blow-off moves
                sensitivity = getattr(config, 'TRAILING_STOP_MOMENTUM_SENSITIVITY', 0.5)
                if trend_dir == 3: # Strong momentum
                    momentum_mult = 0.85 + (1.0 - 0.85) * (1.0 - sensitivity) # Tighter
                elif trend_dir <= 1: # Choppy / Counter-trend
                    momentum_mult = 1.2 + (1.5 - 1.2) * sensitivity # Wider

                # Volatility Adaptation
                if self.avg_candle_body > 0:
                    vol_ratio = atr / self.avg_candle_body
                else:
                    vol_ratio = 1.0
                vol_mult = max(0.7, min(1.8, vol_ratio)) # High vol = widen (safety), Low vol = tighten

                # 3. Breakout Confirmation Rule (Anti-Spike Filter)
                # Only "accept" the new highest_price if price is above the last 1min high/low + buffer
                m1_threshold = candles_m1[-1]['high'] if self.active_trade['type'] == "BUY" else candles_m1[-1]['low']
                threshold_buffer = 10 * self.connector.point
                
                if (self.active_trade['type'] == "BUY" and live_price > m1_threshold + threshold_buffer) or \
                   (self.active_trade['type'] == "SELL" and live_price < m1_threshold - threshold_buffer):
                    confirmed_breakout = True

            # Execution Layer: Compute Trial SL
            mode = getattr(config, 'TRAILING_STOP_MODE', 'FIXED')
            base_dist = 0.0
            if mode == "FIXED":
                base_dist = getattr(config, 'TRAILING_STOP_FIXED_POINTS', 150) * self.connector.point
            elif mode == "PERCENTAGE":
                base_dist = live_price * getattr(config, 'TRAILING_STOP_PERCENT', 0.001)
            elif mode == "VOLATILITY":
                # Fallback to fixed if ATR calc failed
                base_dist = atr * getattr(config, 'TRAILING_STOP_VOL_ATR_MULT', 1.5) if 'atr' in locals() else (150 * self.connector.point)

            # Apply Intelligence Multipliers
            final_dist = base_dist * vol_mult * momentum_mult
            
            # Anti-Flush Rule: Never trail closer than 0.3R of the current range
            min_safety_dist = (self.current_range['high'] - self.current_range['low']) * 0.3 if self.current_range else 0
            final_dist = max(final_dist, min_safety_dist)

            new_trail_sl = 0.0
            if self.active_trade['type'] == "BUY":
                new_trail_sl = self.active_trade['highest_price'] - final_dist
            else:
                new_trail_sl = self.active_trade['lowest_price'] + final_dist
            
            # Movement Validation
            is_better = (new_trail_sl > pos.sl) if self.active_trade['type'] == "BUY" else (new_trail_sl < pos.sl or pos.sl == 0)
            
            # Step Filter (Price & Time Cooldown)
            step_pts = getattr(config, 'TRAILING_STOP_STEP_POINTS', 30) * self.connector.point
            price_step_met = abs(new_trail_sl - pos.sl) >= step_pts if pos.sl > 0 else True
            time_cooldown_met = (time.time() - self.active_trade.get('last_trail_time', 0)) > 5 # 5-sec cooldown
            
            # Final Decision: Better direction + Price Step + Time Cooldown + Breakout Confirmation
            if is_better and price_step_met and time_cooldown_met and confirmed_breakout:
                self.add_log(f"TRAIL: Advancing to {new_trail_sl:.5f} (Confirmed Breakout | Vol: {vol_mult:.2f}x | Dist: {final_dist/self.connector.point:.0f}pts)")
                self.connector.modify_position(pos.ticket, new_trail_sl, pos.tp)
                self.active_trade['last_trail_time'] = time.time()
                self.save_state()

        # 4. TAKE PROFIT TRAILING (Momentum Expansion)
        if hasattr(config, 'TP_TRAILING_ENABLE') and config.TP_TRAILING_ENABLE and self.active_trade['partial_closed']:
            if r_multiple >= config.TP_TRAILING_START_R:
                tp_buffer = 1.0 * r_dist_val # Maintain 1R breathing room
                new_tp = (live_price + tp_buffer) if self.active_trade['type'] == "BUY" else (live_price - tp_buffer)
                
                is_farther = (new_tp > pos.tp) if self.active_trade['type'] == "BUY" else (new_tp < pos.tp or pos.tp == 0)
                move_dist = abs(new_tp - pos.tp) if pos.tp > 0 else 999
                
                if is_farther and move_dist >= (config.TP_TRAILING_STEP_R * r_dist_val):
                    self.add_log(f"TP TRAIL: Extending TP to {new_tp:.5f} ({r_multiple:.2f}R)")
                    self.connector.modify_position(pos.ticket, pos.sl, new_tp)
                    self.active_trade['tp'] = new_tp
                    self.save_state()

        # 5. STUCK POSITION GUARD
        if self.active_trade.get('failure_count', 0) >= config.STUCK_POSITION_THRESHOLD:
            self.add_log(f"CRITICAL: Stuck position detected ({self.active_trade['failure_count']} fails) → Purging.")
            self.connector.close_position(pos.ticket, pos.type, pos.volume)
            self.system_halted = True
            self.save_state()


    def emergency_resolution(self, positions):
        print("ALERT: DOUBLE FILL DETECTED (BUY & SELL BOTH LIVE) → Emergency Resolution.")
        # Flatten everything immediately. Do not try to hedge or net in a high-speed error state.
        for p in positions:
            if p.magic == self.connector.magic:
                self.connector.close_position(p.ticket, p.type, p.volume)
        
        self.system_halted = True
        self.save_state()

    def run(self):
        # 0. HARD GUARD: Do not process if ANY position or order exists for this magic
        positions = self.connector.get_positions()
        orders = self.connector.get_orders()
        
        matched_positions = [p for p in positions if p.magic == self.connector.magic] if positions else []
        matched_orders = [o for o in orders if o.magic == self.connector.magic] if orders else []
        
        has_positions = len(matched_positions) > 0
        has_orders = len(matched_orders) > 0

        # PROACTIVE OCO: Detect fill during the "shadow period" before MT5 reports a position
        if not has_positions and self.execution_lock and len(matched_orders) == 1 and not self.oco_lock:
            # Check if we were expecting 2 orders
            # (Note: we'll update active_trade_meta with the initial count during placement)
            expected_count = self.active_trade_meta.get('expected_order_count', 0)
            if expected_count == 2:
                self.add_log("OCO (Proactive): Pending order missing - likely filled. Purging residual side early.")
                self.connector.cancel_all_pending()
                self.oco_lock = True
                self.save_state()

        # Double Fill / Hedge Error Resolution (Institutional upgrade)
        if len(matched_positions) > 1:
            self.emergency_resolution(matched_positions)
            return

        # Activity confirmation buffer (State Drift Guard)
        if has_positions or has_orders:
            self.last_known_activity_time = time.time()

        # Execution Lock Reset with Grace Period
        if not has_positions and not has_orders:
            # Require 3s of "nothing" before resetting locks to avoid API lag misfires
            if time.time() - self.last_known_activity_time > 3.0:
                if self.oco_lock or self.execution_lock:
                    print("Activity Buffer Clear → Resetting locks.")
                    self.oco_lock = False
                    self.execution_lock = False
                    self.save_state()

        if has_positions:
            # Manage existing position
            matched_pos = [p for p in positions if p.magic == self.connector.magic][0]
            self.manage_position(matched_pos)
            return
        elif self.active_trade:
            # Position just closed
            self.record_performance(self.active_trade['ticket'])
            self.active_trade = None
            self.save_state()

        if has_orders or self.execution_lock:
            # TTL Expiry for pending orders (Only if NO position exists)
            order_time = self.active_trade_meta.get('order_timestamp', 0)
            if has_orders and not has_positions and order_time > 0:
                if time.time() - order_time > config.PENDING_EXPIRY_SEC_TTL:
                    print("TTL Expired → Cancelling stale pending orders.")
                    self.connector.cancel_all_pending()
                    self.execution_lock = False
                    self.save_state()
            return

        # 1. Market Data
        candles = self.connector.get_m1_candles(config.RANGE_LOOKBACK)
        if candles is None or len(candles) == 0: return

        range_high = max(candles['high'])
        range_low = min(candles['low'])
        r_pts = (range_high - range_low) / self.connector.point

        # 2. Checks
        if not self.check_survival_rules(r_pts): return

        # 3. Setup
        self.current_range = {"high": range_high, "low": range_low}
        
        # Calculate dynamic buffer
        buffer_pts_dynamic = self.calculate_dynamic_buffer(r_pts)
        buffer_price = buffer_pts_dynamic * self.connector.point
        
        # Set entry points
        buy_p = range_high + buffer_price      # BUY entry above range
        sell_p = range_low - buffer_price      # SELL entry below range

        # Set Stop Loss points
        buy_sl = range_low                      # BUY's SL at range bottom
        sell_sl = range_high                    # SELL's SL at range top

        # Set Take Profit points (3R)
        buy_tp = buy_p + (buy_p - buy_sl) * 3
        sell_tp = sell_p - (sell_sl - sell_p) * 3
        
        # Meta persistence with range recovery
        self.active_trade_meta = {
            "buy_entry": buy_p,
            "sell_entry": sell_p,
            "range_high": range_high,
            "range_low": range_low,
            "order_timestamp": time.time(),
            "expected_order_count": 2,
            "buffer_size": buffer_pts_dynamic
        }
        self.save_state()

        lot = self.calculate_lot_size(buy_p, buy_sl)
        tick = self.connector.get_tick()
        spread_pts = (tick.ask - tick.bid) / self.connector.point
        dev = int(spread_pts) + 10
        
        print(f"--- SENSING BREAKOUT ---")
        print(f"Range: {range_low:.2f} - {range_high:.2f} ({r_pts:.0f} pts) | Buffer: {buffer_pts_dynamic:.1f} pts")
        
        # Place both orders
        res_buy = self.connector.place_order(
            order_type=mt5.ORDER_TYPE_BUY_STOP,
            price=buy_p,
            sl=buy_sl,
            tp=buy_tp,
            lot=lot,
            deviation=dev
        )
        
        res_sell = self.connector.place_order(
            order_type=mt5.ORDER_TYPE_SELL_STOP,
            price=sell_p,
            sl=sell_sl,
            tp=sell_tp,
            lot=lot,
            deviation=dev
        )
        
        if res_buy and res_sell:
            self.execution_lock = True
            self.add_log(f"EXEC: Pending straddle placed (Size: {lot} lots @ {buy_p:.5f} / {sell_p:.5f})")
            self.save_state()
            print(f"BUY STOP @ {buy_p:.2f} | SL: {buy_sl:.2f} | TP: {buy_tp:.2f}")
            print(f"SELL STOP @ {sell_p:.2f} | SL: {sell_sl:.2f} | TP: {sell_tp:.2f}")
            print(f"Spread: {spread_pts:.0f} | Risk: {self.risk_multiplier*100:.0f}% | LOT: {lot}")
        else:
            print("ERROR: Failed to place straddle orders.")
            self.execution_lock = False
            return

        # Post-placement Verification (Phantom Fill Guard)
        time.sleep(0.5) # Brief pause for MT5 sync
        live_orders = self.connector.get_orders()
        matched_live = [o for o in live_orders if o.magic == self.connector.magic] if live_orders else []
        actual_count = len(matched_live)
        
        # PROOF 2: Stop Loss Verification on Pending Orders
        for o in matched_live:
            if o.sl == 0:
                print(f"CRITICAL: Order {o.ticket} accepted without SL. Broker Policy Violation. Cancelling.")
                self.connector.cancel_order(o.ticket)
                self.execution_lock = False
                return

        if actual_count == 0:
            print("CRITICAL: Placement verification failed (Phantom Fill) → Resetting lock.")
            self.execution_lock = False
            self.stats["consecutive_failures"] = self.stats.get("consecutive_failures", 0) + 1
            if self.stats["consecutive_failures"] >= 3:
                self.system_halted = True
        else:
            self.stats["consecutive_failures"] = 0
            print(f"Verified {actual_count} orders in book.")
            
        self.save_state()
