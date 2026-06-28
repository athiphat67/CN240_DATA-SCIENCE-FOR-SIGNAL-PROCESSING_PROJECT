import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Brain, Activity, Search, Database, Clock } from 'lucide-react';

export const SignalDetail = () => {
    const { id } = useParams(); // รับ ID จาก URL เช่น /signals/597
    const navigate = useNavigate();
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchDetail = async () => {
            try {
                const response = await fetch(`${import.meta.env.VITE_API_URL}/api/signals/${id}`);
                const result = await response.json();
                setData(result);
            } catch (error) {
                console.error("Error fetching detail:", error);
            } finally {
                setLoading(false);
            }
        };
        fetchDetail();
    }, [id]);

    if (loading) return <div className="p-20 text-center font-sans text-gray-400">Analyzing Intelligence Trace...</div>;
    if (!data) return <div className="p-20 text-center font-sans text-gray-400">Signal not found.</div>;

    return (
        <div className="min-h-screen bg-[#fcfcfd] font-sans pb-20">
            {/* Top Navigation */}
            <div className="max-w-5xl mx-auto px-6 py-8">
                <button
                    onClick={() => navigate(-1)}
                    className="flex items-center gap-2 text-gray-400 hover:text-gray-900 transition-colors mb-8"
                >
                    <ArrowLeft size={20} />
                    <span className="text-sm font-medium">Back to Dashboard</span>
                </button>

                {/* Header Section */}
                <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-12">
                    <div>
                        <div className="flex items-center gap-3 mb-4">
                            <span className="px-3 py-1 bg-[#824199]/10 text-[#824199] rounded-full text-xs font-bold tracking-widest uppercase">
                                Logic Trace
                            </span>
                            <span className="text-gray-300">/</span>
                            <span className="text-gray-400 text-sm font-mono">ID #{data.id}</span>
                        </div>
                        <h1 className="text-4xl font-bold text-gray-950 tracking-tight">
                            Intelligence <span className="italic font-normal text-gray-400">Report</span>
                        </h1>
                    </div>

                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                    {/* Left Column: The "Why" (Rationale & Logic) */}
                    <div className="lg:col-span-2 space-y-8">

                        {/* Logic Process Block */}
                        <div className="bg-white border border-gray-100 rounded-[32px] p-8 shadow-sm">
                            <div className="flex items-center gap-3 mb-6">
                                <div className="w-10 h-10 bg-[#824199] rounded-xl flex items-center justify-center text-white">
                                    <Brain size={20} />
                                </div>
                                <h2 className="text-xl font-bold">Thought Process</h2>
                            </div>

                            <div className="space-y-6">
                                <p className="text-gray-600 leading-relaxed italic border-l-4 border-gray-100 pl-6 py-2">
                                    "{data.rationale}"
                                </p>

                                {/* Simulation of Steps from trace_json */}
                                <div className="space-y-5 mt-8 relative before:absolute before:inset-y-0 before:left-[15px] before:w-[2px] before:bg-gray-100">

                                    {formatTraceSteps(data.trace_json).map((step, idx) => (
                                        <div key={step.id} className="relative pl-10">

                                            {/* วงกลมไอคอน */}
                                            <div className={`absolute left-0 top-0 w-8 h-8 rounded-full flex items-center justify-center z-10 
        ${step.type === 'DECISION' ? 'bg-[#824199] text-white shadow-md ring-4 ring-white' : 'bg-white border-2 border-gray-200 text-gray-400'}`}>
                                                {step.icon}
                                            </div>

                                            {/* กล่องข้อความ */}
                                            <div className="bg-white border border-gray-100 shadow-sm rounded-2xl p-4 transition-all hover:border-gray-200 hover:shadow-md">
                                                <h4 className="text-sm font-bold text-gray-900 mb-1.5">{step.title}</h4>
                                                {/* เปลี่ยนจาก <p> เป็น <div> */}
                                                <div className="text-xs text-gray-600 leading-relaxed font-light">
                                                    {step.desc}
                                                </div>
                                            </div>

                                        </div>
                                    ))}

                                </div>
                            </div>
                        </div>

                        {/* Technical Context Block */}
                        <div className="bg-gray-50 border border-gray-100 rounded-[32px] p-8">
                            <h3 className="text-lg font-bold mb-6 flex items-center gap-3 text-gray-900">
                                <div className="w-8 h-8 rounded-xl bg-[#824199]/10 flex items-center justify-center text-[#824199]">
                                    <Activity size={18} />
                                </div>
                                Technical Context
                            </h3>
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
                                <div className="space-y-1">
                                    <p className="text-gray-500 text-[10px] uppercase font-bold tracking-wider">Entry Trigger</p>
                                    <p className="text-xl font-mono font-semibold text-gray-900">{data.entry_price || 'N/A'}</p>
                                </div>
                                <div className="space-y-1">
                                    <p className="text-gray-500 text-[10px] uppercase font-bold tracking-wider">Stop Loss</p>
                                    <p className="text-xl font-mono font-semibold text-rose-600">{data.stop_loss || 'N/A'}</p>
                                </div>
                                <div className="space-y-1">
                                    <p className="text-gray-500 text-[10px] uppercase font-bold tracking-wider">Timeframe</p>
                                    <p className="text-xl font-mono font-semibold text-gray-900">{data.interval_tf || '1H'}</p>
                                </div>
                                <div className="space-y-1">
                                    <p className="text-gray-500 text-[10px] uppercase font-bold tracking-wider">Tokens Used</p>
                                    <p className="text-xl font-mono font-semibold text-gray-900">
                                        {data.token_total ? data.token_total.toLocaleString() : 0}
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Right Column: Metadata */}
                    <div className="space-y-6">

                        <div className="bg-white border border-gray-100 p-4 rounded-2xl shadow-sm flex items-center gap-6">
                            <div className="text-center px-4 border-r border-gray-50">
                                <p className="text-[10px] text-gray-400 uppercase font-bold mb-1">Decision</p>
                                <p className={`text-xl font-black ${data.signal === 'BUY' ? 'text-emerald-600' : data.signal === 'SELL' ? 'text-rose-600' : 'text-amber-600'}`}>
                                    {data.signal}
                                </p>
                            </div>
                            <div className="text-center px-4">
                                <p className="text-[10px] text-gray-400 uppercase font-bold mb-1">Confidence</p>
                                <p className="text-xl font-black text-gray-900">{Math.round(data.confidence * 100)}%</p>
                            </div>
                        </div>

                        <div className="bg-white border border-gray-100 rounded-[28px] p-6 shadow-sm">
                            <h4 className="font-bold text-gray-900 mb-4 flex items-center gap-2">
                                <Clock size={16} className="text-gray-400" />
                                Execution Details
                            </h4>
                            <div className="space-y-4">
                                <MetaItem label="Model Provider" value={data.provider || 'Gemini 3 Flash'} />
                                <MetaItem label="Execution Time" value={`${data.elapsed_ms || 0}ms`} />
                                <MetaItem label="Iteration" value={data.iteration || 1} />
                                <MetaItem label="Logged At" value={new Date(data.logged_at).toLocaleString()} />
                            </div>
                        </div>

                    </div>
                </div>
            </div>
        </div>
    );
};

