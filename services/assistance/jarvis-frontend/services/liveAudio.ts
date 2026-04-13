import { float32To16BitPCM, arrayBufferToBase64, base64ToUint8Array, pcm16ToAudioBuffer } from "./audioUtils";

export type AudioSendFn = (payload: unknown) => boolean;

export interface AudioManager {
	inputAudioContext: AudioContext | null;
	outputAudioContext: AudioContext | null;
	inputSource: MediaStreamAudioSourceNode | null;
	inputWorkletNode: AudioWorkletNode | null;
	inputStream: MediaStream | null;
	nextStartTime: number;
	isStreamingAudio: boolean;
	audioInitError: string | null;
}

/**
 * Creates a lazy-initialized AudioManager. Contexts are NOT created until
 * ensureAudioInput() is called to satisfy browser autoplay policies.
 */
export function makeAudioManager(): AudioManager {
	return {
		inputAudioContext: null,
		outputAudioContext: null,
		inputSource: null,
		inputWorkletNode: null,
		inputStream: null,
		nextStartTime: 0,
		isStreamingAudio: false,
		audioInitError: null,
	};
}

// Inline AudioWorklet processor code
const PCM_PROCESSOR_CODE = `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input && input[0] && input[0].length > 0) {
      this.port.postMessage({ channelData: input[0] });
    }
    return true;
  }
}
registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
`;

let _workletUrl: string | null = null;

async function getWorkletUrl(): Promise<string> {
	if (_workletUrl) return _workletUrl;
	
	try {
		// Try to create a Blob URL first (preferred)
		const blob = new Blob([PCM_PROCESSOR_CODE], { type: "application/javascript" });
		_workletUrl = URL.createObjectURL(blob);
		console.log("[LiveAudio] Created Blob URL for worklet");
		return _workletUrl;
	} catch (e) {
		console.warn("[LiveAudio] Blob URL failed, trying data URL:", e);
		// Fallback to data URL if Blob fails
		const encoded = encodeURIComponent(PCM_PROCESSOR_CODE);
		_workletUrl = `data:application/javascript;charset=utf-8,${encoded}`;
		console.log("[LiveAudio] Created data URL for worklet");
		return _workletUrl;
	}
}

export async function setupAudioInput(
	am: AudioManager,
	stream: MediaStream,
	createTraceId: (p: string) => string,
	send: AudioSendFn,
	onVolume: (v: number) => void,
): Promise<void> {
	console.log("[LiveAudio] setupAudioInput started, isStreamingAudio=", am.isStreamingAudio);
	if (!am.inputAudioContext) {
		console.error("[LiveAudio] No inputAudioContext!");
		return;
	}
	console.log("[LiveAudio] AudioContext state:", am.inputAudioContext.state);
	try {
		console.log("[LiveAudio] Loading inline AudioWorklet...");
		const workletUrl = await getWorkletUrl();
		console.log("[LiveAudio] Worklet URL:", workletUrl.substring(0, 50) + "...");
		await am.inputAudioContext.audioWorklet.addModule(workletUrl);
		console.log("[LiveAudio] AudioWorklet module loaded");
	} catch (e) {
		console.error("[LiveAudio] AudioWorklet addModule failed", e);
		return;
	}
	console.log("[LiveAudio] Creating MediaStreamSource...");
	am.inputSource = am.inputAudioContext.createMediaStreamSource(stream);
	console.log("[LiveAudio] MediaStreamSource created");
	console.log("[LiveAudio] Creating AudioWorkletNode...");
	am.inputWorkletNode = new AudioWorkletNode(am.inputAudioContext, "pcm-capture-processor");
	console.log("[LiveAudio] AudioWorkletNode created, attaching onmessage...");
	am.inputWorkletNode.port.onmessage = (ev: MessageEvent<{ channelData: Float32Array }>) => {
		const inputData = ev.data.channelData;
		// Log EVERY frame for first 20 frames to see if worklet is receiving data
		if ((window as any)._audioFrameCount === undefined) (window as any)._audioFrameCount = 0;
		(window as any)._audioFrameCount++;
		if ((window as any)._audioFrameCount <= 20) {
			console.log(`[LiveAudio] RAW FRAME #${(window as any)._audioFrameCount}: len=${inputData.length}, streaming=${am.isStreamingAudio}, sample[0]=${inputData[0]?.toFixed(4)}`);
		}
		let sum = 0;
		for (let i = 0; i < inputData.length; i++) sum += inputData[i] * inputData[i];
		const volume = Math.sqrt(sum / inputData.length);
		if ((window as any)._audioFrameCount <= 20) {
			console.log(`[LiveAudio] Volume: ${volume.toFixed(6)}`);
		}
		onVolume(volume);
		if (am.isStreamingAudio) {
			const pcm16 = float32To16BitPCM(inputData);
			const base64 = arrayBufferToBase64(pcm16);
			send({
				type: "audio",
				trace_id: createTraceId("audio"),
				mimeType: "audio/pcm;rate=16000",
				data: base64,
			});
		} else if ((window as any)._audioFrameCount <= 20 && (window as any)._audioFrameCount % 5 === 0) {
			console.log(`[LiveAudio] Frame dropped - isStreamingAudio=false`);
		}
	};
	console.log("[LiveAudio] Connecting audio graph...");
	am.inputSource.connect(am.inputWorkletNode);
	am.inputWorkletNode.connect(am.inputAudioContext.destination);
	console.log("[LiveAudio] Audio graph connected, worklet should now receive data");
}

export async function teardownAudio(am: AudioManager): Promise<void> {
	// Remove message handler first to prevent callbacks during teardown
	if (am.inputWorkletNode) {
		try { am.inputWorkletNode.port.onmessage = null; } catch { }
		try { am.inputWorkletNode.disconnect(); } catch { }
		am.inputWorkletNode = null;
	}
	if (am.inputSource) {
		try { am.inputSource.disconnect(); } catch { }
		am.inputSource = null;
	}
	if (am.inputAudioContext) { await am.inputAudioContext.close(); am.inputAudioContext = null; }
	if (am.outputAudioContext) { await am.outputAudioContext.close(); am.outputAudioContext = null; }
	am.nextStartTime = 0;
}

export async function playPcmAudio(am: AudioManager, data: string, sampleRate: number): Promise<void> {
	if (!am.outputAudioContext) return;
	try {
		if (am.outputAudioContext.state === "suspended") await am.outputAudioContext.resume();
	} catch {
		// ignore
	}
	am.nextStartTime = Math.max(am.nextStartTime, am.outputAudioContext.currentTime);
	const pcmBytes = base64ToUint8Array(data);
	const audioBuffer = await pcm16ToAudioBuffer(pcmBytes, am.outputAudioContext, sampleRate);
	const source = am.outputAudioContext.createBufferSource();
	source.buffer = audioBuffer;
	source.connect(am.outputAudioContext.destination);
	source.start(am.nextStartTime);
	am.nextStartTime += audioBuffer.duration;
}
