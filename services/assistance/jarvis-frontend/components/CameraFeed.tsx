import React, { useEffect, useRef } from 'react';

interface CameraFeedProps {
  onFrame: (base64: string) => void;
  active: boolean;
}

const CameraFeed: React.FC<CameraFeedProps> = ({ onFrame, active }) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let mounted = true;
    let stream: MediaStream | null = null;
    let interval: number;

    const startCamera = async () => {
      try {
        const mediaStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
        
        if (!mounted) {
          mediaStream.getTracks().forEach(track => track.stop());
          return;
        }

        stream = mediaStream;
        
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          try {
            await videoRef.current.play();
          } catch (e: any) {
            // Ignore abort errors which happen during rapid component updates
            if (e.name !== 'AbortError') {
              console.error("Video playback error:", e);
            }
          }
        }

        // Start frame capture loop
        interval = window.setInterval(() => {
          if (!mounted || !active || !videoRef.current || !canvasRef.current) return;
          
          const video = videoRef.current;
          const canvas = canvasRef.current;
          const ctx = canvas.getContext('2d');
          
          if (ctx && video.readyState === video.HAVE_ENOUGH_DATA) {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            // Draw flipped for mirror effect if preferred, but usually raw for AI
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            
            const base64 = canvas.toDataURL('image/jpeg', 0.7);
            onFrame(base64);
          }
        }, 500); // 2 FPS (500ms) for better responsiveness

      } catch (err) {
        if (mounted) {
          console.error("Camera access failed", err);
        }
      }
    };

    if (active) {
      startCamera();
    }

    return () => {
      mounted = false;
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
      clearInterval(interval);
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    };
  }, [active, onFrame]);

  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-700 bg-black shadow-[0_0_15px_rgba(14,165,233,0.3)]">
      <video 
        ref={videoRef} 
        muted 
        playsInline 
        className="w-full h-auto object-cover opacity-80"
      />
      <canvas ref={canvasRef} className="hidden" />
      <div className="absolute top-2 left-2 flex items-center gap-2">
         <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></div>
         <span className="text-[10px] text-red-400 font-hud tracking-widest uppercase">Live Feed</span>
      </div>
      {/* HUD Overlays */}
      <div className="absolute top-0 left-0 w-8 h-8 border-t-2 border-l-2 border-cyan-500/50 rounded-tl-md"></div>
      <div className="absolute top-0 right-0 w-8 h-8 border-t-2 border-r-2 border-cyan-500/50 rounded-tr-md"></div>
      <div className="absolute bottom-0 left-0 w-8 h-8 border-b-2 border-l-2 border-cyan-500/50 rounded-bl-md"></div>
      <div className="absolute bottom-0 right-0 w-8 h-8 border-b-2 border-r-2 border-cyan-500/50 rounded-br-md"></div>
    </div>
  );
};

export default CameraFeed;