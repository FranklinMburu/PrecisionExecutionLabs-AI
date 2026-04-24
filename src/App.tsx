import { useState, useEffect, useMemo } from 'react';
import { 
  Activity, 
  TrendingUp, 
  TrendingDown, 
  AlertTriangle, 
  ShieldCheck, 
  Settings, 
  RefreshCw,
  Terminal,
  Zap,
  Target,
  Lock,
  Unlock,
  Gauge,
  History,
  Info
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  AreaChart,
  Area,
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  ReferenceLine
} from 'recharts';
import { cn } from './lib/utils';

interface TradeRecord {
  r: number;
  pnl: number;
  time: number;
  symbol: string;
}

interface EngineStatus {
  engine: {
    symbol: string;
    connected: boolean;
    mock_mode: boolean;
    system_halted: boolean;
    shock_mode: boolean;
    shock_cooldown: number;
    oco_lock: boolean;
    execution_lock: boolean;
    risk_multiplier: number;
    latency: number;
  };
  market: {
    bid: number;
    ask: number;
    range: { high: number; low: number } | null;
    avg_candle_body: number;
    avg_spread: number;
  };
  account: {
    balance: number;
    equity: number;
    profit: number;
    total_risk_pct: number;
  };
  stats: {
    total_trades: number;
    wins: number;
    losses: number;
    total_r: number;
    win_r_sum: number;
    loss_r_sum: number;
  };
  performance: {
    expectancy: number;
    std_r: number;
    r_values: (number | TradeRecord)[];
    r_baseline: number;
  };
  active_trade: any | null;
  active_trade_meta: any;
  raw_orders: any[];
  logs: string[];
}

