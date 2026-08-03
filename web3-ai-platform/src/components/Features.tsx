"use client";

import React from "react";
import { motion } from "framer-motion";
import { ShieldCheck, BarChart3, Binary, ChevronRight } from "lucide-react";

export default function Features() {
  const featuresList = [
    {
      title: "Smart Code Auditor",
      desc: "Instantly scan Solidity and Rust smart contracts for logic vulnerabilities, re-entrancy vectors, and gas-fee optimization routes.",
      icon: <ShieldCheck className="text-neon-blue stroke-[1.5px]" size={26} />,
      color: "border-neon-blue/20 hover:border-neon-blue/60 hover:shadow-[0_0_20px_rgba(0,242,254,0.15)]",
    },
    {
      title: "Blockchain Analytics",
      desc: "Track on-chain smart money transfers, whale wallet accumulation profiles, and live liquidity health stats with zero-lag nodes.",
      icon: <BarChart3 className="text-neon-purple stroke-[1.5px]" size={26} />,
      color: "border-neon-purple/20 hover:border-neon-purple/60 hover:shadow-[0_0_20px_rgba(157,78,221,0.15)]",
    },
    {
      title: "Technical Predictions",
      desc: "Apply advanced sentiment analyses, order book depth mappings, and social hype vectors to predict chart movements and trends.",
      icon: <Binary className="text-neon-orange stroke-[1.5px]" size={26} />,
      color: "border-neon-orange/20 hover:border-neon-orange/60 hover:shadow-[0_0_20px_rgba(255,123,0,0.15)]",
    },
  ];

  // Duplicated text for smooth infinite loop marquee
  const tickerText = "• CODE AUDITING • WALLET ANALYTICS • CHART PREDICTION • DEPLOYER BOTS • THREAT DETECTION • YIELD MAPPING • DATA SCANNERS ";
  const duplicatedTickerText = Array(6).fill(tickerText).join("");

  return (
    <section className="snap-section flex items-center px-6 md:px-20 relative overflow-hidden select-none bg-[#07070d]">
      
      {/* 1. INFINITE HORIZONTAL TICKER IN THE BACKGROUND */}
      <div className="absolute inset-0 flex flex-col justify-center pointer-events-none opacity-2 z-0">
        <div className="w-full overflow-hidden rotate-[-6deg] scale-105 border-y border-slate-900 bg-slate-950/20 py-6">
          <div className="flex whitespace-nowrap animate-marquee">
            <span className="font-display text-4xl md:text-5xl font-black uppercase tracking-wider text-slate-900/40">
              {duplicatedTickerText}
            </span>
          </div>
        </div>
        <div className="w-full overflow-hidden rotate-[4deg] scale-105 border-y border-slate-900 bg-slate-950/20 py-6 mt-16">
          <div className="flex whitespace-nowrap animate-marquee [animation-direction:reverse]">
            <span className="font-display text-4xl md:text-5xl font-black uppercase tracking-wider text-slate-900/40">
              {duplicatedTickerText}
            </span>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto w-full grid grid-cols-1 md:grid-cols-2 gap-12 items-center relative z-20">
        
        {/* LEFT COLUMN: TITLE & FEATURES LIST */}
        <div className="flex flex-col space-y-8 max-w-xl">
          
          {/* Section title panel */}
          <div className="space-y-3">
            <span className="text-[10px] font-bold tracking-widest text-neon-purple uppercase">
              Web3 AI Toolset
            </span>
            <h2 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight uppercase text-white leading-tight">
              Your gateway to <br />
              <span className="bg-gradient-to-r from-neon-blue to-neon-purple bg-clip-text text-transparent text-glow-blue">
                Web3 AI
              </span>
            </h2>
          </div>

          {/* Cards Stack */}
          <div className="flex flex-col space-y-4">
            {featuresList.map((feat, i) => (
              <motion.div
                key={i}
                initial={{ x: -50, opacity: 0 }}
                whileInView={{ x: 0, opacity: 1 }}
                viewport={{ once: true }}
                transition={{ duration: 0.6, delay: i * 0.15, ease: "easeOut" }}
                className={`glass-panel p-5 rounded-xl border flex items-start space-x-4 cursor-pointer transition-all duration-300 group ${feat.color}`}
              >
                {/* Icon wrapper */}
                <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 group-hover:bg-slate-900 transition-colors">
                  {feat.icon}
                </div>
                
                {/* Description */}
                <div className="flex-1 text-left space-y-1">
                  <h3 className="font-display font-bold text-base text-white tracking-wide flex items-center justify-between">
                    {feat.title}
                    <ChevronRight size={14} className="opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all text-neon-blue" />
                  </h3>
                  <p className="text-slate-400 text-xs sm:text-sm leading-relaxed">
                    {feat.desc}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>

        </div>

        {/* RIGHT COLUMN: BLANK SPACE (For 3D Model placement) */}
        <div className="hidden md:block h-[50vh]" />
        
      </div>
    </section>
  );
}
