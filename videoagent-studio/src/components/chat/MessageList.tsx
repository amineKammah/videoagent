'use client';

import { Message } from '@/lib/types';
import { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';

interface MessageListProps {
    messages: Message[];
}

export function MessageList({ messages }: MessageListProps) {
    const bottomRef = useRef<HTMLDivElement>(null);

    // Auto-scroll to bottom when new messages arrive
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    if (messages.length === 0) {
        return (
            <div className="flex-1 flex items-center justify-center text-slate-400">
                <div className="text-center">
                    <div className="text-4xl mb-3">💬</div>
                    <p>Start a conversation with the LLM</p>
                    <p className="text-sm mt-1">Ask it to create a storyboard or match scenes</p>
                </div>
            </div>
        );
    }

    return (
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((message) => (
                <MessageItem key={message.id} message={message} />
            ))}
            <div ref={bottomRef} />
        </div>
    );
}

function MessageItem({ message }: { message: Message }) {
    const isUser = message.role === 'user';

    return (
        <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
            <div
                className={`max-w-[80%] rounded-2xl px-4 py-3 ${isUser
                        ? 'bg-teal-600 text-white rounded-br-md'
                        : 'bg-slate-100 text-slate-800 rounded-bl-md border border-slate-200'
                    }`}
            >
                {isUser ? (
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
                ) : (
                    <div className="prose prose-sm prose-slate max-w-none">
                        <ReactMarkdown
                            components={{
                                // Style overrides for markdown elements
                                p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                                ul: ({ children }) => <ul className="list-disc ml-4 mb-2">{children}</ul>,
                                ol: ({ children }) => <ol className="list-decimal ml-4 mb-2">{children}</ol>,
                                li: ({ children }) => <li className="mb-1">{children}</li>,
                                code: ({ children }) => (
                                    <code className="bg-slate-200 text-slate-800 px-1 py-0.5 rounded text-xs">
                                        {children}
                                    </code>
                                ),
                                pre: ({ children }) => (
                                    <pre className="bg-slate-800 text-slate-100 p-3 rounded-lg overflow-x-auto text-xs my-2">
                                        {children}
                                    </pre>
                                ),
                                strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                                a: ({ href, children }) => (
                                    <a href={href} className="text-teal-600 underline" target="_blank" rel="noopener noreferrer">
                                        {children}
                                    </a>
                                ),
                                h1: ({ children }) => <h1 className="text-lg font-bold mb-2">{children}</h1>,
                                h2: ({ children }) => <h2 className="text-base font-bold mb-2">{children}</h2>,
                                h3: ({ children }) => <h3 className="text-sm font-bold mb-1">{children}</h3>,
                            }}
                        >
                            {message.content}
                        </ReactMarkdown>
                    </div>
                )}
                <div
                    className={`text-xs mt-2 ${isUser ? 'text-teal-200' : 'text-slate-400'
                        }`}
                >
                    {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
            </div>
        </div>
    );
}
