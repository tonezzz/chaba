import { base64ToUint8Array, float32To16BitPCM, arrayBufferToBase64, pcm16ToAudioBuffer } from "./audioUtils";
import { ConnectionState, MessageLog } from "../types";

export type CarsIngestResult = {
  type: "cars_ingest_result";
  request_id: string;
  ok: boolean;
  original_path?: string;
  detector?: any;
  items?: Array<{
    plate: string;
    json_path: string;
    plate_crop?: string | null;
    car_crop?: string | null;
    confidence?: number | null;
  }>;
  crops_written?: number;
  instance_id?: string;
  error?: string;
};

export class LiveService {
  private ws: WebSocket | null = null;
  private inputAudioContext: AudioContext | null = null;
  private outputAudioContext: AudioContext | null = null;
  private inputSource: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private nextStartTime: number = 0;
  private currentCameraFrame: string | null = null;
  private isStreamingAudio: boolean = false;
  private sessionId: string | null = null;

	private getOrCreateSessionId(): string {
		const storageKey = "jarvis_session_id";
		try {
			const existing = String(window.localStorage.getItem(storageKey) || "").trim();
			if (existing) return existing;
			const newId =
				(typeof crypto !== "undefined" && typeof (crypto as any).randomUUID === "function"
					? (crypto as any).randomUUID()
					: `${Date.now()}_${Math.random().toString(16).slice(2)}`);
			window.localStorage.setItem(storageKey, newId);
			return newId;
		} catch {
			return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
		}
	}

  public getSessionId(): string {
    if (!this.sessionId) this.sessionId = this.getOrCreateSessionId();
    return this.sessionId;
  }

