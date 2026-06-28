import React from 'react';
import { OverviewHeader } from '../overview/OverviewHeader';
import {
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    Scatter, ComposedChart, Cell, Area, PieChart, Pie, BarChart, Bar, Legend
} from 'recharts';
import { 
    Brain, ShieldCheck, Zap, Activity, TrendingUp, 
    Sparkles, Gauge, Cpu, Layers, Crosshair
} from 'lucide-react';

export const AnalyticsSection = () => {
    // Mock Data
    const performanceData = [
        { time: '09:00', price: 41000, conf: 45, action: null, regime: 'Sideways' },
        { time: '10:00', price: 40850, conf: 85, action: 'BUY', regime: 'Trend Up' },
        { time: '11:00', price: 41000, conf: 60, action: null, regime: 'Trend Up' },
        { time: '13:00', price: 41450, conf: 92, action: 'SELL', regime: 'Trend Up' },
        { time: '15:00', price: 41200, conf: 50, action: null, regime: 'Sideways' },
    ];

    const agentBias = [
        { name: 'Bullish', value: 70, color: '#10b981' },
        { name: 'Neutral', value: 20, color: '#9ca3af' },
        { name: 'Bearish', value: 10, color: '#f43f5e' },
    ];

    const confidenceAccuracy = [
        { range: '> 90%', won: 45, lost: 2 },
        { range: '75-90%', won: 52, lost: 18 },
        { range: '50-75%', won: 22, lost: 20 },
    ];

    return (
        <section className="w-full min-h-screen pb-16 bg-[#fcfcfd] relative overflow-hidden font-sans">
            <OverviewHeader />

            <div className="px-6 mt-8 max-w-[1300px] mx-auto relative z-20">
                
                {/* ✨ 1. Page Header (Compact & Crisp) */}
                <div className="flex flex-col md:flex-row md:items-end justify-between mb-8 gap-4">
                    <div>
                        <div className="flex items-center gap-2 mb-1.5">
                            <Sparkles className="w-3.5 h-3.5 text-[#824199]" />
                            <p className="text-[10px] font-bold text-[#824199] uppercase tracking-[0.3em]">Neural Engine v3.8</p>
                        </div>
                        <h1 className="text-3xl md:text-4xl font-black text-gray-900 tracking-tight leading-none">
                            Market <span className="bg-clip-text text-transparent bg-gradient-to-r from-[#824199] to-[#c084fc]">Intelligence</span>
                        </h1>
                    </div>
                    <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-xl border border-gray-100 shadow-sm">
                        <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
                        <span className="text-[10px] font-bold text-gray-600 uppercase tracking-widest">System Optimal</span>
                    </div>
                </div>

                {/* ✨ 2. Top Metrics (Leaner Cards) */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                    <MetricCard title="Win Efficiency" icon={<ShieldCheck/>} value="84.2%" trend="+2.4%" color="emerald" />
                    <MetricCard title="Volatility Pulse" icon={<Gauge/>} value="LOW" trend="Safe" color="purple" />
                    <MetricCard title="Agent Latency" icon={<Cpu/>} value="1.2s" trend="Optimal" color="blue" />
                    <MetricCard title="Total Tokens" icon={<Layers/>} value="1.45M" trend="Processed" color="gray" />
                </div>

                {/* ✨ 3. Core Intelligence (70/30 Split - Less Padding, Sleeker Borders) */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
                    
                    {/* ✨ ส่วนกราฟที่ปรับปรุงให้อ่านง่ายสำหรับ User ทั่วไป */}
                    <div className="lg:col-span-8 bg-white p-6 md:p-8 rounded-[24px] border border-gray-100 shadow-[0_4px_20px_rgba(0,0,0,0.02)] relative overflow-hidden">
                        
                        {/* Header ของกราฟที่อธิบายชัดเจน */}
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-8 relative z-10 gap-4">
                            <div>
                                <h3 className="text-base font-black text-gray-900 tracking-tight flex items-center gap-2">
                                   <div className="w-2 h-5 bg-amber-400 rounded-full" /> 
                                   Gold Price & AI Decisions
                                </h3>
                                <p className="text-[11px] text-gray-500 font-medium mt-1">
                                    Timeline showing how the AI reacted to gold price movements.
                                </p>
                            </div>
                            
                            {/* คำอธิบายสัญลักษณ์ (Legend) ที่ดูง่าย */}
                            <div className="flex items-center gap-3 bg-gray-50 px-4 py-2 rounded-xl border border-gray-100">
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-600 uppercase">
                                    <div className="w-2.5 h-2.5 rounded-full bg-amber-400" /> Gold Price
                                </div>
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-600 uppercase">
                                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" /> AI Bought
                                </div>
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-600 uppercase">
                                    <div className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.5)]" /> AI Sold
                                </div>
                            </div>
                        </div>

                        {/* พื้นที่กราฟ */}
                        <div className="h-[300px] w-full relative z-10 pr-4">
                            <ResponsiveContainer width="100%" height="100%">
                                <ComposedChart data={performanceData} margin={{ top: 10, right: 0, bottom: 0, left: 0 }}>
                                    <defs>
                                        <linearGradient id="colorGold" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="#fbbf24" stopOpacity={0.2}/>
                                            <stop offset="95%" stopColor="#fbbf24" stopOpacity={0}/>
                                        </linearGradient>
                                    </defs>
                                    {/* เส้นตารางแนวนอน ช่วยให้กะระดับราคาได้ */}
                                    <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#f1f5f9" />
                                    
                                    <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{fontSize: 10, fill: '#94a3b8', fontWeight: 600}} dy={15} />
                                    
                                    {/* เปิดแกน Y ให้แสดงราคา เพื่อให้ User รู้สเกล */}
                                    <YAxis 
                                        domain={['dataMin - 100', 'dataMax + 100']} 
                                        axisLine={false} 
                                        tickLine={false} 
                                        tick={{fontSize: 10, fill: '#94a3b8', fontWeight: 600}} 
                                        tickFormatter={(val) => `${val.toLocaleString()}`} 
                                        width={50}
                                    />
                                    
                                    <Tooltip content={<FriendlyTooltip />} cursor={{ stroke: '#cbd5e1', strokeWidth: 1, strokeDasharray: '4 4' }} />
                                    
                                    {/* เปลี่ยนสีเส้นเป็นสีทอง/เหลือง ให้สื่อถึงทองคำ */}
                                    <Area type="monotone" dataKey="price" stroke="#fbbf24" strokeWidth={3} fill="url(#colorGold)" activeDot={{ r: 6, fill: '#fbbf24', stroke: '#fff', strokeWidth: 2 }} />
                                    
                                    <Scatter dataKey="price">
                                        {performanceData.map((entry, index) => (
                                            <Cell 
                                                key={index} 
                                                fill={entry.action === 'BUY' ? '#10b981' : entry.action === 'SELL' ? '#f43f5e' : 'transparent'} 
                                                r={entry.action ? 7 : 0} 
                                                stroke="#fff" 
                                                strokeWidth={2.5} 
                                            />
                                        ))}
                                    </Scatter>
                                </ComposedChart>
                            </ResponsiveContainer>
                        </div>
                    </div>

                    {/* Intent Donut */}
                    <div className="lg:col-span-4 bg-[#1a0a24] p-6 rounded-[20px] text-white flex flex-col justify-between shadow-xl relative overflow-hidden">
                         <div className="absolute top-0 right-0 w-32 h-32 bg-[#824199]/20 blur-3xl rounded-full" />
                         
                         <h3 className="text-[11px] font-bold text-purple-300 uppercase tracking-[0.2em] mb-4 text-center relative z-10">Neural Intent Bias</h3>
                         
                         <div className="h-44 w-full relative z-10 flex items-center justify-center">
                            <ResponsiveContainer width="100%" height="100%">
                                <PieChart>
                                    <Pie data={agentBias} cx="50%" cy="50%" innerRadius={55} outerRadius={75} paddingAngle={4} dataKey="value" cornerRadius={6}>
                                        {agentBias.map((entry, index) => <Cell key={index} fill={entry.color} stroke="none" />)}
                                    </Pie>
                                </PieChart>
                            </ResponsiveContainer>
                            <div className="absolute text-center mt-1">
                                <p className="text-3xl font-black leading-none">70<span className="text-sm opacity-50">%</span></p>
                                <p className="text-[9px] text-emerald-400 font-bold uppercase mt-0.5">Bullish</p>
                            </div>
                         </div>

                         <div className="grid grid-cols-3 gap-2 mt-4 relative z-10">
                            {agentBias.map(item => (
                                <div key={item.name} className="bg-white/5 p-2.5 rounded-xl border border-white/5 text-center">
                                    <p className="text-[8px] font-bold text-gray-400 uppercase mb-0.5">{item.name}</p>
                                    <p className="text-xs font-black text-white">{item.value}%</p>
                                </div>
                            ))}
                         </div>
                    </div>
                </div>

                {/* ✨ 4. Deep Analytics Grid (50/50) */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                    
                    {/* Accuracy Calibration */}
                    <div className="bg-white p-6 rounded-[20px] border border-gray-100 shadow-sm flex flex-col">
                        <div className="flex items-center justify-between mb-4">
                            <div>
                                <h4 className="text-[11px] font-black text-gray-900 uppercase tracking-widest flex items-center gap-2">
                                    <Crosshair size={14} className="text-[#824199]"/> Accuracy Calibration
                                </h4>
                                <p className="text-[10px] text-gray-400 mt-1">Win ratio by agent confidence levels</p>
                            </div>
                        </div>
                        <div className="flex-1 min-h-[160px]">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={confidenceAccuracy} layout="vertical" margin={{ left: -25, top: 10, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                                    <XAxis type="number" hide />
                                    <YAxis dataKey="range" type="category" axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: '#64748b', fontWeight: 'bold' }} width={80} />
                                    <Tooltip cursor={{fill: 'transparent'}} content={<AccuracyTooltip/>} />
                                    <Bar dataKey="won" stackId="a" fill="#10b981" radius={[0, 0, 0, 4]} barSize={16} />
                                    <Bar dataKey="lost" stackId="a" fill="#f43f5e" radius={[0, 4, 4, 0]} barSize={16} />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    </div>

                    {/* Risk & Reward Profile */}
                    <div className="grid grid-cols-2 gap-4">
                        <StatBox title="Avg. Winning" value="+3,450 ฿" desc="Per success" color="emerald" />
                        <StatBox title="Max Drawdown" value="-4.2%" desc="Portfolio dip" color="rose" />
                        <StatBox title="Exp. Yield" value="1.85" desc="Profit Factor" color="purple" />
                        <StatBox title="Data Quality" value="HIGH" desc="99.9% uptime" color="blue" />
                    </div>
                </div>

                {/* ✨ 5. Live Logs Feed (Compact Row) */}
                <div className="bg-white p-6 rounded-[20px] border border-gray-100 shadow-sm">
                    <div className="flex items-center justify-between mb-4">
                        <h4 className="text-[11px] font-black text-gray-800 uppercase tracking-widest flex items-center gap-2">
                            <Activity size={14} className="text-[#824199]" /> Intelligence Logs
                        </h4>
                        <button className="text-[9px] font-bold text-gray-400 hover:text-gray-900 transition-colors uppercase">View All</button>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {[
                            { type: 'THOUGHT', text: 'RSI oversold. Validating liquidity.', time: 'Just Now', icon: <Brain size={12}/> },
                            { type: 'ACTION', text: 'Fetched Indicator Data.', time: '2m ago', icon: <Cpu size={12}/> },
                            { type: 'DECISION', text: 'BUY order at 41,200 THB.', time: '5m ago', icon: <Zap size={12}/> },
                        ].map((log, i) => (
                            <div key={i} className="bg-gray-50/80 p-4 rounded-[16px] border border-gray-100">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="flex items-center gap-1.5 text-[9px] font-black text-gray-500 uppercase">
                                        {log.icon} {log.type}
                                    </span>
                                    <span className="text-[8px] text-gray-400 font-bold uppercase">{log.time}</span>
                                </div>
                                <p className="text-[11px] text-gray-600 font-medium leading-relaxed">"{log.text}"</p>
                            </div>
                        ))}
                    </div>
                </div>

            </div>
        </section>
    );
};

