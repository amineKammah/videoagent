import { NextRequest } from 'next/server';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function POST(req: NextRequest) {
    try {
        const { messages, sessionId } = await req.json();

        // Get the last user message
        const lastMessage = messages[messages.length - 1];
        if (!lastMessage || lastMessage.role !== 'user') {
            return new Response('No user message found', { status: 400 });
        }

        // Call FastAPI backend
        const response = await fetch(`${API_BASE}/agent/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                message: lastMessage.content,
            }),
        });

        if (!response.ok) {
            const error = await response.text();
            return new Response(error, { status: response.status });
        }

        const data = await response.json();

        // Create a streaming response using the AI SDK format
        // Even though our backend isn't streaming, we format it for useChat compatibility
        const encoder = new TextEncoder();

        const stream = new ReadableStream({
            start(controller) {
                // Send the text response
                const textChunk = `0:${JSON.stringify(data.message)}\n`;
                controller.enqueue(encoder.encode(textChunk));

                // Send metadata (scenes, customer_details) as data
                if (data.scenes || data.customer_details) {
                    const metadata = {
                        scenes: data.scenes,
                        customer_details: data.customer_details,
                    };
                    const dataChunk = `2:${JSON.stringify([metadata])}\n`;
                    controller.enqueue(encoder.encode(dataChunk));
                }

                // Signal completion
                const finishChunk = `d:{"finishReason":"stop"}\n`;
                controller.enqueue(encoder.encode(finishChunk));

                controller.close();
            },
        });

        return new Response(stream, {
            headers: {
                'Content-Type': 'text/plain; charset=utf-8',
                'X-Vercel-AI-Data-Stream': 'v1',
            },
        });
    } catch (error) {
        console.error('Chat API error:', error);
        return new Response(
            error instanceof Error ? error.message : 'Internal server error',
            { status: 500 }
        );
    }
}
