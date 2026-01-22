'use client';

import { useState, KeyboardEvent } from 'react';

interface ChatInputProps {
    onSend: (message: string) => void;
    disabled?: boolean;
    placeholder?: string;
}

export function ChatInput({ onSend, disabled = false, placeholder = 'Message the LLM...' }: ChatInputProps) {
    const [input, setInput] = useState('');

    const handleSubmit = () => {
        if (input.trim() && !disabled) {
            onSend(input.trim());
            setInput('');
        }
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
    };

    return (
        <div className="border-t border-slate-200 bg-white p-4">
            <div className="flex items-end gap-3">
                <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={placeholder}
                    disabled={disabled}
                    rows={1}
                    className="flex-1 resize-none rounded-xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm 
                     placeholder:text-slate-400 focus:border-teal-500 focus:bg-white focus:outline-none 
                     focus:ring-2 focus:ring-teal-500/20 disabled:opacity-50 disabled:cursor-not-allowed
                     transition-all duration-200"
                    style={{ minHeight: '44px', maxHeight: '120px' }}
                />
                <button
                    onClick={handleSubmit}
                    disabled={disabled || !input.trim()}
                    className="flex h-11 w-11 items-center justify-center rounded-xl bg-teal-600 text-white 
                     hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors duration-200 shadow-sm hover:shadow-md"
                >
                    <SendIcon />
                </button>
            </div>
            {disabled && (
                <p className="text-xs text-slate-400 mt-2 text-center">Processing your request...</p>
            )}
        </div>
    );
}

function SendIcon() {
    return (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-5 h-5"
        >
            <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
        </svg>
    );
}
