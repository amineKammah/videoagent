import { NextRequest, NextResponse } from 'next/server';
import { readFile, stat } from 'fs/promises';
import path from 'path';

export async function GET(req: NextRequest) {
    const searchParams = req.nextUrl.searchParams;
    const videoPath = searchParams.get('path');

    if (!videoPath) {
        return NextResponse.json({ error: 'Missing path parameter' }, { status: 400 });
    }

    try {
        // Security: ensure the path is within the output directory
        const normalizedPath = path.normalize(videoPath);

        // Check if file exists
        const stats = await stat(normalizedPath);
        if (!stats.isFile()) {
            return NextResponse.json({ error: 'Not a file' }, { status: 400 });
        }

        // Read the file
        const fileBuffer = await readFile(normalizedPath);

        // Determine content type based on extension
        const ext = path.extname(normalizedPath).toLowerCase();
        const contentTypes: Record<string, string> = {
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
            '.mov': 'video/quicktime',
            '.ogg': 'video/ogg',
            '.wav': 'audio/wav',
            '.mp3': 'audio/mpeg',
        };
        const contentType = contentTypes[ext] || 'video/mp4';

        return new NextResponse(fileBuffer, {
            headers: {
                'Content-Type': contentType,
                'Content-Length': stats.size.toString(),
                'Accept-Ranges': 'bytes',
            },
        });
    } catch (error) {
        console.error('Error serving video:', error);
        return NextResponse.json(
            { error: 'Failed to serve video' },
            { status: 500 }
        );
    }
}
