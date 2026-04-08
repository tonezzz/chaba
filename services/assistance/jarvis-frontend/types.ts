export enum ConnectionState {
  DISCONNECTED = 'DISCONNECTED',
  CONNECTING = 'CONNECTING',
  CONNECTED = 'CONNECTED',
  ERROR = 'ERROR',
}

export interface GroundingSource {
  title: string;
  uri: string;
}

export interface MessageLog {
  id: string;
  role: 'user' | 'model' | 'system';
  text: string;
  timestamp: Date;
  metadata?: {
    image?: string;
    sources?: GroundingSource[];
    type?: 'search' | 'image_gen' | 'reimagine' | 'text';
    source?: 'input' | 'output';
    kind?: string;
    trace_id?: string;
    severity?: 'debug' | 'info' | 'warn' | 'error';
    category?: 'live' | 'reminder' | 'weaviate' | 'ws' | 'unknown';
    resume?: {
      ok: boolean;
      turns: Array<{ role: 'user' | 'model'; text: string; ts: number }>;
    };
    ws?: {
      type?: string;
      instance_id?: string;
      client_id?: string;
      client_tag?: string;
    };
    raw?: any;
  };
}

export interface AudioConfig {
  sampleRate: number;
}

export interface VoiceCmdModeKeywords {
  gems?: string[];
  knowledge?: string[];
  memory?: string[];
}

export interface VoiceCmdReloadCfg {
  enabled?: boolean;
  phrases?: string[];
  mode_keywords?: VoiceCmdModeKeywords;
}

export interface VoiceCmdFeatureCfg {
  enabled?: boolean;
  phrases?: string[];
}

export interface VoiceCmdConfig {
  enabled?: boolean;
  debounce_ms?: number;
  reload?: VoiceCmdReloadCfg;
  reminders_add?: VoiceCmdFeatureCfg;
  gems_list?: VoiceCmdFeatureCfg;
}

export interface ToolPendingEntry {
  resolve: (v: unknown) => void;
  reject: (e: unknown) => void;
  name: string;
  createdAt: number;
  timeoutId: number;
}

export interface WsReadinessEvent {
  phase: string;
  detail?: unknown;
  ts: number;
}

export interface PendingEventMessage {
  type: "pending_event";
  event?: string;
  action?: string;
  confirmation_id?: string;
  payload?: unknown;
  trace_id?: string;
}