  public async sendCarsIngestImage(file: File, requestId?: string) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("ws_not_connected");
    }
    const buf = await file.arrayBuffer();
    const b64 = arrayBufferToBase64(buf);
    const mimeType = String(file.type || "image/png") || "image/png";
    const reqId = String(requestId || `${Date.now()}_${Math.random().toString(16).slice(2)}`);
    this.ws.send(
      JSON.stringify({
        type: "cars_ingest_image",
        request_id: reqId,
        mimeType,
        data: b64,
      })
    );
    return reqId;
  }

  public onStateChange: (state: ConnectionState) => void = () => {};
  public onMessage: (msg: MessageLog) => void = () => {};
  public onVolume: (vol: number) => void = () => {};
  public onActiveTrip: (trip: { active_trip_id: string | null; active_trip_name: string | null }) => void = () => {};
  public onCarsIngestResult: (ev: CarsIngestResult) => void = () => {};

  constructor() {}

  public startStreaming() {
    this.isStreamingAudio = true;
  }

  public stopStreaming() {
    this.isStreamingAudio = false;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "audio_stream_end" }));
    }
  }

  public sendText(text: string) {
    const trimmed = String(text || "").trim();
    if (!trimmed) return;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "text", text: trimmed }));
    }
  }

  public updateCameraFrame(base64: string) {
    this.currentCameraFrame = base64;
    // Push frame to model to give it vision
    return;
  }

  public async connect() {
    this.onStateChange(ConnectionState.CONNECTING);

    try {
      this.inputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
      this.outputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const backendUrl = (import.meta as any).env?.VITE_JARVIS_WS_URL as string | undefined;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const isJarvisSubpath = location.pathname.startsWith("/jarvis");
      const defaultWsUrl = isJarvisSubpath
        ? `${proto}://${location.host}/jarvis/ws/live`
        : `${proto}://${location.hostname}:8018/ws/live`;
      const baseWsUrl = (backendUrl || defaultWsUrl).trim();
		const sessionId = this.getSessionId();
		let wsUrl = baseWsUrl;
		try {
			const u = new URL(baseWsUrl);
			u.searchParams.set("session_id", sessionId);
			wsUrl = u.toString();
		} catch {
			// If URL parsing fails, fall back to appending query param.
			wsUrl = baseWsUrl.includes("?") ? `${baseWsUrl}&session_id=${encodeURIComponent(sessionId)}` : `${baseWsUrl}?session_id=${encodeURIComponent(sessionId)}`;
		}

      this.ws = new WebSocket(wsUrl);
      this.ws.onopen = () => {
        this.onStateChange(ConnectionState.CONNECTED);
        this.onMessage({
          id: `${Date.now()}_ws_open`,
          role: "system",
          text: "connected",
          timestamp: new Date(),
        });
        this.setupAudioInput(stream);
      };
      this.ws.onclose = (ev) => {
        try {
          console.warn("ws_close", { code: ev.code, reason: ev.reason, wasClean: ev.wasClean });
        } catch {
          // ignore
        }
        this.onStateChange(ConnectionState.DISCONNECTED);
        this.onMessage({
          id: `${Date.now()}_ws_close`,
          role: "system",
          text: `disconnected (code=${ev.code}${ev.reason ? ` reason=${ev.reason}` : ""})`,
          timestamp: new Date(),
        });
      };
      this.ws.onerror = (err) => {
        console.error(err);
        this.onStateChange(ConnectionState.ERROR);
        this.onMessage({
          id: `${Date.now()}_ws_error`,
          role: "system",
          text: "connection_error",
          timestamp: new Date(),
        });
      };
      this.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          this.handleBackendMessage(msg);
        } catch (e) {
          console.error(e);
        }
      };

    } catch (error) {
      console.error("Connection failed", error);
      this.onStateChange(ConnectionState.ERROR);
    }
  }

  public async disconnect() {
    if (this.ws) {
      try {
        this.ws.send(JSON.stringify({ type: "close" }));
      } catch (e) {
        console.error(e);
      }
      this.ws.close();
    }
    
    if (this.inputSource) this.inputSource.disconnect();
    if (this.processor) {
        this.processor.disconnect();
        this.processor.onaudioprocess = null;
    }
    if (this.inputAudioContext) await this.inputAudioContext.close();
    if (this.outputAudioContext) await this.outputAudioContext.close();
    
    this.inputAudioContext = null;
    this.outputAudioContext = null;
    this.ws = null;
    this.onStateChange(ConnectionState.DISCONNECTED);
  }

	public requestActiveTrip() {
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.ws.send(JSON.stringify({ type: "get_active_trip" }));
		}
	}

	public setActiveTrip(active_trip_id: string | null, active_trip_name: string | null) {
		if (this.ws && this.ws.readyState === WebSocket.OPEN) {
			this.ws.send(
				JSON.stringify({
					type: "set_active_trip",
					active_trip_id,
					active_trip_name,
				})
			);
		}
	}

  private setupAudioInput(stream: MediaStream) {
    if (!this.inputAudioContext) return;
    
    this.inputSource = this.inputAudioContext.createMediaStreamSource(stream);
    this.processor = this.inputAudioContext.createScriptProcessor(4096, 1, 1);
    
    this.processor.onaudioprocess = (e) => {
      const inputData = e.inputBuffer.getChannelData(0);
      
      // Calculate volume for visualizer
      let sum = 0;
      for (let i = 0; i < inputData.length; i++) {
        sum += inputData[i] * inputData[i];
      }
      const rms = Math.sqrt(sum / inputData.length);
      this.onVolume(rms);

      const pcm16 = float32To16BitPCM(inputData);
      const base64 = arrayBufferToBase64(pcm16);

      if (this.isStreamingAudio && this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "audio", mimeType: "audio/pcm;rate=16000", data: base64 }));
      }
    };

    this.inputSource.connect(this.processor);
    this.processor.connect(this.inputAudioContext.destination);
  }

  private async handleBackendMessage(message: any) {
    if (message?.type === "state" && message?.state) {
      this.onMessage({
        id: `${Date.now()}_state`,
        role: "system",
        text: String(message.state),
        timestamp: new Date(),
      });
      return;
    }

    if (message?.type === "reminder" && message?.reminder) {
      const r = message.reminder;
      const title = r?.title != null ? String(r.title) : "Reminder";
      const schedule = r?.schedule_type != null ? String(r.schedule_type) : "";
      const text = schedule ? `reminder: ${title} (${schedule})` : `reminder: ${title}`;
      this.onMessage({
        id: `${Date.now()}_reminder`,
        role: "system",
        text,
        timestamp: new Date(),
      });
      return;
    }

		if (message?.type === "active_trip") {
			const active_trip_id = message?.active_trip_id != null ? String(message.active_trip_id) : null;
			const active_trip_name = message?.active_trip_name != null ? String(message.active_trip_name) : null;
			this.onActiveTrip({ active_trip_id, active_trip_name });
			this.onMessage({
				id: `${Date.now()}_trip_state`,
				role: "system",
				text: `active_trip=${active_trip_id || "(none)"}${active_trip_name ? ` (${active_trip_name})` : ""}`,
				timestamp: new Date(),
			});
			return;
		}

    if (message?.type === "cars_ingest_result" && message?.request_id) {
      try {
        this.onCarsIngestResult(message as CarsIngestResult);
      } catch {
        // ignore
      }
      return;
    }

    if (message?.type === "audio" && message?.data && this.outputAudioContext) {
      this.nextStartTime = Math.max(this.nextStartTime, this.outputAudioContext.currentTime);
      const pcmBytes = base64ToUint8Array(message.data);
      const audioBuffer = await pcm16ToAudioBuffer(pcmBytes, this.outputAudioContext, message.sampleRate || 24000);

      const source = this.outputAudioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.outputAudioContext.destination);
      source.start(this.nextStartTime);
      this.nextStartTime += audioBuffer.duration;
      return;
    }

    if (message?.type === "transcript" && message?.text) {
      this.onMessage({
        id: `${Date.now()}_tr`,
        role: "system",
        text: String(message.text),
        timestamp: new Date(),
        metadata: { type: "text", source: message?.source === "output" ? "output" : "input" },
      });
      return;
    }

    if (message?.type === "text" && message?.text) {
      this.onMessage({
        id: `${Date.now()}`,
        role: "model",
        text: String(message.text),
        timestamp: new Date(),
      });
      return;
    }

    if (message?.type === "error" && message?.message) {
      this.onMessage({
        id: `${Date.now()}_err`,
        role: "system",
        text: String(message.message),
        timestamp: new Date(),
      });
      // Backend can emit error events even while keeping the websocket open (e.g. Gemini Live session failed).
      // Do not treat these as transport disconnects.
      try {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.onStateChange(ConnectionState.CONNECTED);
        }
      } catch {
        // ignore
      }
      return;
    }
  }
}