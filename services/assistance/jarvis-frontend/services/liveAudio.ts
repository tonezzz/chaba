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

export async function setupAudioInput(
	am: AudioManager,
	stream: MediaStream,
	createTraceId: (p: string) => string,
	send: AudioSendFn,
	onVolume: (v: number) => void,
): Promise<void> {
	if (!am.inputAudioContext) return;
	try {
		await am.inputAudioContext.audioWorklet.addModule("/pcm-processor.js");
	} catch (e) {
		console.error("[LiveAudio] AudioWorklet addModule failed", e);
		return;
	}
	am.inputSource = am.inputAudioContext.createMediaStreamSource(stream);
	am.inputWorkletNode = new AudioWorkletNode(am.inputAudioContext, "pcm-capture-processor");
	am.inputWorkletNode.port.onmessage = (ev: MessageEvent<{ channelData: Float32Array }>) => {
		const inputData = ev.data.channelData;
		let sum = 0;
		for (let i = 0; i < inputData.length; i++) sum += inputData[i] * inputData[i];
		onVolume(Math.sqrt(sum / inputData.length));
		if (am.isStreamingAudio) {
			const pcm16 = float32To16BitPCM(inputData);
			const base64 = arrayBufferToBase64(pcm16);
			send({
				type: "audio",
				trace_id: createTraceId("audio"),
				mimeType: "audio/pcm;rate=16000",
				data: base64,
			});
		}
	};
	am.inputSource.connect(am.inputWorkletNode);
	am.inputWorkletNode.connect(am.inputAudioContext.destination);
}

export async function ensureAudioInput(
	am: AudioManager,
	stream: MediaStream,
	createTraceId: (p: string) => string,
	send: AudioSendFn,
	onVolume: (v: number) => void,
	onMessage: (msg: { id: string; role: string; text: string; timestamp: Date }) => void,
): Promise<void> {
	try {
		if (!am.inputAudioContext) {
			am.inputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
		}
		if (!am.outputAudioContext) {
			am.outputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });
		}
		if (!am.inputStream) {
			am.audioInitError = null;
			am.inputStream = await navigator.mediaDevices.getUserMedia({ audio: true });
		}
		if (am.inputStream) {
			await setupAudioInput(am, am.inputStream, createTraceId, send, onVolume);
		}
	} catch (audioErr: any) {
		am.inputStream = null;
		am.isStreamingAudio = false;
		const name = String(audioErr?.name || "unknown");
		const msg = String(audioErr?.message || audioErr || "unknown");
		am.audioInitError = `${name}: ${msg}`;
		try {
			onMessage({
				id: `${Date.now()}_audio_unavailable`,
				role: "system",
				text: `audio_unavailable: ${am.audioInitError}`,
				timestamp: new Date(),
			});
		} catch {
			// ignore
		}
	}
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
