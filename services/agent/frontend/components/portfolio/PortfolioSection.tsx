import React, { useState, useEffect } from 'react';
import { OverviewHeader } from '../overview/OverviewHeader';
import { PortfolioHeader } from './PortfolioHeader';

// Components
import { AgentHealthMonitor } from './AgentHealthMonitor';
import { PortfolioMarketBias } from './PortfolioMarketBias';
import { PortfolioActivePositions } from './PortfolioActivePositions';

// Icons
import { DollarSign, Percent, TrendingUp, ShieldCheck, Wallet, Globe, PencilLine } from 'lucide-react';

const API_CANDIDATES = [
  import.meta.env.VITE_API_URL,
  'http://localhost:8000',
  'http://127.0.0.1:8000',
  'http://localhost:8001',
  'http://127.0.0.1:8001',
].filter((value, index, list): value is string => Boolean(value) && list.indexOf(value) === index);

const fetchFromPortfolioApi = async (path: string, init?: RequestInit) => {
  let lastError: Error | null = null;

  for (const base of API_CANDIDATES) {
    try {
      return await fetch(`${base}${path}`, init);
    } catch (error) {
      lastError = error instanceof Error ? error : new Error('Failed to fetch');
    }
  }

  throw lastError ?? new Error('Failed to fetch');
};

// 1. กำหนด Interface สำหรับข้อมูลที่รับมาจาก API (/api/portfolio)
interface PortfolioData {
  available_cash: number;
  cash_balance: number;
  gold_grams: number;
  cost_basis_thb: number;
  current_value_thb: number;
  unrealized_pnl: number;
  pnl_percent: number;
  trades_today: number;
  total_equity: number;
  updated_at: string;
  trailing_stop_level_thb: number | null;
}

export const PortfolioSection = () => {
  // 2. สร้าง State สำหรับเก็บข้อมูลและสถานะการโหลด
  const [data, setData] = useState<PortfolioData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAddFundsOpen, setIsAddFundsOpen] = useState(false);
  const [isWithdrawOpen, setIsWithdrawOpen] = useState(false);
  const [isManualEditOpen, setIsManualEditOpen] = useState(false);
  const [fundAmount, setFundAmount] = useState('');
  const [withdrawAmount, setWithdrawAmount] = useState('');
  const [manualForm, setManualForm] = useState({
    cash_balance: '',
    gold_grams: '',
    cost_basis_thb: '',
    current_value_thb: '',
    unrealized_pnl: '',
    trades_today: '',
    trailing_stop_level_thb: '',
  });
  const [isSubmittingFunds, setIsSubmittingFunds] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [submitSuccess, setSubmitSuccess] = useState('');

  const syncManualForm = (portfolio: PortfolioData) => {
    setManualForm({
      cash_balance: String(portfolio.cash_balance ?? 0),
      gold_grams: String(portfolio.gold_grams ?? 0),
      cost_basis_thb: String(portfolio.cost_basis_thb ?? 0),
      current_value_thb: String(portfolio.current_value_thb ?? 0),
      unrealized_pnl: String(portfolio.unrealized_pnl ?? 0),
      trades_today: String(portfolio.trades_today ?? 0),
      trailing_stop_level_thb: portfolio.trailing_stop_level_thb == null ? '' : String(portfolio.trailing_stop_level_thb),
    });
  };

