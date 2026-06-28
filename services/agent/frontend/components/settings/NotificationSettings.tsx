import React, { useState } from 'react';
import { BellRing, Smartphone, Mail, AlertTriangle, FileText } from 'lucide-react';

export const NotificationSettings = () => {
  const [alerts, setAlerts] = useState({
    signalAlerts: true,
    dailySummary: false,
    riskWarning: true,
    systemUpdates: false
  });

  const toggleAlert = (key: keyof typeof alerts) => {
    setAlerts(prev => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="bg-white p-8 rounded-[24px] border border-gray-100 shadow-[0_4px_20px_rgba(0,0,0,0.02)]">
        <h2 className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em] mb-6 flex items-center gap-2">
          <BellRing size={16} className="text-gray-400"/> Notification Preferences
        </h2>

        <div className="divide-y divide-gray-100">
          
          <AlertItem 
            icon={<Smartphone size={18}/>} title="Signal Alerts" desc="Receive instant alerts via LINE/Telegram when the AI generates a new BUY/SELL recommendation." 
            enabled={alerts.signalAlerts} onToggle={() => toggleAlert('signalAlerts')} color="text-[#824199] bg-purple-50"
          />
          <AlertItem 
            icon={<AlertTriangle size={18}/>} title="Risk Warnings" desc="Immediate alerts if the virtual portfolio drawdown nears your configured maximum limit." 
            enabled={alerts.riskWarning} onToggle={() => toggleAlert('riskWarning')} color="text-rose-500 bg-rose-50"
          />
          <AlertItem 
            icon={<FileText size={18}/>} title="Daily Performance Digest" desc="Receive an email summary of the day's signal accuracy and AI rationale report." 
            enabled={alerts.dailySummary} onToggle={() => toggleAlert('dailySummary')} color="text-blue-500 bg-blue-50"
          />
          <AlertItem 
            icon={<BellRing size={18}/>} title="System Updates" desc="Get notified about major neural engine upgrades or maintenance." 
            enabled={alerts.systemUpdates} onToggle={() => toggleAlert('systemUpdates')} color="text-gray-500 bg-gray-100"
          />

        </div>
      </div>

      <div className="flex justify-end mt-4">
        <button className="px-10 py-4 bg-[#1a0a24] text-white text-sm font-black uppercase tracking-widest rounded-2xl shadow-[0_10px_30px_rgba(26,10,36,0.15)] hover:shadow-[0_10px_40px_rgba(130,65,153,0.3)] transition-all">
          Save Preferences
        </button>
      </div>
    </div>
  );
};

const AlertItem = ({ icon, title, desc, enabled, onToggle, color }: any) => (
    <div className="py-6 flex items-center justify-between group hover:bg-gray-50/50 px-2 -mx-2 rounded-xl transition-colors">
        <div className="flex gap-5 items-start">
            <div className={`p-2.5 rounded-xl mt-0.5 ${color}`}>{icon}</div>
            <div>
                <h4 className="text-sm font-bold text-gray-900">{title}</h4>
                <p className="text-xs text-gray-500 font-medium mt-1 leading-relaxed max-w-lg">{desc}</p>
            </div>
        </div>
        <button onClick={onToggle} className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-300 ease-in-out focus:outline-none ${enabled ? 'bg-emerald-500' : 'bg-gray-200'}`}>
            <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-md ring-0 transition duration-300 ease-in-out ${enabled ? 'translate-x-5' : 'translate-x-0'}`} />
        </button>
    </div>
);