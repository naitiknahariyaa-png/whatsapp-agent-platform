"use client";

import React from "react";
import { motion } from "framer-motion";

interface NavbarProps {
  onNavClick: (index: number) => void;
}

export default function Navbar({ onNavClick }: NavbarProps) {
  const menuLinks = [
    { label: "Solutions", sectionIndex: 0 },
    { label: "Features", sectionIndex: 1 },
    { label: "Learn", sectionIndex: 1 },
    { label: "Reviews", sectionIndex: 2 },
    { label: "Contact us", sectionIndex: 2 },
  ];

  return (
    <motion.header
      initial={{ y: -100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, ease: "easeOut" }}
      className="fixed top-0 left-0 right-0 z-50 bg-background/30 backdrop-blur-md border-b border-dark-border/40"
    >
      <div className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
        {/* LOGO */}
        <div className="flex items-center space-x-3 cursor-pointer" onClick={() => onNavClick(0)}>
          <div className="w-9 h-9 bg-gradient-to-tr from-neon-blue to-neon-purple rounded-lg flex items-center justify-center shadow-[0_0_15px_rgba(0,242,254,0.4)]">
            <span className="font-display font-bold text-white text-base">C</span>
          </div>
          <span className="font-display font-bold text-xl tracking-tight bg-gradient-to-r from-white via-slate-100 to-neon-blue bg-clip-text text-transparent">
            ChainAI
          </span>
        </div>

        {/* MIDDLE LINKS */}
        <nav className="hidden md:flex items-center space-x-8">
          {menuLinks.map((link, i) => (
            <button
              key={i}
              onClick={() => onNavClick(link.sectionIndex)}
              className="text-sm font-medium text-slate-400 hover:text-white hover:text-glow-blue transition-all cursor-pointer relative py-1 group"
            >
              {link.label}
              <span className="absolute bottom-0 left-0 w-0 h-[2px] bg-gradient-to-r from-neon-blue to-neon-purple group-hover:w-full transition-all duration-300" />
            </button>
          ))}
        </nav>

        {/* RIGHT CTA BUTTON */}
        <div className="flex items-center">
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.98 }}
            className="relative px-5 py-2.5 rounded-lg font-display font-semibold text-xs tracking-wider uppercase text-white bg-slate-900/50 border border-neon-blue/30 hover:border-neon-blue/80 hover:shadow-[0_0_20px_rgba(0,242,254,0.3)] transition-all cursor-pointer overflow-hidden group"
          >
            {/* Ambient hover glow */}
            <span className="absolute inset-0 w-full h-full bg-gradient-to-r from-neon-blue/10 to-neon-purple/10 opacity-0 group-hover:opacity-100 transition-opacity" />
            LAUNCH DAPP
          </motion.button>
        </div>
      </div>
    </motion.header>
  );
}
