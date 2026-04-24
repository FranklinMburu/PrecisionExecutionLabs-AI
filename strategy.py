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
                print(f"Daily Baseline Reset: {self.day_start_balance:.2f}")

    def update_spread_rolling(self, current_spread):
        self.spread_history.append(current_spread)
        if len(self.spread_history) > 20:
            self.spread_history.pop(0)
        self.avg_spread = sum(self.spread_history) / len(self.spread_history)

    def calculate_lot_size(self, entry, sl):
        acc = self.connector.get_account()
        sym_info = self.connector.get_symbol_info()
        if not acc or not sym_info: return 0.01
        
        # Effective Basis: Use the lowest of balance or equity to be conservative
        effective_basis = min(acc.balance, acc.equity)
        
        # Guard: If equity is extremely low, return minimum lot
        if effective_basis < 10: return sym_info.volume_min 

        # Risk amount based on equity and risk multiplier
        current_risk_pct = getattr(config, 'RISK_PER_TRADE_PERCENT', 1.0) / 100
        risk_amount = effective_basis * current_risk_pct * self.risk_multiplier
        
        # Apply slippage factor (Assume actual loss could be 20% worse than SL in news)
        protected_risk_amount = risk_amount / 1.2 
        
        sl_dist = abs(entry - sl)
        if sl_dist == 0: return sym_info.volume_min
        
        # Standard FX/Metal lot formula: Lot = Risk / (Distance * Contract Size)
        raw_lot = protected_risk_amount / (sl_dist * sym_info.trade_contract_size)
        
        # Clamp to broker limits
        lot = max(sym_info.volume_min, min(raw_lot, sym_info.volume_max))
        
        # Margin Check: Ensure we don't use more than 50% of free margin
        # Estimated margin (simplified assuming leverage 1:30)
        est_margin = (lot * sym_info.trade_contract_size * entry) / 30
        if est_margin > acc.margin_free * 0.5:
             lot = (acc.margin_free * 0.5) / (sym_info.trade_contract_size * entry / 30)
             lot = max(sym_info.volume_min, lot)

        print(f"Audit: Basis {effective_basis:.2f} | Risk $: {risk_amount:.2f} | Final Lot: {lot}")
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
                    risk = abs(o.price_open - o.sl) * o.volume * sym_info.trade_contract_size
                    total_risk += (risk * config.SLIPPAGE_RISK_BUFFER)
                        
        return total_risk / acc.balance

    def check_survival_rules(self, range_points):
        if self.system_halted: return False
        
        self.update_daily_balance()
        acc = self.connector.get_account()
        if not acc: return False
        
        # Equity sync delay buffer
        effective_equity = min(acc.equity, acc.balance)
        self.track_drawdown(effective_equity)
        if self.system_halted: return False

        # MARKET SHOCK DETECTION & STABILIZATION
        candles_m1 = self.connector.get_m1_candles(10)
        if candles_m1 is not None and len(candles_m1) >= 10:
            bodies = [abs(c['close'] - c['open']) for c in candles_m1]
            self.avg_candle_body = sum(bodies) / len(bodies)
            last_body = bodies[-1]
            
            # Detect shock
            if last_body > 3.0 * self.avg_candle_body:
                self.add_log(f"SHOCK: Volatility spike ({last_body:.2f} vs {self.avg_candle_body:.2f}) → Stabilization active.")
                self.shock_mode = True
                self.shock_cooldown = config.SHOCK_STABILIZATION_CYCLES
            
        if self.shock_cooldown > 0:
            # Dynamic Shock Recovery: Require volatility to be returning to normal
            if self.avg_candle_body > 0 and candles_m1 is not None:
                last_vol = abs(candles_m1[-1]['close'] - candles_m1[-1]['open'])
                if last_vol > 1.5 * self.avg_candle_body:
                    print("Shock Recovery Delayed: Volatility still high.")
                    return False
            
            self.shock_cooldown -= 1
            if self.shock_cooldown == 0: 
                self.add_log("SHOCK: Stabilization complete. Resuming scanner.")
                self.shock_mode = False
            return False

        # Daily Loss
        if (self.day_start_balance - effective_equity) / self.day_start_balance >= config.DAILY_LOSS_LIMIT:
            print("CRITICAL: Daily Loss Limit. Stopping.")
            return False

        # TRUE Exposure Control
        risk_pct = self.calculate_total_risk()
        if risk_pct >= config.MAX_TOTAL_EXPOSURE:
            print(f"Exposure at limit ({risk_pct:.2%}). Skip.")
            return False

        if range_points < config.MIN_RANGE_POINTS:
            return False
            
        # Spread vs Progress: Hard friction filter (Institutional upgrade)
        tp_dist = range_points * 3 # Estimated TP distance based on straddle setup
        tick = self.connector.get_tick()
        if tick:
            spread_pts = (tick.ask - tick.bid) / self.connector.point
            friction_ratio = spread_pts / tp_dist if tp_dist > 0 else 1.0
            if friction_ratio > config.MAX_FRICTION_RATIO:
                print(f"FRICTION SHIELD: Spread ({spread_pts:.0f} pts) is too large for TP ({tp_dist:.0f} pts). Skip.")
                return False

        # Dead Market Filter: Range compression detection
        self.range_history.append(range_points)
        if len(self.range_history) > config.RANGE_SHRINK_CHECK_WINDOW:
            self.range_history.pop(0)

        # Breakout Quality: Volatility Expansion Check
        # Only enter if current range is significantly larger than the average of recent compressed ranges
        if len(self.range_history) == config.RANGE_SHRINK_CHECK_WINDOW:
            avg_range = sum(self.range_history) / len(self.range_history)
            # If current range is widening vs average → Potential breakout start
            # If current range is shrinking → Compression phase (wait for expansion)
            if all(self.range_history[i] < self.range_history[i-1] for i in range(1, len(self.range_history))):
                print("Market Compression Detected → Waiting for expansion.")
                return False
                
        # Spread & Rollover Guard
        tick = self.connector.get_tick()
        if tick:
            # Rollover hour filter
            hour = time.gmtime(tick.time).tm_hour
            if hour in [21, 22, 23]:
                return False

            spread_pts = (tick.ask - tick.bid) / self.connector.point
            self.update_spread_rolling(spread_pts)
            
            # Spread-to-Range Normalization
            spread_ratio = spread_pts / range_points
            if spread_ratio > config.MAX_SPREAD_RATIO:
                print(f"Spread logic: Ratio {spread_ratio:.2f} exceeds {config.MAX_SPREAD_RATIO}. Skip.")
                return False

            # Warm-up baseline check
            if len(self.spread_history) < 10:
                return False
            if spread_pts > self.avg_spread * 2 and spread_ratio > 0.1:
                print(f"Spread Spike Detected ({spread_pts:.0f} pts vs Avg: {self.avg_spread:.0f}).")
                return False

        # Adaptive Cooldown
        if self.cooldown_counter > 0:
            self.cooldown_counter -= 1
            return False

        # Expectancy & Variance Kill Switch
        count = self.stats["total_trades"]
        if count >= config.VALIDATION_WINDOW:
            exp = self.calculate_expectancy()
            # Confidence Weighting (Institutional upgrade)
            confidence = min(1.0, count / 100)
            adjusted_exp = exp * confidence
            
            std_r = self.calculate_std_r()
            
            # Instability Check
            if count >= 30 and std_r > 2.5:
                print(f"Unstable Performance (std_r: {std_r:.2f} > 2.5) → Halting.")
                self.system_halted = True
                self.save_state()
                return False

            if count < 100:
                if adjusted_exp < -0.2: self.system_halted = True
            else:
                if adjusted_exp <= 0: self.system_halted = True
        
        if self.system_halted: 
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
                "partial_closed": False
            }
            self.save_state()

        # Fake Breakout Logic (Buffered)
        r_dist_val = abs(self.active_trade['entry'] - self.active_trade['initial_sl'])
        if r_dist_val <= 0: return
        
        # Spread vs Progress: If spread is too large vs TP, reconsider
        tp_dist = abs(self.active_trade['tp'] - self.active_trade['entry'])
        spread_pts = (tick.ask - tick.bid) / self.connector.point
        if not self.active_trade['partial_closed'] and (spread_pts * self.connector.point) > (0.2 * tp_dist):
            print(f"Friction Warning: Spread is {spread_pts:.0f} pts while TP is nearby.")

        buffer = 0.2 * r_dist_val
        candles = self.connector.get_m1_candles(3)
        momentum_ratio = 0.0
        if candles is not None and len(candles) >= 3:
            avg_body = sum(abs(c['close'] - c['open']) for c in candles) / len(candles)
            momentum_ratio = avg_body / r_dist_val if r_dist_val > 0 else 0
            
            if self.current_range:
                last_closed = candles[-1]
                if self.active_trade['type'] == "BUY" and last_closed['close'] < (self.current_range['high'] - buffer):
                    print("Fake breakout (buffered) → closing.")
                    self.connector.close_position(pos.ticket, pos.type, pos.volume)
                    return
                elif self.active_trade['type'] == "SELL" and last_closed['close'] > (self.current_range['low'] + buffer):
                    print("Fake breakout (buffered) → closing.")
                    self.connector.close_position(pos.ticket, pos.type, pos.volume)
                    return

        if is_lagging: return # End of critical section

        # Continuous Trailing Logic
        profit_points = abs(live_price - self.active_trade['entry'])
        r_multiple = profit_points / r_dist_val

        # 3. Take Profit Management (Institutional Grade Trailing)
        if hasattr(config, 'TP_TRAILING_ENABLE') and config.TP_TRAILING_ENABLE and self.active_trade['partial_closed']:
            if r_multiple >= config.TP_TRAILING_START_R:
                # Maintain a buffer between live price and TP to 'ride' the expansion
                tp_buffer = 1.0 * r_dist_val # Maintain 1R breathing room
                
                new_tp = 0.0
                if self.active_trade['type'] == "BUY":
                    new_tp = live_price + tp_buffer
                else:
                    new_tp = live_price - tp_buffer
                
                # Check if movement is significant and moves TP further away
                is_farther = (new_tp > pos.tp) if self.active_trade['type'] == "BUY" else (new_tp < pos.tp or pos.tp == 0)
                move_dist = abs(new_tp - pos.tp) if pos.tp > 0 else 999
                
                if is_farther and move_dist >= (config.TP_TRAILING_STEP_R * r_dist_val):
                    self.add_log(f"TP TRAIL: Extending TP to {new_tp:.5f} (Momentum detected at {r_multiple:.2f}R)")
                    self.connector.modify_position(pos.ticket, pos.sl, new_tp)
                    # Update state to reflect new TP
                    self.active_trade['tp'] = new_tp
                    self.save_state()

        # Velocity-aware ladder thresholds
        if momentum_ratio > 0.3:
            l1_val, l2_val = 0.5, 1.2
        else:
            l1_val, l2_val = 0.3, 0.8

        if self.active_trade['partial_closed']:
            if r_multiple >= 1.5 and r_multiple < 2.0:
                new_sl = self.active_trade['entry'] + (l1_val * r_dist_val) if self.active_trade['type'] == "BUY" else self.active_trade['entry'] - (l1_val * r_dist_val)
                if (self.active_trade['type'] == "BUY" and new_sl > pos.sl) or (self.active_trade['type'] == "SELL" and (pos.sl == 0 or new_sl < pos.sl)):
                    print(f"Velocity Trailing ({momentum_ratio:.2f} momentum) → SL to +{l1_val}R")
                    res = self.connector.modify_position(pos.ticket, new_sl, pos.tp)
                    if not res: self.active_trade['failure_count'] = self.active_trade.get('failure_count', 0) + 1
            elif r_multiple >= 2.0:
                new_sl = self.active_trade['entry'] + (l2_val * r_dist_val) if self.active_trade['type'] == "BUY" else self.active_trade['entry'] - (l2_val * r_dist_val)
                if (self.active_trade['type'] == "BUY" and new_sl > pos.sl) or (self.active_trade['type'] == "SELL" and (pos.sl == 0 or new_sl < pos.sl)):
                    print(f"Velocity Trailing ({momentum_ratio:.2f} momentum) → SL to +{l2_val}R")
                    res = self.connector.modify_position(pos.ticket, new_sl, pos.tp)
                    if not res: self.active_trade['failure_count'] = self.active_trade.get('failure_count', 0) + 1

        # Partial Close
        if not self.active_trade['partial_closed'] and r_multiple >= 1.0:
            current_vol = self.connector.get_position_filled_volume(pos.ticket)
            if current_vol <= 0: current_vol = pos.volume # fallback
            
            half_vol = self.connector.round_volume(current_vol / 2)
            print(f"Partial Close ({half_vol}) at 1R.")
            res_close = self.connector.close_position(pos.ticket, pos.type, half_vol)
            res_mod = self.connector.modify_position(pos.ticket, self.active_trade['entry'], pos.tp)
            
            if res_close:
                self.active_trade['partial_closed'] = True
                if res_mod:
                    self.active_trade['breakeven_moved'] = True
                else:
                    self.active_trade['failure_count'] = self.active_trade.get('failure_count', 0) + 1
            else:
                 self.active_trade['failure_count'] = self.active_trade.get('failure_count', 0) + 1
                 
            self.save_state()
            
        # Stuck Position final check
        if self.active_trade.get('failure_count', 0) >= config.STUCK_POSITION_THRESHOLD:
            print(f"STUCK POSITION DETECTED (Failures: {self.active_trade['failure_count']}) → Flattening.")
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
        buy_p = range_high + (config.BUFFER_POINTS * self.connector.point)
        sell_p = range_low - (config.BUFFER_POINTS * self.connector.point)
        
        # Meta persistence with range recovery
        self.active_trade_meta = {
            "buy_entry": buy_p,
            "sell_entry": sell_p,
            "range_high": range_high,
            "range_low": range_low,
            "order_timestamp": time.time(),
            "expected_order_count": 2
        }
        self.save_state()

        lot = self.calculate_lot_size(buy_p, range_low)
        tick = self.connector.get_tick()
        spread_pts = (tick.ask - tick.bid) / self.connector.point
        dev = int(spread_pts) + 10
        
        print(f"--- SENSING BREAKOUT ---")
        print(f"Range: {range_low:.2f} - {range_high:.2f} ({r_pts:.0f} pts)")
        print(f"BUY STOP @ {buy_p:.2f} | SL: {range_low:.2f}")
        print(f"SELL STOP @ {sell_p:.2f} | SL: {range_high:.2f}")
        print(f"Spread: {spread_pts:.0f} | Risk: {self.risk_multiplier*100:.0f}% | LOT: {lot}")
        
        # Internal Execution Lock
        self.execution_lock = True
        self.save_state()
        
        self.connector.place_order(mt5.ORDER_TYPE_BUY_STOP, buy_p, range_low, buy_p + (buy_p-range_low)*3, lot, deviation=dev)
        self.connector.place_order(mt5.ORDER_TYPE_SELL_STOP, sell_p, range_high, sell_p - (range_high-sell_p)*3, lot, deviation=dev)
        self.add_log(f"EXEC: Pending straddle placed (Size: {lot})")

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
