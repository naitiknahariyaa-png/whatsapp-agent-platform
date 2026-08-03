"use client";

import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowDown } from "lucide-react";

interface ProgressIndicatorProps {
  activeSection: number;
  totalSections: number;
  onDotClick: (index: number) => void;
}

export default function ProgressIndicator({
  activeSection,
  totalSections,
  onDotClick,
}: ProgressIndicatorProps) {
  const sectionsInfo = [
    { label: "INTRO", index: 0 },
    { label: "PRODUCT", index: 1 },
    { label: "REVIEWS", index: 2 },
  ];

  return (
    <>
      {/* 1. FIXED RIGHT PROGRESS DOTS PANEL */}
      <div className="fixed right-8 top-1/2 -translate-y-1/2 z-40 hidden md:flex flex-col items-center space-y-6">
        {/* Track Line */}
        <div className="absolute top-0 bottom-0 right-[7px] w-[1px] bg-slate-800 -z-10" />
        
        {sectionsInfo.map((sec) => {
          const isActive = activeSection === sec.index;
          return (
            <button
              key={sec.index}
              onClick={() => onDotClick(sec.index)}
              className="flex items-center space-x-4 group cursor-pointer focus:outline-none"
            >
              {/* Text label showing on hover or when active */}
              <AnimatePresence>
                {(isActive || sec.index === activeSection) && (
                  <motion.span
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: isActive ? 1 : 0.4, x: 0 }}
                    exit={{ opacity: 0, x: -10 }}
                    className={`font-display text-xs font-bold tracking-widest ${
                      isActive
                        ? "text-neon-blue text-glow-blue"
                        : "text-slate-500 group-hover:opacity-100 group-hover:text-slate-300"
                    }`}
                  >
                    {sec.label}
                  </motion.span>
                )}
              </AnimatePresence>

              {/* Dot */}
              <div className="relative w-4 h-4 flex items-center justify-center">
                <motion.div
                  animate={{
                    scale: isActive ? 1.3 : 1,
                    backgroundColor: isActive ? "#00f2fe" : "#1e293b",
                    boxShadow: isActive ? "0 0 10px #00f2fe" : "none",
                  }}
                  className="w-2.5 h-2.5 rounded-full transition-all duration-300"
                />
              </div>
            </button>
          );
        })}
      </div>

      {/* 2. BOTTOM SCROLL INDICATOR */}
      <AnimatePresence>
        {activeSection < totalSections - 1 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            transition={{ delay: 1 }}
            className="fixed bottom-8 left-1/2 -translate-x-1/2 z-40 flex flex-col items-center cursor-pointer pointer-events-none"
          >
            <span className="font-display text-[9px] font-bold tracking-widest text-slate-500 mb-2">
              SCROLL
            </span>
            <motion.div
              animate={{ y: [0, 6, 0] }}
              transition={{ repeat: Infinity, duration: 1.5, ease: "easeInOut" }}
              className="text-neon-purple shadow-[0_0_10px_rgba(157,78,221,0.2)]"
            >
              <ArrowDown size={14} className="stroke-[2.5px]" />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
