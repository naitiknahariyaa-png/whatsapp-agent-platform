"use client";

import React from "react";
import { motion, Variants } from "framer-motion";
import { ArrowRight, Terminal } from "lucide-react";

export default function Hero() {
  const containerVariants: Variants = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: 0.15,
      },
    },
  };

  const itemVariants: Variants = {
    hidden: { y: 30, opacity: 0 },
    visible: {
      y: 0,
      opacity: 1,
      transition: { duration: 0.8, ease: "easeOut" },
    },
  };

  return (
    <section className="snap-section flex items-center px-6 md:px-20 relative overflow-hidden select-none bg-[#050508]">
      {/* Decorative cyber grid or lighting */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(76,29,149,0.05)_0%,transparent_70%)] pointer-events-none" />

      <div className="max-w-7xl mx-auto w-full grid grid-cols-1 md:grid-cols-2 gap-12 items-center relative z-20">
        
        {/* LEFT COLUMN: HEADINGS & TEXT */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="flex flex-col space-y-6 text-left max-w-xl"
        >
          {/* Neon chip tag */}
          <motion.div variants={itemVariants} className="inline-flex items-center self-start px-3.5 py-1 rounded-full border border-neon-blue/20 bg-neon-blue/5 text-[10px] font-bold tracking-widest text-neon-blue uppercase">
            <Terminal size={12} className="mr-2" />
            Consensus-Powered Intelligence
          </motion.div>

          {/* Heading */}
          <motion.h1
            variants={itemVariants}
            className="font-display text-4xl sm:text-5xl md:text-6xl font-extrabold tracking-tight leading-tight text-white uppercase"
          >
            Unleash the <br />
            power of <br />
            <span className="bg-gradient-to-r from-neon-blue via-neon-purple to-neon-orange bg-clip-text text-transparent text-glow-blue">
              Blockchain AI
            </span>
          </motion.h1>

          {/* Subtitle */}
          <motion.p
            variants={itemVariants}
            className="text-slate-400 text-sm sm:text-base leading-relaxed font-sans max-w-lg"
          >
            Supercharge your Web3 journey. Instantly audit smart contracts, track on-chain wallets, predict token charts, and auto-generate decentralized code with ChainAI's high-consensus LLM.
          </motion.p>

          {/* CTA Buttons */}
          <motion.div variants={itemVariants} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 pt-2">
            <button className="flex items-center justify-center px-6 py-3.5 bg-gradient-to-r from-neon-blue to-neon-purple text-white font-display font-bold text-xs tracking-wider uppercase rounded-lg hover:shadow-[0_0_25px_rgba(0,242,254,0.4)] hover:scale-[1.02] active:scale-[0.98] transition-all cursor-pointer">
              Launch Console
              <ArrowRight size={14} className="ml-2" />
            </button>
            <button className="flex items-center justify-center px-6 py-3.5 border border-slate-700 bg-slate-900/30 text-slate-300 hover:text-white hover:border-slate-500 font-display font-semibold text-xs tracking-wider uppercase rounded-lg transition-all cursor-pointer">
              Read Docs
            </button>
          </motion.div>

          {/* Technical Specs List */}
          <motion.div
            variants={itemVariants}
            className="grid grid-cols-3 gap-6 pt-8 border-t border-slate-900/60"
          >
            <div>
              <div className="text-xl font-bold font-display text-white">4,096</div>
              <div className="text-[10px] text-slate-500 tracking-wider font-semibold uppercase">Active Nodes</div>
            </div>
            <div>
              <div className="text-xl font-bold font-display text-neon-blue text-glow-blue">&lt; 0.4s</div>
              <div className="text-[10px] text-slate-500 tracking-wider font-semibold uppercase">Latency</div>
            </div>
            <div>
              <div className="text-xl font-bold font-display text-neon-purple text-glow-purple">Audited</div>
              <div className="text-[10px] text-slate-500 tracking-wider font-semibold uppercase">Security Cert</div>
            </div>
          </motion.div>
        </motion.div>

        {/* RIGHT COLUMN: BLANK SPACE (3D Canvas overlays here) */}
        <div className="hidden md:block h-[50vh]" />
        
      </div>
    </section>
  );
}