export default function App() {
  const [data, setData] = useState<EngineStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = async () => {
    try {
      const response = await fetch('/api/status');
      if (!response.ok) throw new Error('API Sync Failed');
      const status = await response.json();
      setData(status);
      setError(null);
    } catch (err) {
      setError('Connection to Core Engine lost. Reconnecting...');
    }
  };

  const handleReset = async () => {
    try {
      const response = await fetch('/api/reset', { method: 'POST' });
      if (response.ok) {
        fetchStatus();
      }
    } catch (err) {
      console.error("Reset failed", err);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 1000);
    return () => clearInterval(interval);
  }, []);

  const chartData = useMemo(() => {
    const values = data?.performance.r_values || [];
    const baseline = data?.performance.r_baseline || 0;
    let runningTotal = baseline;
    
    const mapped = values.map((val, i) => {
      const isRecord = typeof val === 'object';
      const r_val = isRecord ? val.r : val;
      const time = isRecord ? val.time : Date.now() - (values.length - i) * 60000;
      
      runningTotal += r_val;
      
      return {
        time: new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(time)),
        sortTime: time,
        r: r_val,
        value: runningTotal, // This is the cumulative R
        pair: isRecord ? val.symbol : 'XAUUSD'
      };
    });

    if (mapped.length > 0) {
      const firstTime = mapped[0].sortTime;
      const startTime = firstTime - 60000;
      mapped.unshift({
        time: new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(startTime)),
        sortTime: startTime,
        r: 0,
        value: baseline,
        pair: 'START'
      });
    }

    return mapped;
  }, [data?.performance.r_values, data?.performance.r_baseline]);

  if (!data && !error) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <RefreshCw className="w-8 h-8 text-blue-500" />
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#020617] text-[#94a3b8] font-sans selection:bg-blue-500/30 overflow-x-hidden">
      {/* Top Telemetry Bar */}
      <div className="h-1 bg-slate-900 overflow-hidden">
        {data?.engine.connected && (
          <motion.div 
            className="h-full bg-blue-500"
            animate={{ x: [-100, 1000] }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          />
        )}
      </div>

      <header className="border-b border-white/5 bg-slate-900/20 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-[1600px] mx-auto px-6 h-20 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="relative">
              <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center">
                <Zap className="w-7 h-7 text-white fill-white/20" />
              </div>
              {data?.engine.mock_mode && (
                <div className="absolute -top-1 -right-1 w-4 h-4 bg-amber-500 border-2 border-[#020617] rounded-full" />
              )}
            </div>
            <div>
              <h1 className="text-xl font-black text-white tracking-tighter uppercase italic">PRECISION<span className="text-blue-500">EXECUTION</span>LAB AI</h1>
              <div className="flex items-center gap-2">
                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Powered by AI Trading Systems</p>
                <span className="text-[10px] text-slate-700">|</span>
                <p className="text-[10px] font-bold text-blue-500/80 uppercase tracking-widest">{data?.engine.symbol}</p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1.5 font-mono">
             <EngineTag label="OCO" active={data?.engine.oco_lock} color="rose" />
             <EngineTag label="EXEC" active={data?.engine.execution_lock} color="amber" />
             <EngineTag label="SHOCK" active={data?.engine.shock_mode} color="purple" />
             <div className="w-px h-8 bg-white/5 mx-2" />
             <div className="flex items-center gap-3">
               {(data?.engine.latency || 0) > 0.5 && (
                 <motion.div 
                   animate={{ scale: [1, 1.2, 1], opacity: [0.5, 1, 0.5] }}
                   transition={{ duration: 1, repeat: Infinity }}
                   className="text-rose-500"
                 >
                   <AlertTriangle className="w-5 h-5 fill-rose-500/20" />
                 </motion.div>
               )}
               <div className="text-right">
                 <p className="text-[10px] uppercase font-bold text-slate-500 tracking-tighter leading-none">Latency</p>
                 <p className={cn(
                   "text-sm font-black transition-colors duration-300",
                   (data?.engine.latency || 0) > 0.5 ? "text-rose-500 drop-shadow-[0_0_8px_rgba(244,63,94,0.4)]" : "text-emerald-500"
                 )}>
                   {(data?.engine.latency || 0).toFixed(3)}s
                 </p>
               </div>
             </div>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto px-6 py-10">
        <AnimatePresence>
          {error && (
            <motion.div 
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="bg-rose-500/10 border border-rose-500/20 px-6 py-4 rounded-2xl flex items-center gap-4 text-rose-400 mb-8"
            >
              <AlertTriangle className="w-6 h-6 animate-pulse" />
              <p className="font-bold uppercase tracking-widest text-xs">{error}</p>
            </motion.div>
          )}
          {data?.engine.system_halted && (
            <motion.div 
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="bg-rose-500 border border-rose-600 px-6 py-4 rounded-2xl flex items-center justify-between text-white mb-8 shadow-lg shadow-rose-500/20"
            >
              <div className="flex items-center gap-4">
                <AlertTriangle className="w-6 h-6" />
                <div>
                  <p className="font-black uppercase tracking-tight text-sm">System Halted: Max Drawdown Triggered</p>
                  <p className="text-[10px] font-bold opacity-80 uppercase tracking-widest">Trading logic is currently disabled due to risk breach.</p>
                </div>
              </div>
              <button 
                onClick={handleReset}
                className="bg-white text-rose-600 px-6 py-2 rounded-xl font-black text-xs uppercase tracking-widest hover:scale-105 transition-transform active:scale-95 shadow-xl"
              >
                Reset & Resume
              </button>
            </motion.div>
          )}
          {(data?.engine.latency || 0) > 0.5 && (
            <motion.div 
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="bg-amber-500 border border-amber-600 px-6 py-3 rounded-2xl flex items-center gap-4 text-amber-950 mb-8 shadow-lg shadow-amber-500/10"
            >
              <Activity className="w-5 h-5 animate-pulse" />
              <div>
                <p className="font-black uppercase tracking-tight text-xs">High Execution Latency Detected ({(data?.engine.latency || 0).toFixed(3)}s)</p>
                <p className="text-[9px] font-bold opacity-80 uppercase tracking-widest">Orders may experience significant slippage or rejection.</p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="grid grid-cols-12 gap-8">
          {/* Key Stats Row */}
          <div className="col-span-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6">
            <MetricBox 
              label="Equity" 
              value={`$${data?.account.equity.toLocaleString()}`} 
              icon={<TrendingUp className="w-4 h-4" />} 
              sub={`Profit: $${data?.account.profit.toFixed(2)}`}
              color="blue"
            />
            <MetricBox 
              label="Active Risk" 
              value={`${data?.account.total_risk_pct.toFixed(2)}%`} 
              icon={<ShieldCheck className="w-4 h-4" />} 
              sub={`Limit: ${(0.05 * 100).toFixed(0)}%`}
              color={ (data?.account.total_risk_pct || 0) > 4 ? "rose" : "emerald" }
              alert={ (data?.account.total_risk_pct || 0) > 4.5 }
            />
            <MetricBox 
              label="Win Rate" 
              value={`${((data?.stats.wins || 0) / (data?.stats.total_trades || 1) * 100).toFixed(1)}%`} 
              icon={<Target className="w-4 h-4" />} 
              sub={`Trades: ${data?.stats.total_trades}`}
              color="purple"
            />
            <MetricBox 
              label="Expectancy" 
              value={`${data?.performance.expectancy.toFixed(2)}R`} 
              icon={<Gauge className="w-4 h-4" />} 
              sub={`Std Dev: ${data?.performance.std_r.toFixed(2)}`}
              color={ (data?.performance.expectancy || 0) > 0 ? "emerald" : "rose" }
            />
            <MetricBox 
              label="Latency" 
              value={`${(data?.engine.latency || 0).toFixed(3)}s`} 
              icon={<Zap className="w-4 h-4" />} 
              sub={ (data?.engine.latency || 0) > 0.5 ? "CRITICAL LAG" : "OPTIMIZED" }
              color={ (data?.engine.latency || 0) > 0.5 ? "rose" : "blue" }
              alert={ (data?.engine.latency || 0) > 0.5 }
            />
          </div>

          {/* Market Visualizer */}
          <div className="col-span-12 lg:col-span-8 space-y-8">
            <div className="bg-slate-900/40 border border-white/5 rounded-3xl p-8 relative overflow-hidden backdrop-blur-sm">
              <div className="flex justify-between items-start mb-12">
                <div>
                  <h3 className="text-white text-3xl font-black tracking-tighter mb-1 uppercase italic">Range Dynamics</h3>
                  <p className="text-xs text-slate-500 font-bold tracking-widest uppercase">M1 Lookback: 6-Cycle</p>
                </div>
                <div className="flex gap-4">
                   <div className="text-right">
                     <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Risk Factor</p>
                     <p className="text-xl font-mono text-white font-black">x{data?.engine.risk_multiplier.toFixed(1)}</p>
                   </div>
                </div>
              </div>

              {/* Range Dial */}
              <div className="relative h-64 flex items-center justify-center">
                 <div className="absolute inset-0 flex flex-col justify-between items-center py-4">
                    <RangeIndicator label="UPPER BOUND" value={data?.market.range?.high} color="emerald" />
                    <div className="w-full h-px bg-white/5 relative">
                       <motion.div 
                        className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-600 px-4 py-1 rounded-full text-white font-black text-lg border-2 border-white"
                        animate={{ scale: [1, 1.05, 1] }}
                        transition={{ duration: 1, repeat: Infinity }}
                       >
                         {data?.market.bid.toFixed(5)}
                       </motion.div>
                    </div>
                    <RangeIndicator label="LOWER BOUND" value={data?.market.range?.low} color="rose" />
                 </div>
              </div>

              <div className="grid grid-cols-2 gap-8 mt-12 border-t border-white/5 pt-8">
                 <div className="space-y-1">
                    <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Avg Candle Body</p>
                    <p className="text-lg font-black text-white">{data?.market.avg_candle_body.toFixed(5)}</p>
                 </div>
                 <div className="space-y-1 text-right">
                    <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Rolling Spread Avg</p>
                    <p className="text-lg font-black text-white">{data?.market.avg_spread.toFixed(1)} pts</p>
                 </div>
              </div>
            </div>

            {/* Performance Chart */}
            <div className="bg-slate-900/40 border border-white/5 rounded-3xl p-8 backdrop-blur-sm">
              <div className="flex items-center justify-between mb-8">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-emerald-500/10 rounded-lg text-emerald-500">
                    <History className="w-5 h-5" />
                  </div>
                  <h3 className="text-white font-black tracking-tight text-lg uppercase">Equity Progression (R)</h3>
                </div>
                <div className="flex items-center gap-2">
                   <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                   <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Real-time Attribution</span>
                </div>
              </div>
              <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#ffffff05" vertical={false} />
                    <XAxis 
                      dataKey="time" 
                      stroke="#475569" 
                      fontSize={10} 
                      tickLine={false} 
                      axisLine={false}
                      minTickGap={20}
                    />
                    <YAxis 
                      stroke="#475569" 
                      fontSize={10} 
                      tickFormatter={(v) => `${v}R`} 
                      tickLine={false} 
                      axisLine={false} 
                    />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #ffffff10', borderRadius: '12px' }}
                      itemStyle={{ color: '#10b981', fontWeight: 'bold' }}
                      formatter={(value: number) => [`${value.toFixed(2)}R`, 'Cumulative Performance']}
                    />
                    <Area 
                      type="monotone" 
                      dataKey="value" 
                      stroke="#10b981" 
                      strokeWidth={3} 
                      fillOpacity={1} 
                      fill="url(#equityGradient)" 
                      animationDuration={1500}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Right Sidebar - Active Context */}
          <div className="col-span-12 lg:col-span-4 space-y-8">
            <SideSection title="Current Position" icon={<Activity className="w-4 h-4" />}>
               <AnimatePresence mode="wait">
                 {data?.active_trade ? (
                   <motion.div 
                     initial={{ opacity: 0, x: 20 }}
                     animate={{ opacity: 1, x: 0 }}
                     exit={{ opacity: 0, x: -20 }}
                     className="space-y-6"
                   >
                     <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                           <div className={cn(
                             "px-3 py-1 rounded-md text-[10px] font-black uppercase tracking-widest text-white shadow-xl",
                             data.active_trade.type === 'BUY' ? "bg-emerald-600" : "bg-rose-600"
                           )}>
                             {data.active_trade.type}
                           </div>
                           <p className="text-xs font-mono text-slate-400">#{data.active_trade.ticket}</p>
                        </div>
                        <div className="text-right">
                          {data.active_trade.partial_closed && <span className="text-[10px] text-blue-500 font-bold uppercase tracking-widest bg-blue-500/10 px-2 py-0.5 rounded-full">Partialled</span>}
                        </div>
                     </div>

                     <div className="grid grid-cols-2 gap-4">
                        <TradeCoord label="Entry" val={data.active_trade.entry.toFixed(5)} />
                        <TradeCoord label="Current SL" val={data.active_trade.initial_sl.toFixed(5)} highlight />
                     </div>

                     <div className="p-4 bg-slate-950 border border-white/5 rounded-2xl flex items-center justify-between">
                        <div>
                          <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest mb-1">Unrealized R</p>
                          <p className="text-xl font-black text-white">
                            {((data.market.bid - data.active_trade.entry) / Math.abs(data.active_trade.entry - data.active_trade.initial_sl)).toFixed(2)}R
                          </p>
                        </div>
                        <div className="w-12 h-12 rounded-full border-4 border-blue-500/20 border-t-blue-500 animate-spin" />
                     </div>
                   </motion.div>
                 ) : (
                   <motion.div 
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="h-40 flex flex-col items-center justify-center text-slate-600 border-2 border-dashed border-white/5 rounded-2xl"
                   >
                     <Target className="w-10 h-10 mb-2 opacity-20" />
                     <p className="text-[10px] font-bold uppercase tracking-[0.2em] opacity-40">Scanning for Breakout</p>
                   </motion.div>
                 )}
               </AnimatePresence>
            </SideSection>

            <SideSection title="Pending Book" icon={<Lock className="w-4 h-4" />}>
               {data?.raw_orders.length === 0 ? (
                 <p className="text-[10px] text-slate-600 font-bold text-center py-4 uppercase">Wait-state clear</p>
               ) : (
                 <div className="space-y-4">
                    {data?.raw_orders.map(order => (
                      <div key={order.ticket} className="flex justify-between items-center p-3 bg-slate-950/50 rounded-xl border border-white/5">
                         <div className="flex gap-3">
                            <div className={cn("w-1 h-8 rounded-full", order.type === 4 ? "bg-emerald-500" : "bg-rose-500")} />
                            <div>
                               <p className="text-[10px] font-black uppercase tracking-tighter text-white">
                                {order.type === 4 ? 'BUY STOP' : 'SELL STOP'} @ {order.price_open.toFixed(5)}
                               </p>
                               <p className="text-[10px] text-slate-500 font-mono">Lot: {order.volume}</p>
                            </div>
                         </div>
                         <Lock className="w-3 h-3 text-slate-700" />
                      </div>
                    ))}
                 </div>
               )}
            </SideSection>

            <SideSection title="Terminal Logs" icon={<Terminal className="w-4 h-4" />}>
              <div className="h-48 overflow-y-auto font-mono text-[9px] text-slate-500 space-y-1 custom-scrollbar">
                 {data?.logs.map((log: string, i: number) => (
                   <p key={i} className={cn(
                     "transition-colors",
                     log.includes('CRITICAL') ? "text-rose-500 font-bold" : 
                     log.includes('SHOCK') ? "text-purple-400" : 
                     log.includes('EXEC') ? "text-emerald-400" : ""
                   )}>
                     {log}
                   </p>
                 ))}
                 {(!data?.logs || data.logs.length === 0) && <p className="opacity-20 uppercase tracking-widest text-[8px]">Waiting for engine lifecycle...</p>}
              </div>
            </SideSection>
          </div>
        </div>
      </main>

      {/* Emergency Status Footer */}
      <footer className="fixed bottom-0 left-0 right-0 h-10 bg-slate-950 border-t border-white/5 z-50 flex items-center px-6">
        <div className="flex gap-6 items-center w-full">
            <StatusDot label="SYSTEM_READY" active={!data?.engine.system_halted} />
            <StatusDot label="API_SYNC" active={!!data} />
            <StatusDot label="BUFFER_CLEAR" active={!data?.engine.execution_lock} />
            <div className="flex-1" />
            <p className="text-[10px] font-bold text-slate-700 uppercase tracking-[0.3em]">
              Precision Trading Core <span className="text-white/20">|</span> v1.0.0-PROD
            </p>
        </div>
      </footer>
    </div>
  );
}