// 3. ฟังก์ชันสำหรับดึงข้อมูลจาก API
  const fetchPortfolioData = async () => {
    try {
      const response = await fetchFromPortfolioApi('/api/portfolio');
      
      if (!response.ok) throw new Error('Failed to fetch portfolio data');
      const result = await response.json();
      setData(result);
      if (!isManualEditOpen) syncManualForm(result);
    } catch (error) {
      console.error('Error fetching portfolio:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // 4. เรียกใช้ useEffect เพื่อ Fetch ข้อมูลเมื่อเปิดหน้าจอ และตั้ง Interval
  useEffect(() => {
    fetchPortfolioData();

    // Re-fetch ข้อมูลทุกๆ 10 วินาที เพื่อความเป็น Real-time
    const interval = setInterval(fetchPortfolioData, 10000);
    return () => clearInterval(interval);
  }, []);

  const closeAddFundsModal = () => {
    if (isSubmittingFunds) return;
    setIsAddFundsOpen(false);
    setFundAmount('');
    setSubmitError('');
  };

  const closeWithdrawModal = () => {
    if (isSubmittingFunds) return;
    setIsWithdrawOpen(false);
    setWithdrawAmount('');
    setSubmitError('');
  };

  const closeManualEditModal = () => {
    if (isSubmittingFunds) return;
    setIsManualEditOpen(false);
    setSubmitError('');
    if (data) syncManualForm(data);
  };

  const openAddFundsModal = () => {
    setSubmitSuccess('');
    setSubmitError('');
    setFundAmount('');
    setIsManualEditOpen(false);
    setIsWithdrawOpen(false);
    setIsAddFundsOpen(true);
  };

  const openWithdrawModal = () => {
    setSubmitSuccess('');
    setSubmitError('');
    setWithdrawAmount('');
    setIsAddFundsOpen(false);
    setIsManualEditOpen(false);
    setIsWithdrawOpen(true);
  };

  const openManualEditModal = () => {
    setSubmitSuccess('');
    setSubmitError('');
    setIsAddFundsOpen(false);
    setIsWithdrawOpen(false);
    if (data) syncManualForm(data);
    setIsManualEditOpen(true);
  };

  const handleAddFunds = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const amount = Number(fundAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setSubmitError('Please enter an amount greater than 0.');
      return;
    }

    setIsSubmittingFunds(true);
    setSubmitError('');

    try {
      const response = await fetchFromPortfolioApi(`/api/portfolio/add-funds?amount=${encodeURIComponent(amount)}`, {
        method: 'POST',
      });

      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Failed to add funds');
      }

      setData(result);
      syncManualForm(result);
      setSubmitSuccess(`Added ${formatNumber(amount)} THB to portfolio.`);
      setIsAddFundsOpen(false);
      setFundAmount('');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to reach portfolio API';
      setSubmitError(message);
    } finally {
      setIsSubmittingFunds(false);
    }
  };

  const handleWithdrawFunds = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const amount = Number(withdrawAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setSubmitError('Please enter an amount greater than 0.');
      return;
    }

    if (amount > (data?.available_cash ?? 0)) {
      setSubmitError('Withdrawal amount exceeds available cash balance.');
      return;
    }

    setIsSubmittingFunds(true);
    setSubmitError('');

    try {
      const response = await fetchFromPortfolioApi(`/api/portfolio/withdraw-funds?amount=${encodeURIComponent(amount)}`, {
        method: 'POST',
      });

      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Failed to withdraw funds');
      }

      setData(result);
      syncManualForm(result);
      setSubmitSuccess(`Withdrew ${formatNumber(amount)} THB from portfolio.`);
      setIsWithdrawOpen(false);
      setWithdrawAmount('');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to reach portfolio API';
      setSubmitError(message);
    } finally {
      setIsSubmittingFunds(false);
    }
  };

  const handleManualFieldChange = (field: keyof typeof manualForm, value: string) => {
    setManualForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleManualUpdate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmittingFunds(true);
    setSubmitError('');

    try {
      const params = new URLSearchParams();
      const requiredNumericFields: Array<keyof typeof manualForm> = [
        'cash_balance',
        'gold_grams',
        'cost_basis_thb',
        'current_value_thb',
        'unrealized_pnl',
        'trades_today',
      ];

      for (const field of requiredNumericFields) {
        const raw = manualForm[field].trim();
        const value = Number(raw);
        if (!raw || !Number.isFinite(value)) {
          throw new Error(`Invalid value for ${field}`);
        }
        params.set(field, raw);
      }

      const trailingRaw = manualForm.trailing_stop_level_thb.trim();
      if (trailingRaw !== '') {
        const trailingValue = Number(trailingRaw);
        if (!Number.isFinite(trailingValue)) {
          throw new Error('Invalid value for trailing_stop_level_thb');
        }
        params.set('trailing_stop_level_thb', trailingRaw);
      }

      const response = await fetchFromPortfolioApi(`/api/portfolio/manual-update?${params.toString()}`, {
        method: 'POST',
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Failed to update portfolio');
      }

      setData(result);
      syncManualForm(result);
      setSubmitSuccess('Portfolio fields updated manually.');
      setIsManualEditOpen(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to reach portfolio API';
      setSubmitError(message);
    } finally {
      setIsSubmittingFunds(false);
    }
  };

  // ฟังก์ชันช่วยจัดรูปแบบตัวเลข (เช่น 1,245,200)
  const formatNumber = (num: number | undefined) => {
    if (num === undefined) return "0";
    return new Intl.NumberFormat('th-TH', { maximumFractionDigits: 2 }).format(num);
  };

  return (
    <section className="w-full min-h-screen pb-12" style={{ background: '#FCFBF7' }}>
      <OverviewHeader />

      <div className="px-6 mt-8 relative z-20 max-w-7xl mx-auto">
        <PortfolioHeader
          onAddFunds={openAddFundsModal}
          onWithdrawFunds={openWithdrawModal}
          isSubmitting={isSubmittingFunds}
        />

        {submitSuccess ? (
          <div className="mb-6 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-bold text-emerald-700">
            {submitSuccess}
          </div>
        ) : null}

        {/* 🚀 BENTO BOX GRID SYSTEM 🚀 */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">

          {/* ======================================================== */}
          {/* LEFT COLUMN (8/12) - PERFORMANCE & POSITIONS */}
          {/* ======================================================== */}
          <div className="lg:col-span-8 flex flex-col gap-6">

            {/* 1. PROFIT MATRIX DASHBOARD (TOTAL NET EQUITY) */}
            <div className="relative bg-white/95 backdrop-blur-3xl rounded-[40px] border border-white shadow-[0_30px_70px_rgba(130,65,153,0.08)] overflow-hidden p-10 flex flex-col h-[340px] justify-between group transition-all duration-500 hover:translate-y-[-2px]">

              {/* Background Decor & Watermark */}
              <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-gradient-to-br from-purple-100/40 via-emerald-50/20 to-transparent blur-[110px] rounded-full -mr-32 -mt-32 pointer-events-none" />
              <div className="absolute -bottom-16 -right-16 opacity-[0.03] group-hover:opacity-[0.06] transition-opacity duration-1000 pointer-events-none group-hover:rotate-12 transition-transform">
                <Wallet size={320} strokeWidth={1} className="text-[#824199]" />
              </div>

              <div className="relative z-10">
                <div className="flex items-center justify-between mb-8">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-[#824199] to-[#a855f7] flex items-center justify-center shadow-[0_8px_20px_rgba(130,65,153,0.3)] group-hover:rotate-3 transition-transform">
                      <ShieldCheck size={20} className="text-white" />
                    </div>
                    <div>
                      <p className="text-[11px] font-black text-[#824199] uppercase tracking-[0.2em]">Verified Portfolio</p>
                      <p className="text-[9px] text-gray-400 font-bold uppercase tracking-widest">Global Asset Node</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 px-4 py-2 bg-emerald-50 border border-emerald-100 rounded-2xl shadow-sm">
                      <TrendingUp size={14} className="text-emerald-500" />
                      <span className="text-[10px] font-black text-emerald-600 uppercase tracking-tighter">
                        {data?.trades_today ?? 0} Trades Today
                      </span>
                    </div>
                  </div>
                </div>

                <div className="ml-2">
                  <p className="text-[11px] font-bold text-gray-400 uppercase tracking-[0.4em] mb-2 opacity-60">Total Net Equity</p>
                  <div className="flex items-baseline gap-3">
                    <p className="text-6xl font-black text-gray-900 tracking-tighter leading-none group-hover:scale-[1.01] transition-transform duration-500">
                      {isLoading ? "Loading..." : formatNumber(data?.total_equity)}
                    </p>
                    <div className="flex flex-col">
                      <span className="text-xl font-black text-[#824199] leading-none mb-1">฿</span>
                      <span className="text-[9px] font-bold text-gray-300 uppercase">THB</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Stats Footer */}
              <div className="relative z-10 flex items-end justify-between border-t border-gray-100 pt-8 mt-4 ml-2">
                <div className="flex gap-14">
                  <div className="relative">
                    <p className="text-[10px] font-bold text-gray-400 uppercase mb-2 tracking-widest">Trading Status</p>
                    <div className="flex items-center gap-2.5">
                      <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_12px_rgba(52,211,153,0.6)]" />
                      <p className="text-3xl font-black text-gray-900 tracking-tight">Active</p>
                    </div>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold text-gray-400 uppercase mb-2 tracking-widest">Total Growth</p>
                    <p className={`text-3xl font-black tracking-tight ${data && data.pnl_percent >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                      {data && data.pnl_percent > 0 ? '+' : ''}{data?.pnl_percent ?? 0}
                      <span className={`text-lg font-bold ml-1 ${data && data.pnl_percent >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>%</span>
                    </p>
                  </div>
                </div>

                <div className="flex flex-col items-end gap-1">
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 rounded-xl border border-gray-100 group-hover:border-purple-100 transition-colors">
                    <Globe size={12} className="text-gray-400 group-hover:text-[#824199]" />
                    <p className="text-[10px] font-black text-gray-500 uppercase tracking-widest">Live Node: TH-BK1</p>
                  </div>
                  <p className="text-[9px] font-bold text-gray-300 uppercase tracking-[0.1em] mr-1">
                    Last Sync: {new Date().toLocaleTimeString()}
                  </p>
                </div>
              </div>
            </div>


            {/* 2. SECONDARY STATS (CASH & P&L) */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {/* Available Cash Box */}
              <div className="bg-white p-6 rounded-[32px] border border-gray-100 shadow-sm flex items-center justify-between group hover:shadow-md transition-all">
                <div>
                  <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Available Cash</p>
                  <p className="text-2xl font-black text-gray-900">
                    {formatNumber(data?.available_cash)} <span className="text-sm font-bold text-gray-300 ml-1">฿</span>
                  </p>
                </div>
                <div className="w-14 h-14 rounded-2xl bg-gray-50 flex items-center justify-center text-gray-400 group-hover:bg-purple-50 group-hover:text-[#824199] transition-all">
                  <DollarSign size={24} />
                </div>
              </div>

              {/* Unrealized P&L Box */}
              <div className={`p-6 rounded-[32px] border-2 flex items-center justify-between group transition-all shadow-[0_4px_20px_rgba(0,0,0,0.05)] ${data && data.unrealized_pnl >= 0 ? 'bg-emerald-50/40 border-emerald-500' : 'bg-rose-50/40 border-rose-500'}`}>
                <div>
                  <p className={`text-[10px] font-bold uppercase tracking-widest mb-1 ${data && data.unrealized_pnl >= 0 ? 'text-emerald-600/70' : 'text-rose-600/70'}`}>Unrealized P&L</p>
                  <p className={`text-2xl font-black ${data && data.unrealized_pnl >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                    {data && data.unrealized_pnl > 0 ? '+' : ''}{formatNumber(data?.unrealized_pnl)} 
                    <span className="text-sm font-bold opacity-60 ml-1">฿</span>
                  </p>
                </div>
                <div className={`w-14 h-14 rounded-2xl flex items-center justify-center text-white group-hover:scale-110 transition-transform duration-500 shadow-lg ${data && data.unrealized_pnl >= 0 ? 'bg-emerald-500 shadow-emerald-200' : 'bg-rose-500 shadow-rose-200'}`}>
                  <Percent size={24} strokeWidth={3} />
                </div>
              </div>
            </div>

            {/* 3. ACTIVE POSITIONS */}
            <div className="flex-1">
              <PortfolioActivePositions />
            </div>
          </div>

          {/* ======================================================== */}
          {/* RIGHT COLUMN (4/12) - RISK & INTELLIGENCE */}
          {/* ======================================================== */}
          <div className="lg:col-span-4 flex flex-col gap-6">
            <div className="bg-white rounded-[32px] border border-gray-100 shadow-sm p-6">
              <div className="flex items-start justify-between gap-4 mb-5">
                <div>
                  <p className="text-[10px] font-black text-[#824199] uppercase tracking-[0.2em] mb-2">Portfolio Controls</p>
                  <h3 className="text-lg font-black text-gray-900">Portfolio Values</h3>
                  <p className="text-xs text-gray-500 mt-1">Values can be adjusted.</p>
                </div>
                <button
                  type="button"
                  onClick={openManualEditModal}
                  disabled={isSubmittingFunds}
                  className="inline-flex items-center gap-2 rounded-xl border border-[#824199]/20 px-3 py-2 text-xs font-black text-[#824199] hover:bg-purple-50 transition-all disabled:opacity-60"
                >
                  <PencilLine size={14} /> Manual Edit
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: 'Gold Grams', value: `${formatNumber(data?.gold_grams)} g` },
                  { label: 'Cost Basis', value: `${formatNumber(data?.cost_basis_thb)} THB/g` },
                  { label: 'Current Value', value: `${formatNumber(data?.current_value_thb)} THB` },
                  { label: 'Trailing Stop', value: data?.trailing_stop_level_thb == null ? '—' : `${formatNumber(data?.trailing_stop_level_thb)} THB/g` },
                  { label: 'Trades Today', value: `${data?.trades_today ?? 0}` },
                  { label: 'Updated At', value: data?.updated_at ? new Date(data.updated_at).toLocaleString() : '—' },
                ].map((item) => (
                  <div key={item.label} className="rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
                    <p className="text-[10px] font-black uppercase tracking-[0.15em] text-gray-400 mb-2">{item.label}</p>
                    <p className="text-sm font-black text-gray-900 break-words">{item.value}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="h-auto">
              <AgentHealthMonitor />
            </div>
            <div className="h-auto">
              <PortfolioMarketBias />
            </div>
          </div>

        </div>
      </div>

      {isAddFundsOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 backdrop-blur-sm px-4">
          <div className="w-full max-w-md rounded-[32px] bg-white border border-gray-100 shadow-[0_30px_80px_rgba(17,24,39,0.18)] p-7">
            <div className="flex items-start justify-between gap-4 mb-6">
              <div>
                <p className="text-[11px] font-black text-[#824199] uppercase tracking-[0.22em] mb-2">Portfolio Funding</p>
                <h2 className="text-2xl font-black text-gray-900 tracking-tight">Add cash to portfolio</h2>
                <p className="text-sm text-gray-500 mt-2">
                  Funds will be added directly to `cash_balance` in the portfolio database.
                </p>
              </div>
              <button
                type="button"
                onClick={closeAddFundsModal}
                className="text-sm font-black text-gray-300 hover:text-gray-500 transition-colors"
              >
                Close
              </button>
            </div>

            <form onSubmit={handleAddFunds} className="space-y-5">
              <div>
                <label htmlFor="fund-amount" className="block text-[11px] font-black text-gray-500 uppercase tracking-[0.2em] mb-2">
                  Amount (THB)
                </label>
                <input
                  id="fund-amount"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={fundAmount}
                  onChange={(event) => setFundAmount(event.target.value)}
                  placeholder="1000.00"
                  className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-lg font-bold text-gray-900 outline-none transition focus:border-[#824199] focus:bg-white"
                />
              </div>

              {submitError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-600">
                  {submitError}
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeAddFundsModal}
                  disabled={isSubmittingFunds}
                  className="px-4 py-2 rounded-xl border border-gray-200 text-sm font-bold text-gray-600 bg-white hover:bg-gray-50 transition-all disabled:opacity-60"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingFunds}
                  className="px-5 py-2 rounded-xl bg-[#824199] text-sm font-black text-white shadow-md hover:bg-[#6c3680] transition-all disabled:opacity-60"
                >
                  {isSubmittingFunds ? 'Saving...' : 'Confirm Add Funds'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {isWithdrawOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 backdrop-blur-sm px-4">
          <div className="w-full max-w-md rounded-[32px] bg-white border border-gray-100 shadow-[0_30px_80px_rgba(17,24,39,0.18)] p-7">
            <div className="flex items-start justify-between gap-4 mb-6">
              <div>
                <p className="text-[11px] font-black text-[#824199] uppercase tracking-[0.22em] mb-2">Portfolio Withdrawal</p>
                <h2 className="text-2xl font-black text-gray-900 tracking-tight">Withdraw cash balance</h2>
                <p className="text-sm text-gray-500 mt-2">
                  Withdrawals will reduce `cash_balance` directly in the portfolio database.
                </p>
                <p className="text-xs font-bold text-gray-400 mt-2">
                  Available now: {formatNumber(data?.available_cash)} THB
                </p>
              </div>
              <button
                type="button"
                onClick={closeWithdrawModal}
                className="text-sm font-black text-gray-300 hover:text-gray-500 transition-colors"
              >
                Close
              </button>
            </div>

            <form onSubmit={handleWithdrawFunds} className="space-y-5">
              <div>
                <label htmlFor="withdraw-amount" className="block text-[11px] font-black text-gray-500 uppercase tracking-[0.2em] mb-2">
                  Amount (THB)
                </label>
                <input
                  id="withdraw-amount"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={withdrawAmount}
                  onChange={(event) => setWithdrawAmount(event.target.value)}
                  placeholder="500.00"
                  className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-lg font-bold text-gray-900 outline-none transition focus:border-[#824199] focus:bg-white"
                />
              </div>

              {submitError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-600">
                  {submitError}
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeWithdrawModal}
                  disabled={isSubmittingFunds}
                  className="px-4 py-2 rounded-xl border border-gray-200 text-sm font-bold text-gray-600 bg-white hover:bg-gray-50 transition-all disabled:opacity-60"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingFunds}
                  className="px-5 py-2 rounded-xl bg-[#824199] text-sm font-black text-white shadow-md hover:bg-[#6c3680] transition-all disabled:opacity-60"
                >
                  {isSubmittingFunds ? 'Saving...' : 'Confirm Withdraw'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {isManualEditOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 backdrop-blur-sm px-4 py-6 overflow-y-auto">
          <div className="w-full max-w-2xl rounded-[32px] bg-white border border-gray-100 shadow-[0_30px_80px_rgba(17,24,39,0.18)] p-7">
            <div className="flex items-start justify-between gap-4 mb-6">
              <div>
                <p className="text-[11px] font-black text-[#824199] uppercase tracking-[0.22em] mb-2">Manual Portfolio Edit</p>
                <h2 className="text-2xl font-black text-gray-900 tracking-tight">Adjust portfolio table values</h2>
                <p className="text-sm text-gray-500 mt-2">
                  This writes directly to fields in `public.portfolio`. Use with care when reconciling manual changes.
                </p>
              </div>
              <button
                type="button"
                onClick={closeManualEditModal}
                className="text-sm font-black text-gray-300 hover:text-gray-500 transition-colors"
              >
                Close
              </button>
            </div>

            <form onSubmit={handleManualUpdate} className="space-y-5">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[
                  ['cash_balance', 'Cash Balance (THB)', '1500.00'],
                  ['gold_grams', 'Gold Grams', '0.0000'],
                  ['cost_basis_thb', 'Cost Basis (THB/g)', '0.00'],
                  ['current_value_thb', 'Current Value (THB)', '0.00'],
                  ['unrealized_pnl', 'Unrealized P&L (THB)', '0.00'],
                  ['trades_today', 'Trades Today', '0'],
                  ['trailing_stop_level_thb', 'Trailing Stop (THB/g)', 'optional'],
                ].map(([field, label, placeholder]) => (
                  <div key={field}>
                    <label htmlFor={field} className="block text-[11px] font-black text-gray-500 uppercase tracking-[0.2em] mb-2">
                      {label}
                    </label>
                    <input
                      id={field}
                      type="number"
                      step={field === 'trades_today' ? '1' : '0.01'}
                      min={field === 'unrealized_pnl' || field === 'cost_basis_thb' || field === 'trailing_stop_level_thb' ? undefined : '0'}
                      value={manualForm[field as keyof typeof manualForm]}
                      onChange={(event) => handleManualFieldChange(field as keyof typeof manualForm, event.target.value)}
                      placeholder={placeholder}
                      className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-base font-bold text-gray-900 outline-none transition focus:border-[#824199] focus:bg-white"
                    />
                  </div>
                ))}
              </div>

              {submitError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-600">
                  {submitError}
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeManualEditModal}
                  disabled={isSubmittingFunds}
                  className="px-4 py-2 rounded-xl border border-gray-200 text-sm font-bold text-gray-600 bg-white hover:bg-gray-50 transition-all disabled:opacity-60"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingFunds}
                  className="px-5 py-2 rounded-xl bg-[#824199] text-sm font-black text-white shadow-md hover:bg-[#6c3680] transition-all disabled:opacity-60"
                >
                  {isSubmittingFunds ? 'Saving...' : 'Save Manual Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </section>
  );
};
