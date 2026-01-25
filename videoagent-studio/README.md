# VideoAgent Studio (Frontend)

The frontend interface for the VideoAgent, built with Next.js and React.

## Prerequisites

- Node.js (v18 or higher recommended)
- The VideoAgent Backend running (default: http://localhost:8000)

## Installation

1. Navigate to the studio directory:
   ```bash
   cd videoagent-studio
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

## Configuration

By default, the frontend connects to the backend at `http://localhost:8000`.
To change this, create a `.env.local` file in this directory:

```bash
NEXT_PUBLIC_API_URL=http://your-backend-url:port
```

## Running

Start the development server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.