// Reusable Components
const StepItem = ({ icon, title, desc }: any) => (
    <div className="flex gap-4">
        <div className="flex-none w-8 h-8 rounded-full bg-gray-50 flex items-center justify-center text-gray-400 mt-1">
            {icon}
        </div>
        <div>
            <h4 className="text-sm font-bold text-gray-900">{title}</h4>
            <p className="text-xs text-gray-500 leading-relaxed">{desc}</p>
        </div>
    </div>
);

const MetaItem = ({ label, value }: any) => (
    <div className="flex justify-between items-center py-2 border-b border-gray-50 last:border-0">
        <span className="text-xs text-gray-400 font-medium">{label}</span>
        <span className="text-xs text-gray-900 font-bold">{value}</span>
    </div>
);

const formatTraceSteps = (traceJsonString: string) => {
    if (!traceJsonString) return [];

    try {
        const rawSteps = JSON.parse(traceJsonString);
        const formattedSteps: any[] = [];

        rawSteps.forEach((stepItem: any, index: number) => {
            // 1. THOUGHT
            if (stepItem.step.startsWith('THOUGHT') && stepItem.response?.thought) {
                formattedSteps.push({
                    id: `thought-${index}`,
                    type: 'THOUGHT',
                    title: `Iteration ${stepItem.iteration} Analysis`,
                    desc: stepItem.response.thought,
                    icon: <Brain size={16} />,
                });
            }

            // 2. TOOL_EXECUTION
            if (stepItem.step === 'TOOL_EXECUTION') {
                const cleanToolName = stepItem.tool_name.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase());

                let toolDetails: React.ReactNode = 'Executed tool successfully.';

                if (stepItem.observation?.data) {
                    const obsData = stepItem.observation.data;

                    // กรณี: get_htf_trend
                    if (stepItem.tool_name === 'get_htf_trend') {
                        if (obsData.status === 'error') {
                            toolDetails = <span className="text-rose-600 font-medium bg-rose-50 px-2 py-1 rounded-md text-[11px]">⚠️ {obsData.message}</span>;
                        } else {
                            // นำข้อมูล Trend ทั้งหมดมาโชว์แบบตาราง
                            const { status, ...restData } = obsData;
                            toolDetails = (
                                <div className="mt-2 rounded-lg p-3">
                                    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                                        {Object.entries(restData).map(([key, value]) => (
                                            <div key={key} className="text-[11px]">
                                                <span className="text-gray-500 capitalize">{key.replace(/_/g, ' ')}: </span>
                                                <span className="font-semibold text-gray-900">{String(value)}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            );
                        }
                    }
                    // กรณี: get_deep_news_by_category
                    else if (stepItem.tool_name === 'get_deep_news_by_category' && obsData.articles) {
                        toolDetails = (
                            <div className="mt-3">
                                <p className="text-[11px] font-bold text-[#824199] uppercase tracking-wider mb-3">
                                    Analyzed {obsData.articles.length} Articles:
                                </p>
                                <ul className="space-y-3 border-l-2 border-[#824199]/20 pl-3">
                                    {/* เอา .slice(0,3) ออก เพื่อให้โชว์ครบทุกข่าว */}
                                    {obsData.articles.map((article: any, i: number) => (
                                        <li key={i} className="text-[11px] leading-relaxed text-gray-600">
                                            <span className="font-bold text-gray-900 block mb-0.5">{article.title}</span>
                                            <div className="flex items-center gap-2 mt-1">
                                                <span className="text-gray-400 font-mono bg-gray-50 px-1.5 py-0.5 rounded text-[10px] border border-gray-100">
                                                    {article.source}
                                                </span>
                                                {/* ถ้าข่าวมีค่า Sentiment โชว์ด้วย */}
                                                {article.sentiment !== undefined && article.sentiment !== null && (
                                                    <span className={`px-1.5 py-0.5 rounded text-[10px] ${article.sentiment > 0 ? 'text-emerald-600 bg-emerald-50' : article.sentiment < 0 ? 'text-rose-600 bg-rose-50' : 'text-gray-500 bg-gray-100'}`}>
                                                        Score: {article.sentiment}
                                                    </span>
                                                )}
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        );
                    }
                    // กรณี: เครื่องมืออื่นๆ นอกเหนือจาก 2 ตัวนี้
                    else {
                        const { status, ...restData } = obsData;
                        toolDetails = (
                            <div className="mt-2">
                                <pre className="text-[10px] bg-gray-50 p-3 rounded-lg border border-gray-100 text-gray-600 overflow-x-auto font-mono">
                                    {JSON.stringify(restData, null, 2)}
                                </pre>
                            </div>
                        );
                    }
                } else if (stepItem.observation?.error) {
                    toolDetails = <span className="text-rose-600 font-medium">❌ Error: {stepItem.observation.error}</span>;
                }

                formattedSteps.push({
                    id: `tool-${index}`,
                    type: 'ACTION',
                    title: `Tool: ${cleanToolName}`,
                    desc: toolDetails,
                    icon: <Search size={16} />,
                });
            }

            // 3. FINAL_DECISION
            if (stepItem.response?.action === 'FINAL_DECISION') {
                formattedSteps.push({
                    id: `final-${index}`,
                    type: 'DECISION',
                    title: `Final Decision: ${stepItem.response.signal}`,
                    desc: stepItem.response.rationale,
                    icon: <Database size={16} />,
                });
            }
        });

        return formattedSteps;

    } catch (error) {
        console.error("Failed to parse trace_json", error);
        return [];
    }
};