function MetricBox({ label, value, icon, sub, color, alert }: any) {
  const colors: any = {
    blue: "text-blue-500 bg-blue-500/10 border-blue-500/20",
    emerald: "text-emerald-500 bg-emerald-500/10 border-emerald-500/20",
    rose: "text-rose-500 bg-rose-500/10 border-rose-500/20",
    purple: "text-purple-500 bg-purple-500/10 border-purple-500/20",
    amber: "text-amber-500 bg-amber-500/10 border-amber-500/20"
  };

  return (
    <div className={cn(
      "bg-slate-900/60 border border-white/5 p-6 rounded-3xl backdrop-blur-xl relative overflow-hidden transition-all duration-500",
      alert && "ring-1 ring-rose-500/50 bg-rose-500/5"
    )}>
      {alert && (
        <motion.div 
          className="absolute inset-0 bg-rose-500/5 pointer-events-none"
          animate={{ opacity: [0, 1, 0] }}
          transition={{ duration: 2, repeat: Infinity }}
        />
      )}
      <div className="flex items-center justify-between mb-4">
        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">{label}</p>
        <div className={cn("p-2 rounded-xl border transition-all duration-500", colors[color], alert && "scale-110 shadow-[0_0_15px_rgba(244,63,94,0.3)]")}>
          {alert ? <AlertTriangle className="w-4 h-4 animate-pulse" /> : icon}
        </div>
      </div>
      <div>
        <h4 className="text-2xl font-black text-white tracking-widest">{value}</h4>
        <p className="text-[10px] font-bold text-slate-500 mt-1 uppercase tracking-wider">{sub}</p>
      </div>
    </div>
  );
}

