"use client";

import React, { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

interface RobotModelProps {
  mouse: { x: number; y: number };
  activeSection: number;
}

export default function RobotModel({ mouse, activeSection }: RobotModelProps) {
  const groupRef = useRef<THREE.Group>(null);
  const ringRef1 = useRef<THREE.Mesh>(null);
  const ringRef2 = useRef<THREE.Mesh>(null);
  const ringRef3 = useRef<THREE.Mesh>(null);
  const faceGroupRef = useRef<THREE.Group>(null);

  // Dynamic animations inside the R3F render loop
  useFrame((state, delta) => {
    if (groupRef.current) {
      // 1. Mouse tracking: lerp rotation based on mouse coordinates
      const targetY = mouse.x * 0.45;
      const targetX = -mouse.y * 0.35;
      
      groupRef.current.rotation.y = THREE.MathUtils.lerp(
        groupRef.current.rotation.y,
        targetY,
        0.05
      );
      groupRef.current.rotation.x = THREE.MathUtils.lerp(
        groupRef.current.rotation.x,
        targetX,
        0.05
      );

      // Subtle float animation
      groupRef.current.position.y = Math.sin(state.clock.getElapsedTime() * 1.5) * 0.1;
    }

    // 2. Spin the orbital rings on separate axes
    if (ringRef1.current) {
      ringRef1.current.rotation.y += delta * 0.4;
      ringRef1.current.rotation.z += delta * 0.1;
    }
    if (ringRef2.current) {
      ringRef2.current.rotation.x += delta * 0.5;
      ringRef2.current.rotation.y += delta * 0.2;
    }
    if (ringRef3.current) {
      ringRef3.current.rotation.z += delta * 0.3;
      ringRef3.current.rotation.x += delta * 0.3;
    }

    // 3. Spin face indicators
    if (faceGroupRef.current) {
      if (activeSection === 1) {
        // Spinning loading gear/dots for Features section
        faceGroupRef.current.rotation.z -= delta * 2.0;
      } else {
        // Return to flat rotation
        faceGroupRef.current.rotation.z = THREE.MathUtils.lerp(
          faceGroupRef.current.rotation.z,
          0,
          0.1
        );
      }
    }
  });

  return (
    <group ref={groupRef}>
      {/* 1. CENTRAL AI CORE SPHERE */}
      <mesh castShadow receiveShadow>
        <icosahedronGeometry args={[1.0, 2]} />
        <meshStandardMaterial
          color="#0f0f20"
          roughness={0.1}
          metalness={0.9}
          flatShading
          emissive="#4C1D95"
          emissiveIntensity={0.2}
        />
      </mesh>

      {/* 2. CORE INNER LIGHT SHIELD (FACETED WIREFRAME GLOW) */}
      <mesh>
        <icosahedronGeometry args={[1.05, 1]} />
        <meshBasicMaterial
          color="#00f2fe"
          wireframe
          transparent
          opacity={0.15}
        />
      </mesh>

      {/* 3. FACE SCREEN BACKGROUND PANEL (FRONT-FACING BLACK DISK) */}
      <mesh position={[0, 0, 0.95]} rotation={[0, 0, 0]}>
        <circleGeometry args={[0.42, 32]} />
        <meshBasicMaterial color="#020205" />
      </mesh>
      
      {/* Face Screen Glow Border Ring */}
      <mesh position={[0, 0, 0.96]}>
        <ringGeometry args={[0.42, 0.44, 32]} />
        <meshBasicMaterial color="#9d4edd" />
      </mesh>

      {/* 4. DYNAMIC SYMBOLS SHOWN ON FACE */}
      <group ref={faceGroupRef} position={[0, 0, 0.97]}>
        
        {/* SECTION 0 (HERO): PULSING RADAR RINGS */}
        {activeSection === 0 && (
          <group>
            {/* Inner dot */}
            <mesh>
              <circleGeometry args={[0.06, 16]} />
              <meshBasicMaterial color="#00f2fe" />
            </mesh>
            {/* Pulsing ring 1 */}
            <PulseRing radius={0.18} speed={1.2} color="#00f2fe" />
            {/* Pulsing ring 2 */}
            <PulseRing radius={0.3} speed={0.8} color="#9d4edd" />
          </group>
        )}

        {/* SECTION 1 (FEATURES): ROTATING GEOMETRIC LOADING DOTS */}
        {activeSection === 1 && (
          <group>
            {/* Center ring */}
            <mesh>
              <ringGeometry args={[0.12, 0.14, 16]} />
              <meshBasicMaterial color="#ff7b00" />
            </mesh>
            {/* Satellite Dots */}
            {[0, 1, 2, 3].map((i) => {
              const angle = (i * Math.PI) / 2;
              return (
                <mesh key={i} position={[Math.cos(angle) * 0.25, Math.sin(angle) * 0.25, 0]}>
                  <sphereGeometry args={[0.04, 8, 8]} />
                  <meshBasicMaterial color="#ff7b00" />
                </mesh>
              );
            })}
          </group>
        )}

        {/* SECTION 2 (TESTIMONIALS): 3D GLOWING QUOTE MARKS */}
        {activeSection === 2 && (
          <group scale={[0.8, 0.8, 0.8]} position={[0, 0.05, 0]}>
            {/* Quote comma 1 */}
            <group position={[-0.12, 0, 0]}>
              <mesh rotation={[0, 0, 0.2]}>
                <cylinderGeometry args={[0.02, 0.02, 0.12, 8]} />
                <meshBasicMaterial color="#00f2fe" />
              </mesh>
              <mesh position={[-0.02, -0.07, 0]} rotation={[0, 0, 0.6]}>
                <cylinderGeometry args={[0.015, 0.005, 0.08, 8]} />
                <meshBasicMaterial color="#00f2fe" />
              </mesh>
            </group>
            
            {/* Quote comma 2 */}
            <group position={[0.12, 0, 0]}>
              <mesh rotation={[0, 0, 0.2]}>
                <cylinderGeometry args={[0.02, 0.02, 0.12, 8]} />
                <meshBasicMaterial color="#00f2fe" />
              </mesh>
              <mesh position={[-0.02, -0.07, 0]} rotation={[0, 0, 0.6]}>
                <cylinderGeometry args={[0.015, 0.005, 0.08, 8]} />
                <meshBasicMaterial color="#00f2fe" />
              </mesh>
            </group>
          </group>
        )}
      </group>

      {/* 5. SPINNING GYROSCOPIC ORBITAL RINGS */}
      {/* Ring 1 - Vertical (Neon Purple) */}
      <mesh ref={ringRef1} rotation={[0, 0.2, 0]}>
        <torusGeometry args={[1.7, 0.025, 8, 64]} />
        <meshBasicMaterial color="#9d4edd" transparent opacity={0.6} />
      </mesh>

      {/* Ring 2 - Horizontal (Neon Blue) */}
      <mesh ref={ringRef2} rotation={[Math.PI / 2, 0, 0.3]}>
        <torusGeometry args={[1.9, 0.015, 8, 64]} />
        <meshBasicMaterial color="#00f2fe" transparent opacity={0.7} />
      </mesh>

      {/* Ring 3 - Tilted Outer (Neon Orange) */}
      <mesh ref={ringRef3} rotation={[0.4, 0.4, 0.4]}>
        <torusGeometry args={[2.1, 0.01, 8, 64]} />
        <meshBasicMaterial color="#ff7b00" transparent opacity={0.5} />
      </mesh>

      {/* 6. PARTICLE CLOUD FIELD */}
      <PointsCloud count={200} radius={3.0} />
    </group>
  );
}

// Subcomponent: Pulsing ring helper for Radar effect on Face Screen
function PulseRing({ radius, speed, color }: { radius: number; speed: number; color: string }) {
  const meshRef = useRef<THREE.Mesh>(null);
  
  useFrame((state) => {
    if (meshRef.current) {
      const scale = 1 + Math.sin(state.clock.getElapsedTime() * speed * 4) * 0.15;
      meshRef.current.scale.set(scale, scale, 1);
    }
  });

  return (
    <mesh ref={meshRef}>
      <ringGeometry args={[radius - 0.01, radius + 0.01, 32]} />
      <meshBasicMaterial color={color} transparent opacity={0.8} />
    </mesh>
  );
}

// Subcomponent: Ambient particle cloud surrounding the model
function PointsCloud({ count, radius }: { count: number; radius: number }) {
  const pointsRef = useRef<THREE.Points>(null);

  useFrame((state, delta) => {
    if (pointsRef.current) {
      pointsRef.current.rotation.y += delta * 0.03;
      pointsRef.current.rotation.x += delta * 0.015;
    }
  });

  const positions = React.useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const theta = THREE.MathUtils.randFloat(0, Math.PI * 2);
      const phi = THREE.MathUtils.randFloat(0, Math.PI);
      const r = THREE.MathUtils.randFloat(radius * 0.7, radius * 1.5);

      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      arr[i * 3 + 2] = r * Math.cos(phi);
    }
    return arr;
  }, [count, radius]);

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
          count={count}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        color="#f8fafc"
        size={0.035}
        sizeAttenuation={true}
        transparent
        opacity={0.4}
      />
    </points>
  );
}
