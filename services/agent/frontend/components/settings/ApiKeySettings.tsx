import React from 'react';
import { Key, Eye, Copy, RefreshCw } from 'lucide-react';

export const ApiKeysSettings = () => (
  <div className="flex flex-col gap-6">
    <div className="bg-white p-8 rounded-[24px] border border-gray-100 shadow-sm">
      <h3 className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em] mb-8">AI Provider Integration</h3>
      
      <div className="space-y-6">
        <ApiKeyRow provider="OpenAI" status="Connected" />
        <ApiKeyRow provider="Anthropic" status="Not Set" color="gray" />
      </div>
    </div>

    <div className="bg-purple-50/50 p-6 rounded-[24px] border border-purple-100">
      <p className="text-[11px] text-purple-600 font-bold leading-relaxed">
        <span className="font-black">Security Note:</span> Your API keys are encrypted at rest. We only use these keys to communicate with LLM providers for gold market analysis as defined in our database protocols.
      </p>
    </div>
  </div>
);

const ApiKeyRow = ({ provider, status, color = "emerald" }: any) => (
  <div className="p-5 bg-gray-50 rounded-2xl border border-gray-100 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
    <div className="flex items-center gap-4">
      <div className="w-10 h-10 rounded-xl bg-white flex items-center justify-center shadow-sm border border-gray-100"><Key size={18} className="text-[#824199]" /></div>
      <div>
        <p className="text-sm font-black text-gray-900">{provider} API Key</p>
        <div className="flex items-center gap-1.5 mt-0.5">
           <span className={`w-1.5 h-1.5 rounded-full ${color === 'emerald' ? 'bg-emerald-500' : 'bg-gray-300'}`} />
           <p className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">{status}</p>
        </div>
      </div>
    </div>
    <div className="flex items-center gap-2">
      <button className="p-2.5 bg-white rounded-lg border border-gray-100 text-gray-400 hover:text-[#824199] transition-colors"><Eye size={14}/></button>
      <button className="p-2.5 bg-white rounded-lg border border-gray-100 text-gray-400 hover:text-[#824199] transition-colors"><Copy size={14}/></button>
      <button className="px-4 py-2 bg-[#1a0a24] text-white text-[10px] font-black rounded-lg uppercase tracking-widest hover:shadow-md transition-all">Configure</button>
    </div>
  </div>
);