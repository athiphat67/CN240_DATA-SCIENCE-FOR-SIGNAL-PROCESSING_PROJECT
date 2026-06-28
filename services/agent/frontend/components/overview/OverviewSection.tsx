import React, { useState } from 'react';
import { OverviewHeader } from './OverviewHeader';
import { RecentlySignal } from './RecentlySignal';
import { GrossPnL } from './GrossPnL';
import { StatsStack } from './StatsStack';
import { SignalLogTable } from './SignalLogTable';

export const OverviewSection = () => {
  return (
      <section 
        id="overview" 
        className="w-full min-h-screen pb-12 bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-yellow-100 via-white to-white"
      >
            
      {/* 1. Header Section */}
      <OverviewHeader />

      {/* 2. Main Content Grid */}
      <div className="px-6 mt-8 relative z-20 grid grid-cols-12 gap-4">
        
        <div className="col-span-12 lg:col-span-5"><RecentlySignal /></div>
        <div className="col-span-12 lg:col-span-4"><GrossPnL /></div>
        <div className="col-span-12 lg:col-span-3"><StatsStack /></div>
        <div className="col-span-12"><SignalLogTable /></div>
        
      </div>
    </section>
  );
};