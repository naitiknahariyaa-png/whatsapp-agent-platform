"use client";

import React, { useState, useEffect, useRef } from "react";
import Navbar from "@/components/Navbar";
import ThreeScene from "@/components/ThreeScene";
import Hero from "@/components/Hero";
import Features from "@/components/Features";
import Testimonials from "@/components/Testimonials";
import ProgressIndicator from "@/components/ProgressIndicator";

export default function Home() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeSection, setActiveSection] = useState(0);
  const [mouse, setMouse] = useState({ x: 0, y: 0 });
  const [isMounted, setIsMounted] = useState(false);

  // 1. Ensure client-side initialization
  useEffect(() => {
    setIsMounted(true);
  }, []);

  // 2. Mouse position tracking (normalized coordinate system [-1, 1])
  useEffect(() => {
    if (!isMounted) return;

    const handlePointerMove = (e: PointerEvent) => {
      const x = (e.clientX / window.innerWidth) * 2 - 1;
      const y = -(e.clientY / window.innerHeight) * 2 + 1;
      setMouse({ x, y });
    };

    window.addEventListener("pointermove", handlePointerMove);
    return () => window.removeEventListener("pointermove", handlePointerMove);
  }, [isMounted]);

  // 3. Scroll position detection for updating active section
  const handleScroll = () => {
    if (containerRef.current) {
      const scrollTop = containerRef.current.scrollTop;
      const height = window.innerHeight;
      const index = Math.round(scrollTop / height);
      if (index !== activeSection && index >= 0 && index < 3) {
        setActiveSection(index);
      }
    }
  };

  // 4. Smooth scrolling callback triggered by dots and nav clicks
  const scrollToSection = (index: number) => {
    if (containerRef.current) {
      containerRef.current.scrollTo({
        top: index * window.innerHeight,
        behavior: "smooth",
      });
      setActiveSection(index);
    }
  };

  if (!isMounted) {
    return <div className="min-h-screen bg-[#050508]" />;
  }

  return (
    <main className="relative w-full h-screen overflow-hidden bg-[#050508]">
      {/* GLOBAL BACKGROUND GLOW (CYAN AND PURPLE NEON AMBIENCE) */}
      <div className="absolute top-[10%] left-[-10%] w-[40vw] h-[40vw] rounded-full bg-neon-blue/5 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[10%] right-[-10%] w-[45vw] h-[45vw] rounded-full bg-neon-purple/5 blur-[150px] pointer-events-none" />

      {/* TOP HEADER */}
      <Navbar onNavClick={scrollToSection} />

      {/* BACKGROUND/OVERLAY 3D ELEMENT */}
      <ThreeScene mouse={mouse} activeSection={activeSection} />

      {/* FULLSCREEN SNAP SCROLL CONTAINER */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="snap-container no-scrollbar z-20 relative w-full h-full"
      >
        <Hero />
        <Features />
        <Testimonials />
      </div>

      {/* FIXED NAVIGATION PROGRESS PANEL */}
      <ProgressIndicator
        activeSection={activeSection}
        totalSections={3}
        onDotClick={scrollToSection}
      />
    </main>
  );
}
