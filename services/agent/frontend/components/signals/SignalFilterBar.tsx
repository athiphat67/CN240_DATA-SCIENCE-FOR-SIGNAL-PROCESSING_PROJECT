import React from 'react';
import { Search } from 'lucide-react';

export const SignalFilterBar = ({ activeFilter, setActiveFilter }: any) => {
  return (
    <div className="bg-white p-2 rounded-2xl border border-gray-100 shadow-sm flex items-center justify-between mb-6">
      <div className="flex items-center gap-2 px-4 w-full md:w-1/3 border-r border-gray-100">
        <Search size={18} className="text-gray-400" />
        <input 
          type="text" 
          placeholder="Search by ID or keywords..." 
          className="bg-transparent border-none outline-none text-sm w-full py-2 placeholder:text-gray-300" 
        />
      </div>
      <div className="flex items-center gap-1 px-4 overflow-x-auto">
        {['All', 'BUY', 'SELL', 'HOLD'].map(f => (
          <button 
            key={f} 
            onClick={() => setActiveFilter(f)}
            className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all ${
              activeFilter === f ? 'bg-gray-100 text-gray-900 shadow-sm' : 'text-gray-400 hover:text-gray-600'
            }`}
          >
            {f}
          </button>
        ))}
      </div>
    </div>
  );
};