import React, { useState } from 'react';
import { OverviewHeader } from '../overview/OverviewHeader';
import { User, Bot, Bell, Shield, Key, LogOut } from 'lucide-react';
import { AgentSettings } from './AgentSettings';
import { NotificationSettings } from './NotificationSettings';
import { ProfileSettings } from './ProfileSettings';
import { ApiKeysSettings } from './ApiKeySettings';
import { SecuritySettings } from './SecuritySettings';

export const SettingsSection = () => {
  const [activeTab, setActiveTab] = useState('profile');

  const menuItems = [
    { id: 'profile', label: 'My Profile', icon: <User size={18} /> },
    { id: 'agent', label: 'Agent & Risk', icon: <Bot size={18} /> },
    { id: 'api', label: 'API Keys', icon: <Key size={18} /> },
    { id: 'notifications', label: 'Notifications', icon: <Bell size={18} /> },
    { id: 'security', label: 'Security', icon: <Shield size={18} /> },
  ];

  return (
    <section className="w-full min-h-screen pb-16 bg-[#fcfcfd] relative overflow-hidden font-sans scroll-mt-24">
      <OverviewHeader />

      <div className="px-6 mt-8 max-w-[1200px] mx-auto relative z-20">
        <div className="mb-8">
          <h1 className="font-['Newsreader'] font-normal text-gray-900 text-4xl md:text-5xl tracking-tight leading-none">
            Account <span className="italic text-[#824199]">Settings</span>
          </h1>
          <p className="text-gray-500 text-sm font-medium mt-3">Configure your trading environment and personal security.</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Sidebar */}
          <div className="lg:col-span-3 flex flex-col gap-1.5">
            {menuItems.map((item) => (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`flex items-center gap-3 px-4 py-3.5 rounded-[16px] text-sm font-bold transition-all ${
                  activeTab === item.id 
                  ? 'bg-[#1a0a24] text-white shadow-lg' 
                  : 'text-gray-500 hover:bg-white hover:text-gray-900 border border-transparent hover:border-gray-100'
                }`}
              >
                {item.icon} {item.label}
              </button>
            ))}
            <div className="w-full h-[1px] bg-gray-200 my-4" />
            <button className="flex items-center gap-3 px-4 py-3.5 rounded-[16px] text-sm font-bold text-rose-500 hover:bg-rose-50 transition-all">
              <LogOut size={18} /> Log Out
            </button>
          </div>

          {/* Dynamic Content Area */}
          <div className="lg:col-span-9">
            {activeTab === 'profile' && <ProfileSettings />}
            {activeTab === 'agent' && <AgentSettings />}
            {activeTab === 'api' && <ApiKeysSettings />}
            {activeTab === 'notifications' && <NotificationSettings />}
            {activeTab === 'security' && <SecuritySettings />}
          </div>
        </div>
      </div>
    </section>
  );
};