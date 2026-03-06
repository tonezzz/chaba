import React, { useEffect, useRef } from 'react';

interface VisualizerProps {
  volume: number;
  active: boolean;
}

const Visualizer: React.FC<VisualizerProps> = ({ volume, active }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationId: number;
    let currentRadius = 50;
    
    const draw = () => {
      if (!active) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        // Draw idle state
        ctx.beginPath();
        ctx.arc(canvas.width / 2, canvas.height / 2, 40, 0, 2 * Math.PI);
        ctx.strokeStyle = '#0ea5e9';
        ctx.lineWidth = 2;
        ctx.stroke();
        return;
      }

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;
      
      // Smooth volume
      const targetRadius = 50 + (volume * 300); // Scale up
      currentRadius += (targetRadius - currentRadius) * 0.2;

      // Draw glow
      const gradient = ctx.createRadialGradient(centerX, centerY, currentRadius * 0.5, centerX, centerY, currentRadius * 1.5);
      gradient.addColorStop(0, 'rgba(14, 165, 233, 0.8)');
      gradient.addColorStop(1, 'rgba(14, 165, 233, 0)');
      
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(centerX, centerY, currentRadius * 1.5, 0, 2 * Math.PI);
      ctx.fill();

      // Draw core
      ctx.beginPath();
      ctx.arc(centerX, centerY, currentRadius, 0, 2 * Math.PI);
      ctx.fillStyle = '#0f172a';
      ctx.fill();
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 4;
      ctx.stroke();

      // Draw orbital rings
      const time = Date.now() / 1000;
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.5)';
      ctx.lineWidth = 1;
      
      ctx.beginPath();
      ctx.ellipse(centerX, centerY, currentRadius + 15, (currentRadius + 15) * 0.3, time, 0, 2 * Math.PI);
      ctx.stroke();

      ctx.beginPath();
      ctx.ellipse(centerX, centerY, currentRadius + 25, (currentRadius + 25) * 0.3, -time * 0.8, 0, 2 * Math.PI);
      ctx.stroke();

      animationId = requestAnimationFrame(draw);
    };

    draw();

    return () => cancelAnimationFrame(animationId);
  }, [volume, active]);

  return (
    <canvas 
      ref={canvasRef} 
      width={300} 
      height={300} 
      className="w-full h-full max-w-[300px] max-h-[300px]"
    />
  );
};

export default Visualizer;