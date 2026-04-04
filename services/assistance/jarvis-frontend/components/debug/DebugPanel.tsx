import React, { useState } from 'react';
import { Activity, ChevronDown, ChevronRight, Copy, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';

interface DebugEntry {
  id: string;
  timestamp: number;
  type: 'user' | 'model' | 'system' | 'error' | 'progress';
  text: string;
  traceId?: string;
  instanceId?: string;
  metadata?: Record<string, any>;
  expanded?: boolean;
}

interface DebugPanelProps {
  entries: DebugEntry[];
  showDebugLogs: boolean;
  onToggleDebugLogs: () => void;
  onCopyEntry: (entry: DebugEntry) => void;
  copiedId?: string;
}

export default function DebugPanel({
  entries,
  showDebugLogs,
  onToggleDebugLogs,
  onCopyEntry,
  copiedId
}: DebugPanelProps) {
  const [expandedEntries, setExpandedEntries] = useState<Set<string>>(new Set());

  const toggleExpanded = (entryId: string) => {
    const newExpanded = new Set(expandedEntries);
    if (newExpanded.has(entryId)) {
      newExpanded.delete(entryId);
    } else {
      newExpanded.add(entryId);
    }
    setExpandedEntries(newExpanded);
  };

  const getEntryIcon = (type: DebugEntry['type']) => {
    switch (type) {
      case 'user':
        return <div className="w-2 h-2 bg-blue-500 rounded-full" />;
      case 'model':
        return <div className="w-2 h-2 bg-green-500 rounded-full" />;
      case 'system':
        return <div className="w-2 h-2 bg-gray-500 rounded-full" />;
      case 'error':
        return <XCircle className="w-4 h-4 text-red-500" />;
      case 'progress':
        return <Activity className="w-4 h-4 text-yellow-500" />;
      default:
        return <div className="w-2 h-2 bg-gray-400 rounded-full" />;
    }
  };

  const formatTimestamp = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  const filteredEntries = showDebugLogs
    ? entries
    : entries.filter(entry => !['system', 'progress'].includes(entry.type));

  return (
    <div className="border-t bg-gray-50">
      <div className="flex items-center justify-between p-3 border-b">
        <div className="flex items-center space-x-2">
          <Activity className="w-4 h-4 text-gray-600" />
          <span className="text-sm font-medium text-gray-700">Debug Log</span>
          <span className="text-xs text-gray-500">({filteredEntries.length} entries)</span>
        </div>
        <div className="flex items-center space-x-2">
          <button
            onClick={onToggleDebugLogs}
            className={`px-2 py-1 text-xs rounded transition-colors ${
              showDebugLogs
                ? 'bg-blue-100 text-blue-700'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {showDebugLogs ? 'Hide Debug' : 'Show Debug'}
          </button>
        </div>
      </div>

      <div className="max-h-64 overflow-y-auto">
        {filteredEntries.length === 0 ? (
          <div className="p-4 text-center text-gray-500 text-sm">
            No entries to display
          </div>
        ) : (
          <div className="divide-y divide-gray-200">
            {filteredEntries.map((entry) => (
              <div key={entry.id} className="p-3 hover:bg-gray-100 transition-colors">
                <div className="flex items-start space-x-2">
                  <div className="mt-1">
                    {getEntryIcon(entry.type)}
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center space-x-2 mb-1">
                      <span className="text-xs text-gray-500">
                        {formatTimestamp(entry.timestamp)}
                      </span>
                      {entry.traceId && (
                        <span className="text-xs text-blue-600 font-mono">
                          {entry.traceId.slice(0, 8)}
                        </span>
                      )}
                      <button
                        onClick={() => onCopyEntry(entry)}
                        className="text-xs text-gray-400 hover:text-gray-600"
                        title="Copy entry"
                      >
                        {copiedId === entry.id ? (
                          <CheckCircle2 className="w-3 h-3" />
                        ) : (
                          <Copy className="w-3 h-3" />
                        )}
                      </button>
                    </div>
                    
                    <div className="text-sm text-gray-900 break-words">
                      {entry.text}
                    </div>
                    
                    {(entry.metadata || entry.instanceId) && (
                      <div className="mt-2">
                        <button
                          onClick={() => toggleExpanded(entry.id)}
                          className="flex items-center space-x-1 text-xs text-gray-500 hover:text-gray-700"
                        >
                          {expandedEntries.has(entry.id) ? (
                            <ChevronDown className="w-3 h-3" />
                          ) : (
                            <ChevronRight className="w-3 h-3" />
                          )}
                          <span>Details</span>
                        </button>
                        
                        {expandedEntries.has(entry.id) && (
                          <div className="mt-2 p-2 bg-gray-100 rounded text-xs">
                            {entry.instanceId && (
                              <div className="mb-1">
                                <span className="font-medium">Instance ID:</span>{' '}
                                <span className="font-mono">{entry.instanceId}</span>
                              </div>
                            )}
                            {entry.metadata && (
                              <div>
                                <span className="font-medium">Metadata:</span>
                                <pre className="mt-1 text-xs overflow-x-auto whitespace-pre-wrap">
                                  {JSON.stringify(entry.metadata, null, 2)}
                                </pre>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
