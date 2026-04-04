import React, { useState, useRef, KeyboardEvent } from 'react';
import { Send, Mic, MicOff, Paperclip, Image as ImageIcon } from 'lucide-react';

interface MessageInputProps {
  onSendMessage: (text: string) => void;
  onToggleRecording: () => void;
  isRecording: boolean;
  disabled?: boolean;
  placeholder?: string;
}

export default function MessageInput({
  onSendMessage,
  onToggleRecording,
  isRecording,
  disabled = false,
  placeholder = "Type your message..."
}: MessageInputProps) {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    if (text.trim() && !disabled) {
      onSendMessage(text.trim());
      setText('');
      // Reset textarea height
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    // Auto-resize textarea
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  };

  return (
    <div className="border-t bg-white p-4">
      <div className="flex items-end space-x-2">
        <div className="flex-1">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            className="w-full resize-none rounded-lg border border-gray-300 px-3 py-2 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100"
            rows={1}
            style={{ minHeight: '40px', maxHeight: '120px' }}
          />
        </div>
        
        <div className="flex items-center space-x-1">
          <button
            onClick={() => {/* Handle file upload */}}
            disabled={disabled}
            className="p-2 text-gray-500 hover:text-gray-700 disabled:text-gray-300"
            title="Attach file"
          >
            <Paperclip className="h-5 w-5" />
          </button>
          
          <button
            onClick={() => {/* Handle image upload */}}
            disabled={disabled}
            className="p-2 text-gray-500 hover:text-gray-700 disabled:text-gray-300"
            title="Attach image"
          >
            <ImageIcon className="h-5 w-5" />
          </button>
          
          <button
            onClick={onToggleRecording}
            disabled={disabled}
            className={`p-2 rounded-lg transition-colors ${
              isRecording
                ? 'bg-red-500 text-white hover:bg-red-600'
                : 'text-gray-500 hover:text-gray-700 disabled:text-gray-300'
            }`}
            title={isRecording ? 'Stop recording' : 'Start recording'}
          >
            {isRecording ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
          </button>
          
          <button
            onClick={handleSend}
            disabled={!text.trim() || disabled}
            className="p-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            title="Send message"
          >
            <Send className="h-5 w-5" />
          </button>
        </div>
      </div>
    </div>
  );
}
