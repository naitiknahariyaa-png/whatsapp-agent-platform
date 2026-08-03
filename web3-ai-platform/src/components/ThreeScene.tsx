"use client";

import React, { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import RobotModel from "./RobotModel";

interface ThreeSceneProps {
  mouse: { x: number; y: number };
  activeSection: number;
}

export default function ThreeScene({ mouse, activeSection }: ThreeSceneProps) {
  return (
    <div className="fixed top-0 right-0 w-full md:w-[50vw] h-screen z-10 pointer-events-none flex items-center justify-center">
      <div className="w-full h-[60vh] md:h-[80vh] pointer-events-auto">
        <Canvas
          shadows
          camera={{ position: [0, 0, 5.5], fov: 45 }}
          gl={{ antialias: true, alpha: true }}
        >
          {/* Ambient soft glow */}
          <ambientLight intensity={0.4} />
          
          {/* Neon Purple light from bottom-left */}
          <pointLight
            position={[-3, -2, 2]}
            intensity={3.0}
            color="#9d4edd"
            distance={10}
            decay={2}
          />
          
          {/* Neon Blue light from top-right */}
          <pointLight
            position={[3, 2, 2]}
            intensity={4.0}
            color="#00f2fe"
            distance={10}
            decay={2}
          />
          
          {/* Soft white backlighting for silhouette */}
          <directionalLight
            position={[0, 0, -4]}
            intensity={1.5}
            color="#ffffff"
          />

          <Suspense fallback={null}>
            <ResponsiveModel mouse={mouse} activeSection={activeSection} />
          </Suspense>
        </Canvas>
      </div>
    </div>
  );
}

// Responsive scale and position wrapper
function ResponsiveModel({ mouse, activeSection }: ThreeSceneProps) {
  // Simple check for responsive sizing inside canvas
  const [scale, setScale] = React.useState<[number, number, number]>([1.1, 1.1, 1.1]);
  const [position, setPosition] = React.useState<[number, number, number]>([0, 0, 0]);

  React.useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 768) {
        // Mobile layout: model is smaller and shifted up
        setScale([0.75, 0.75, 0.75]);
        setPosition([0, 0.6, 0]);
      } else {
        // Desktop layout
        setScale([1.1, 1.1, 1.1]);
        setPosition([0, 0, 0]);
      }
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <group position={position} scale={scale}>
      <RobotModel mouse={mouse} activeSection={activeSection} />
    </group>
  );
}
