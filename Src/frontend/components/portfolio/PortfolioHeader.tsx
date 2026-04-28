import React from 'react';
import { Download, Minus, Plus } from 'lucide-react';

interface PortfolioHeaderProps {
  onAddFunds: () => void;
  onWithdrawFunds: () => void;
  isSubmitting?: boolean;
}

export const PortfolioHeader = ({ onAddFunds, onWithdrawFunds, isSubmitting = false }: PortfolioHeaderProps) => {
  return (
    <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 tracking-tight mb-2">Portfolio Overview</h1>
        <p className="text-sm text-gray-500 font-medium">
          Real-time tracking of your assets, margin, and active agent positions.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <button className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-bold text-gray-700 shadow-sm hover:bg-gray-50 transition-all active:scale-95">
          <Download size={16} /> Statement
        </button>
        <button
          type="button"
          onClick={onWithdrawFunds}
          disabled={isSubmitting}
          className="flex items-center gap-2 px-4 py-2 bg-white text-[#824199] border border-[#824199]/20 rounded-xl text-sm font-bold shadow-sm hover:bg-purple-50 transition-all active:scale-95 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          <Minus size={16} /> {isSubmitting ? 'Saving...' : 'Withdraw'}
        </button>
        <button
          type="button"
          onClick={onAddFunds}
          disabled={isSubmitting}
          className="flex items-center gap-2 px-4 py-2 bg-[#824199] text-white rounded-xl text-sm font-bold shadow-md hover:bg-[#6c3680] transition-all active:scale-95 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          <Plus size={16} /> {isSubmitting ? 'Saving...' : 'Add Funds'}
        </button>
      </div>
    </div>
  );
};
