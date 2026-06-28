import React from 'react';
import { Camera, Mail, User as UserIcon } from 'lucide-react';

export const ProfileSettings = () => (
  <div className="bg-white p-8 rounded-[24px] border border-gray-100 shadow-sm flex flex-col gap-10">
    <div className="flex items-center gap-6">
      <div className="relative group">
        <div className="w-24 h-24 rounded-full bg-purple-50 flex items-center justify-center border-2 border-gray-50 overflow-hidden">
           <UserIcon size={40} className="text-[#824199]" />
        </div>
        <button className="absolute bottom-0 right-0 p-2 bg-white rounded-full border border-gray-100 shadow-md text-[#824199] hover:scale-110 transition-transform">
          <Camera size={14} />
        </button>
      </div>
      <div>
        <h3 className="text-xl font-black text-gray-900">John Doe</h3>
        <p className="text-sm text-gray-400 font-medium">Gold Trader · Joined April 2026</p>
      </div>
    </div>

    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <InputGroup label="Display Name" value="John Doe" />
      <InputGroup label="Email Address" value="john@example.com" disabled />
      <InputGroup label="Timezone" value="(GMT+07:00) Bangkok" />
      <InputGroup label="Preferred Language" value="Thai / English" />
    </div>

    <div className="flex justify-end pt-4">
      <button className="px-8 py-3 bg-[#1a0a24] text-white text-xs font-black uppercase tracking-widest rounded-xl hover:shadow-lg transition-all">
        Update Profile
      </button>
    </div>
  </div>
);

const InputGroup = ({ label, value, disabled = false }: any) => (
  <div className="flex flex-col gap-2">
    <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">{label}</label>
    <input 
      type="text" defaultValue={value} disabled={disabled}
      className={`px-4 py-3 rounded-xl border border-gray-100 text-sm font-bold focus:outline-none focus:ring-2 focus:ring-purple-100 transition-all ${disabled ? 'bg-gray-50 text-gray-400 cursor-not-allowed' : 'text-gray-900'}`}
    />
  </div>
);