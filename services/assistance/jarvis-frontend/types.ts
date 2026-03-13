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
    trace_id?: string;
    severity?: 'debug' | 'info' | 'warn' | 'error';
    category?: 'live' | 'reminder' | 'weaviate' | 'ws' | 'unknown';
    ws?: {
      type?: string;
      instance_id?: string;
    };
    raw?: any;
  };
}

export interface AudioConfig {
  sampleRate: number;
}