// --- ✨ Compact UI Atoms ---

const MetricCard = ({ title, icon, value, trend, color }: any) => {
    const colors: any = {
        emerald: "text-emerald-600 bg-emerald-50 border-emerald-100",
        purple: "text-[#824199] bg-purple-50 border-purple-100",
        blue: "text-blue-600 bg-blue-50 border-blue-100",
        gray: "text-gray-600 bg-gray-50 border-gray-100"
    };
    return (
        <div className="bg-white p-5 rounded-[20px] border border-gray-100 shadow-sm flex flex-col justify-between hover:shadow-md transition-all group">
            <div className="flex items-center justify-between mb-3">
                <div className={`w-8 h-8 rounded-xl flex items-center justify-center transition-transform group-hover:scale-105 ${colors[color]}`}>
                    {React.cloneElement(icon, { size: 16 })}
                </div>
                <span className={`text-[9px] font-black uppercase tracking-wider ${colors[color].split(' ')[0]}`}>{trend}</span>
            </div>
            <div>
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">{title}</p>
                <p className="text-2xl font-black text-gray-900 tracking-tight leading-none">{value}</p>
            </div>
        </div>
    );
};

const StatBox = ({ title, value, desc, color }: any) => {
    const colors: any = {
        emerald: "text-emerald-600 bg-emerald-50 border-emerald-100/50",
        rose: "text-rose-600 bg-rose-50 border-rose-100/50",
        purple: "text-[#824199] bg-purple-50 border-purple-100/50",
        blue: "text-blue-600 bg-blue-50 border-blue-100/50"
    };
    return (
        <div className={`${colors[color]} p-4 rounded-[20px] border flex flex-col justify-center`}>
            <p className="text-[9px] font-black text-gray-500 uppercase tracking-widest mb-1.5">{title}</p>
            <p className="text-xl font-black tracking-tight leading-none mb-1">{value}</p>
            <p className="text-[9px] opacity-60 font-medium">{desc}</p>
        </div>
    );
};

