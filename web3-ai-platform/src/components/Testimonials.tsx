"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight, Quote } from "lucide-react";

export default function Testimonials() {
  const reviews = [
    {
      quote: "ChainAI's smart contract auditor saved our DEX from a critical re-entrancy vulnerability that could have drained $40M in TVL. The speed is unparalleled.",
      name: "Alex Thorne",
      title: "Lead Architect",
      company: "HydraSwap Protocol",
    },
    {
      quote: "The whale wallet trackers and machine-learning predictions have completely reshaped how we manage our treasury reserves. Truly a game changer.",
      name: "Sarah Lin",
      title: "Director of Treasury",
      company: "Eclipse Capital",
    },
    {
      quote: "We deployed our cross-chain yield pools in record time using ChainAI's code generators. The compiler optimizations are industry-leading.",
      name: "Marcus Vance",
      title: "Co-Founder",
      company: "Synapse Network",
    },
  ];

  const [current, setCurrent] = useState(0);

  const handleNext = () => {
    setCurrent((prev) => (prev + 1) % reviews.length);
  };

  const handlePrev = () => {
    setCurrent((prev) => (prev - 1 + reviews.length) % reviews.length);
  };

  return (
    <section className="snap-section flex items-center px-6 md:px-20 relative overflow-hidden select-none bg-[#050508]">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom,rgba(0,242,254,0.03)_0%,transparent_60%)] pointer-events-none" />

      <div className="max-w-7xl mx-auto w-full grid grid-cols-1 md:grid-cols-2 gap-12 items-center relative z-20">
        
        {/* LEFT COLUMN: TESTIMONIAL PANEL */}
        <div className="flex flex-col space-y-8 max-w-xl text-left">
          
          {/* Tag and Title */}
          <div className="space-y-3">
            <span className="text-[10px] font-bold tracking-widest text-neon-blue uppercase">
              Web3 Verification
            </span>
            <h2 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold tracking-tight uppercase text-white leading-tight">
              Trusted by <br />
              <span className="bg-gradient-to-r from-neon-blue via-neon-purple to-neon-orange bg-clip-text text-transparent text-glow-purple">
                The Web3 Elite
              </span>
            </h2>
          </div>

          {/* Testimonial Display Area */}
          <div className="glass-panel-glow p-8 md:p-10 rounded-2xl relative min-h-[250px] flex flex-col justify-between">
            {/* Quote Icon overlay */}
            <div className="absolute top-6 right-8 text-slate-800/40 pointer-events-none">
              <Quote size={50} className="stroke-[1.5px]" />
            </div>

            <div className="relative overflow-hidden flex-1 flex items-center">
              <AnimatePresence mode="wait">
                <motion.div
                  key={current}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.4, ease: "easeInOut" }}
                  className="space-y-6"
                >
                  <p className="text-slate-200 text-sm sm:text-base md:text-lg leading-relaxed font-medium italic">
                    "{reviews[current].quote}"
                  </p>
                  
                  <div>
                    <h4 className="font-display font-bold text-base text-neon-blue">
                      {reviews[current].name}
                    </h4>
                    <p className="text-slate-500 text-xs tracking-wider">
                      {reviews[current].title} &bull; <span className="text-slate-400 font-semibold">{reviews[current].company}</span>
                    </p>
                  </div>
                </motion.div>
              </AnimatePresence>
            </div>

            {/* Nav Arrows */}
            <div className="flex items-center space-x-4 pt-6 border-t border-slate-900/60 mt-6 self-start">
              <button
                onClick={handlePrev}
                className="w-10 h-10 rounded-lg border border-slate-800 bg-slate-950 flex items-center justify-center text-slate-400 hover:text-white hover:border-neon-purple/50 hover:shadow-[0_0_15px_rgba(157,78,221,0.2)] transition-all cursor-pointer"
              >
                <ArrowLeft size={16} />
              </button>
              <button
                onClick={handleNext}
                className="w-10 h-10 rounded-lg border border-slate-800 bg-slate-950 flex items-center justify-center text-slate-400 hover:text-white hover:border-neon-purple/50 hover:shadow-[0_0_15px_rgba(157,78,221,0.2)] transition-all cursor-pointer"
              >
                <ArrowRight size={16} />
              </button>
            </div>

          </div>

        </div>

        {/* RIGHT COLUMN: BLANK SPACE (For 3D Model placement) */}
        <div className="hidden md:block h-[50vh]" />
        
      </div>
    </section>
  );
}