function EngineTag({ label, active, color }: any) {
  const variants: any = {
    rose: active ? "bg-rose-500/20 text-rose-500 border-rose-500/30" : "bg-white/5 text-slate-600 border-white/5",
    amber: active ? "bg-amber-500/20 text-amber-500 border-amber-500/30" : "bg-white/5 text-slate-600 border-white/5",
    purple: active ? "bg-purple-500/20 text-purple-500 border-purple-500/30" : "bg-white/5 text-slate-600 border-white/5",
    emerald: active ? "bg-emerald-500/20 text-emerald-500 border-emerald-500/30" : "bg-white/5 text-slate-600 border-white/5"
  };

  return (
    <div className={cn(
      "px-3 py-1.5 rounded-lg border text-[10px] font-black uppercase tracking-widest flex items-center gap-2 transition-all duration-500",
      variants[color]
    )}>
      {active ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />}
      {label}
    </div>
  );
}

function RangeIndicator({ label, value, color }: any) {
  return (
    <div className="flex flex-col items-center gap-2 group">
       <span className={cn(
         "text-[10px] font-black uppercase tracking-[0.3em] transition-opacity",
         color === 'emerald' ? "text-emerald-500" : "text-rose-500"
       )}>
         {label}
       </span>
       <div className={cn(
         "px-8 py-3 rounded-2xl border-2 font-black text-2xl tracking-widest font-mono group-hover:scale-110 transition-transform",
         color === 'emerald' ? "bg-emerald-500/5 border-emerald-500/20 text-emerald-500" : "bg-rose-500/5 border-rose-500/20 text-rose-500"
       )}>
         {value?.toFixed(5) || '-----.-----'}
       </div>
    </div>
  );
}

function SideSection({ title, icon, children }: any) {
  return (
    <div className="bg-slate-900/40 border border-white/5 rounded-3xl p-6 backdrop-blur-sm">
      <div className="flex items-center gap-3 mb-6">
        <div className="text-slate-500">{icon}</div>
        <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-white/40">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function TradeCoord({ label, val, highlight }: any) {
  return (
    <div className="space-y-1">
      <p className="text-[10px] font-bold text-slate-600 uppercase tracking-widest">{label}</p>
      <p className={cn("text-sm font-mono font-black", highlight ? "text-rose-400" : "text-white")}>{val}</p>
    </div>
  );
}

function StatusDot({ label, active }: any) {
  return (
    <div className="flex items-center gap-2">
      <div className={cn("w-1.5 h-1.5 rounded-full", active ? "bg-emerald-500 animate-pulse" : "bg-rose-500")} />
      <span className="text-[9px] font-black uppercase tracking-widest text-slate-600">{label}</span>
    </div>
  );
}