import { TrendingDown } from 'lucide-react'; // นำเข้า TrendingDown เพิ่มเติมด้านบนไฟล์ด้วยนะครับ

// --- ✨ Friendly Tooltip (เล่าเรื่องให้เข้าใจง่าย) ---
const FriendlyTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
        const data = payload[0].payload;
        return (
            <div className="bg-white p-4 rounded-2xl border border-gray-100 shadow-xl max-w-[220px]">
                <div className="flex items-center gap-2 mb-3 pb-2 border-b border-gray-50">
                    <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest bg-gray-50 px-2 py-1 rounded-md">{data.time}</span>
                </div>
                
                <p className="text-xs text-gray-500 font-medium mb-1">Market Gold Price:</p>
                <p className="text-xl font-black text-gray-900 leading-none mb-3">{data.price.toLocaleString()} <span className="text-sm text-gray-400">THB</span></p>
                
                {data.action ? (
                    <div className={`mt-2 p-2.5 rounded-xl text-[11px] font-bold flex flex-col gap-1.5 ${data.action === 'BUY' ? 'bg-emerald-50 text-emerald-700 border border-emerald-100' : 'bg-rose-50 text-rose-700 border border-rose-100'}`}>
                        <div className="flex items-center gap-1.5 uppercase tracking-widest">
                            {data.action === 'BUY' ? <TrendingUp size={14}/> : <TrendingDown size={14}/>}
                            AI Executed {data.action}
                        </div>
                        <span className="text-[9px] opacity-70 font-medium normal-case">
                            {data.action === 'BUY' ? 'Agent found a good entry point.' : 'Agent secured profit / cut loss.'}
                        </span>
                    </div>
                ) : (
                    <div className="mt-2 p-2 rounded-xl bg-gray-50 border border-gray-100 text-[10px] text-gray-400 font-medium italic flex items-center gap-2">
                        <Activity size={12} /> AI was observing...
                    </div>
                )}
            </div>
        );
    }
    return null;
};

const AccuracyTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
        const won = payload[0].value;
        const lost = payload[1].value;
        const total = won + lost;
        const wr = Math.round((won / total) * 100);
        return (
            <div className="bg-gray-900 p-2.5 rounded-lg shadow-xl text-white">
                <p className="text-[9px] font-bold text-gray-400 mb-1 uppercase">Conf: {payload[0].payload.range}</p>
                <p className="text-xs font-black text-emerald-400 mb-0.5">Win Rate: {wr}%</p>
                <p className="text-[10px] text-gray-300">{won} Won / {lost} Lost</p>
            </div>
        );
    }
    return null;
};