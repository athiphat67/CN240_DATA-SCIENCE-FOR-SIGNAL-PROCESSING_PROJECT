import React from 'react';
import { ShieldCheck, Lock, Smartphone, ChevronRight } from 'lucide-react';

export const SecuritySettings = () => (
  <div className="flex flex-col gap-6">
    <div className="bg-white p-8 rounded-[24px] border border-gray-100 shadow-sm">
      <h3 className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em] mb-8">Access Security</h3>
      
      <div className="divide-y divide-gray-50">
        <SecurityAction 
            icon={<Lock size={18}/>} title="Change Password" desc="Update your login credentials regularly to keep your account safe." 
            action="Update" 
        />
        <SecurityAction 
            icon={<Smartphone size={18}/>} title="Two-Factor Authentication (2FA)" desc="Add an extra layer of security by requiring a code from your device." 
            action="Enable" highlight
        />
        <SecurityAction 
            icon={<ShieldCheck size={18}/>} title="Active Sessions" desc="View and manage all devices currently logged into your account." 
            action="View All" 
        />
      </div>
    </div>
  </div>
);

const SecurityAction = ({ icon, title, desc, action, highlight = false }: any) => (
  <div className="py-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 group">
    <div className="flex gap-5 items-start">
        <div className="p-2.5 bg-purple-50 rounded-xl text-[#824199] mt-0.5">{icon}</div>
        <div>
            <h4 className="text-sm font-bold text-gray-900">{title}</h4>
            <p className="text-xs text-gray-500 font-medium mt-1 leading-relaxed max-w-md">{desc}</p>
        </div>
    </div>
    <button className={`px-5 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all ${highlight ? 'bg-[#824199] text-white shadow-lg' : 'bg-gray-50 text-gray-400 hover:text-gray-900 border border-gray-100'}`}>
        {action}
    </button>
  </div>
);