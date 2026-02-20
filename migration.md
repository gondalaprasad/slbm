# SLB Tracker Migration Guide

## Overview

This guide covers migrating the SLB Tracking Mechanism from a Flask-based local application to a cloud-hosted Next.js application with Supabase backend and user authentication.

**Current Architecture:**
```
┌─────────────┐         ┌──────────────┐
│  Flask App  │────────▶│ Local Files  │
│  (Python)   │         │  (Excel)     │
└─────────────┘         └──────────────┘
     :5000
```

**Target Architecture:**
```
┌──────────────┐         ┌──────────────┐
│   Next.js    │────────▶│  Supabase    │
│  (React/SSR) │         │ (PostgreSQL) │
└──────────────┘         └──────────────┘
     Netlify                      :
              :                ┌────┴─────┐
              └───────────────▶│ Supabase │
                              │   Auth   │
                              └──────────┘
```

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Supabase Setup](#supabase-setup)
3. [Next.js Project Setup](#nextjs-project-setup)
4. [Authentication Implementation](#authentication-implementation)
5. [API Routes Creation](#api-routes-creation)
6. [Dashboard Migration](#dashboard-migration)
7. [Data Scraper Migration](#data-scraper-migration)
8. [Deployment to Netlify](#deployment-to-netlify)
9. [Environment Variables](#environment-variables)
10. [Testing Checklist](#testing-checklist)

---

## Prerequisites

### Required Accounts
- [Supabase Account](https://supabase.com) (Free tier available)
- [GitHub Account](https://github.com) (for Netlify deployment)
- [Netlify Account](https://netlify.com) (Free tier available)

### Required Tools
```bash
# Node.js (v18+)
node --version

# Git
git --version

# Netlify CLI (optional)
npm install -g netlify-cli
```

---

## Supabase Setup

### 1. Create Project

1. Go to [supabase.com](https://supabase.com)
2. Click **"New Project"**
3. Configure:
   - **Name**: `slb-tracker`
   - **Database Password**: Generate strong password (save it!)
   - **Region**: Choose closest to your users
4. Click **"Create new project**
5. Wait for project provisioning (~2 minutes)

### 2. Create Database Tables

Go to **SQL Editor** in Supabase dashboard and run:

```sql
-- =====================================================
-- 1. PROFILES TABLE (extends Supabase Auth)
-- =====================================================
CREATE TABLE profiles (
    id UUID REFERENCES auth.users PRIMARY KEY,
    email TEXT,
    full_name TEXT,
    avatar_url TEXT,
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- 2. SLB DATA TABLE (main data storage)
-- =====================================================
CREATE TABLE slb_data (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    series TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    time_short TEXT,
    bid_price NUMERIC(10, 2),
    ask_price NUMERIC(10, 2),
    spread NUMERIC(10, 2),
    ltp NUMERIC(10, 2),
    annualised_yield NUMERIC(10, 2),
    volume BIGINT,
    turnover NUMERIC(20, 2),
    expiry TEXT,
    ca TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- 3. METADATA TABLE (series A & B options)
-- =====================================================
CREATE TABLE slb_metadata (
    id BIGSERIAL PRIMARY KEY,
    type TEXT NOT NULL, -- 'series_a' or 'series_b'
    value TEXT NOT NULL,
    text TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(type, value)
);

-- =====================================================
-- 4. USER CONFIGS TABLE (user preferences)
-- =====================================================
CREATE TABLE user_configs (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id)
);

-- =====================================================
-- 5. INDEXES FOR PERFORMANCE
-- =====================================================
CREATE INDEX idx_slb_data_symbol_series ON slb_data(symbol, series);
CREATE INDEX idx_slb_data_timestamp ON slb_data(timestamp DESC);
CREATE INDEX idx_slb_data_symbol_timestamp ON slb_data(symbol, timestamp DESC);
CREATE INDEX idx_slb_data_series_timestamp ON slb_data(series, timestamp DESC);

-- =====================================================
-- 6. ROW LEVEL SECURITY (RLS)
-- =====================================================
ALTER TABLE slb_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE slb_metadata ENABLE ROW LEVEL SECURITY;

-- Public read access for SLB data
CREATE POLICY "Public read access for SLB data"
    ON slb_data FOR SELECT
    USING (true);

-- Public read access for metadata
CREATE POLICY "Public read access for metadata"
    ON slb_metadata FOR SELECT
    USING (true);

-- Users can read own profile
CREATE POLICY "Users can read own profile"
    ON profiles FOR SELECT
    USING (auth.uid() = id);

-- Users can update own profile
CREATE POLICY "Users can update own profile"
    ON profiles FOR UPDATE
    USING (auth.uid() = id);

-- Users can read own config
CREATE POLICY "Users can read own config"
    ON user_configs FOR SELECT
    USING (auth.uid() = user_id);

-- Users can insert own config
CREATE POLICY "Users can insert own config"
    ON user_configs FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can update own config
CREATE POLICY "Users can update own config"
    ON user_configs FOR UPDATE
    USING (auth.uid() = user_id);

-- =====================================================
-- 7. FUNCTIONS & TRIGGERS
-- =====================================================
-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_profiles_updated_at BEFORE UPDATE ON profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_configs_updated_at BEFORE UPDATE ON user_configs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- 8. RANKINGS FUNCTION
-- =====================================================
CREATE OR REPLACE FUNCTION get_latest_rankings(series_param TEXT)
RETURNS TABLE (
    symbol TEXT,
    bid_price NUMERIC,
    ltp NUMERIC,
    earning_pct NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        sub.symbol,
        sub.bid_price,
        sub.ltp,
        ROUND((sub.bid_price / sub.ltp * 100)::numeric, 2) as earning_pct
    FROM (
        SELECT DISTINCT ON (d.symbol)
            d.symbol,
            d.bid_price,
            d.ltp
        FROM slb_data d
        WHERE d.series = series_param
            AND d.bid_price IS NOT NULL
            AND d.ltp IS NOT NULL
            AND d.ltp > 0
        ORDER BY d.symbol, d.timestamp DESC
    ) sub
    ORDER BY earning_pct DESC
    LIMIT 10;
END;
$$ LANGUAGE plpgsql;
```

### 3. Get Supabase Credentials

1. Go to **Project Settings** → **API**
2. Copy these values:
   - `Project URL`
   - `anon public` key
   - `service_role` key (keep secret!)

---

## Next.js Project Setup

### 1. Create Project

```bash
# Create Next.js app with TypeScript
npx create-next-app@latest slb-tracker --typescript --tailwind --app --src-dir --import-alias "@/*"

cd slb-tracker

# Install dependencies
npm install @supabase/supabase-js \
            @supabase/auth-helpers-nextjs \
            @supabase/auth-ui-react \
            @supabase/auth-ui-shared

# Chart libraries
npm install chart.js \
            react-chartjs-2 \
            chartjs-plugin-datalabels

# Additional utilities
npm install date-fns \
            zustand \
            react-hook-form \
            zod
```

### 2. Project Structure

```
slb-tracker/
├── src/
│   ├── app/
│   │   ├── (auth)/
│   │   │   ├── login/
│   │   │   └── signup/
│   │   ├── (dashboard)/
│   │   │   ├── dashboard/
│   │   │   └── config/
│   │   ├── api/
│   │   │   ├── slb-data/
│   │   │   ├── metadata/
│   │   │   ├── rankings/
│   │   │   └── ltp/
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── components/
│   │   ├── charts/
│   │   ├── tables/
│   │   ├── ui/
│   │   └── auth/
│   ├── lib/
│   │   ├── supabase.ts
│   │   └── utils.ts
│   ├── hooks/
│   ├── store/
│   └── types/
├── public/
├── .env.local
└── middleware.ts
```

### 3. Environment Variables

Create `.env.local`:

```env
# Supabase
NEXT_PUBLIC_SUPABASE_URL=your_project_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# App
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

---

## Authentication Implementation

### 1. Supabase Client Setup

`src/lib/supabase.ts`:
```typescript
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

export const supabaseAdmin = createClient(
  supabaseUrl,
  process.env.SUPABASE_SERVICE_ROLE_KEY!,
  { auth: { persistSession: false } }
)
```

### 2. Server-Side Auth Helper

`src/lib/supabase-server.ts`:
```typescript
import { createServerComponentClient } from '@supabase/auth-helpers-nextjs'
import { cookies } from 'next/headers'

export function createClient() {
  const cookieStore = cookies()
  return createServerComponentClient<Database>({
    cookies: () => cookieStore
  })
}
```

### 3. Middleware for Auth Protection

`middleware.ts` (root level):
```typescript
import { createMiddlewareClient } from '@supabase/auth-helpers-nextjs'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export async function middleware(req: NextRequest) {
  const res = NextResponse.next()
  const supabase = createMiddlewareClient({ req, res })

  const {
    data: { session }
  } = await supabase.auth.getSession()

  // Protected routes
  const protectedPaths = ['/dashboard', '/config']
  const isProtectedPath = protectedPaths.some(path =>
    req.nextUrl.pathname.startsWith(path)
  )

  if (isProtectedPath && !session) {
    return NextResponse.redirect(
      new URL('/login', req.url)
    )
  }

  // Redirect authenticated users away from auth pages
  if (session && req.nextUrl.pathname.startsWith('/login')) {
    return NextResponse.redirect(new URL('/dashboard', req.url))
  }

  return res
}

export const config = {
  matcher: ['/dashboard/:path*', '/config/:path*', '/login']
}
```

### 4. Login Page

`src/app/login/page.tsx`:
```typescript
'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password
    })

    if (error) {
      setError(error.message)
    } else {
      router.push('/dashboard')
      router.refresh()
    }
    setLoading(false)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white p-8 rounded-lg shadow-md w-96">
        <h1 className="text-2xl font-bold mb-6 text-center">SLB Tracker</h1>

        {error && (
          <div className="bg-red-50 text-red-500 p-3 rounded mb-4 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full p-3 border rounded-lg"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full p-3 border rounded-lg"
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white p-3 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          Don't have an account?{' '}
          <a href="/signup" className="text-blue-600 hover:underline">
            Sign up
          </a>
        </p>
      </div>
    </div>
  )
}
```

### 5. Signup Page

`src/app/signup/page.tsx`:
```typescript
'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

export default function SignupPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    setMessage('')

    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { full_name: fullName }
      }
    })

    if (error) {
      setError(error.message)
    } else {
      setMessage('Check your email for the confirmation link!')
      // Create profile
      if (data.user) {
        await supabase.from('profiles').insert({
          id: data.user.id,
          email: data.user.email,
          full_name: fullName
        })
      }
    }
    setLoading(false)
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white p-8 rounded-lg shadow-md w-96">
        <h1 className="text-2xl font-bold mb-6 text-center">Create Account</h1>

        {error && (
          <div className="bg-red-50 text-red-500 p-3 rounded mb-4 text-sm">
            {error}
          </div>
        )}

        {message && (
          <div className="bg-green-50 text-green-600 p-3 rounded mb-4 text-sm">
            {message}
          </div>
        )}

        <form onSubmit={handleSignup} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">Full Name</label>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full p-3 border rounded-lg"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full p-3 border rounded-lg"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full p-3 border rounded-lg"
              minLength={6}
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white p-3 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Creating account...' : 'Sign Up'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          Already have an account?{' '}
          <a href="/login" className="text-blue-600 hover:underline">
            Sign in
          </a>
        </p>
      </div>
    </div>
  )
}
```

---

## API Routes Creation

### 1. SLB Data API

`src/app/api/slb-data/route.ts`:
```typescript
import { NextRequest, NextResponse } from 'next/server'
import { supabase } from '@/lib/supabase'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const symbol = searchParams.get('symbol')
    const series = searchParams.get('series')

    let query = supabase
      .from('slb_data')
      .select('*')
      .order('timestamp', { ascending: true })

    if (symbol) query = query.eq('symbol', symbol)
    if (series) query = query.eq('series', series)

    const { data, error } = await query

    if (error) {
      return NextResponse.json(
        { error: error.message },
        { status: 500 }
      )
    }

    return NextResponse.json({ data })
  } catch (error) {
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}
```

### 2. Metadata API

`src/app/api/metadata/route.ts`:
```typescript
import { NextResponse } from 'next/server'
import { supabase } from '@/lib/supabase'

export async function GET() {
  try {
    // Get unique symbols
    const { data: symbolsData } = await supabase
      .from('slb_data')
      .select('symbol')

    // Get series from metadata
    const { data: seriesData } = await supabase
      .from('slb_metadata')
      .select('*')
      .eq('type', 'series_b')

    const symbols = [...new Set(symbolsData?.map(d => d.symbol) || [])]
      .sort()

    const series = seriesData?.map(d => d.text) || []

    return NextResponse.json({
      symbols,
      series,
      latest_expiry: 'N/A'
    })
  } catch (error) {
    return NextResponse.json({ error: 'Failed to fetch metadata' }, { status: 500 })
  }
}
```

### 3. Rankings API

`src/app/api/rankings/route.ts`:
```typescript
import { NextRequest, NextResponse } from 'next/server'
import { supabase } from '@/lib/supabase'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const series = searchParams.get('series')

    if (!series) {
      return NextResponse.json({ rankings: [] })
    }

    // Get latest data for each symbol in the series
    const { data, error } = await supabase.rpc('get_latest_rankings', {
      series_param: series
    })

    if (error) {
      console.error('Rankings error:', error)
      return NextResponse.json({ rankings: [] })
    }

    return NextResponse.json({ rankings: data || [] })
  } catch (error) {
    console.error('Rankings API error:', error)
    return NextResponse.json({ rankings: [] })
  }
}
```

---

## Dashboard Migration

### 1. Dashboard Component Structure

`src/app/dashboard/page.tsx`:
```typescript
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase-server'
import Dashboard from '@/components/dashboard/Dashboard'

export default async function DashboardPage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()

  if (!session) {
    redirect('/login')
  }

  return <Dashboard user={session.user} />
}
```

### 2. Key Components to Migrate

| Original File | New Component |
|--------------|--------------|
| `templates/dashboard.html` | `components/dashboard/Dashboard.tsx` |
| `templates/config.html` | `components/dashboard/Config.tsx` |
| HTML Charts | `components/charts/PriceChart.tsx` |
| HTML Tables | `components/tables/RankingsTable.tsx` |

---

## Data Scraper Migration

The Python scraper (`slb_pw.py`) needs to be converted to push data to Supabase.

### Option A: Deploy as Serverless Function

1. Convert to use REST API calls instead of Playwright
2. Deploy as Vercel/Netlify Function

### Option B: Keep Python Backend

1. Deploy to Railway, Render, or AWS Lambda
2. Use cron jobs for scheduled execution
3. Push data to Supabase via REST API

`scraper_to_supabase.py`:
```python
import os
from supabase import create_client, Client
from datetime import datetime
import pandas as pd

# Initialize Supabase
supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_SERVICE_KEY")
)

def push_to_supabase(df: pd.DataFrame):
    """Push DataFrame to Supabase"""
    data = df.to_dict('records')

    # Convert to Supabase format
    records = []
    for row in data:
        records.append({
            "symbol": row.get("Symbol"),
            "series": row.get("Series"),
            "timestamp": row.get("Timestamp"),
            "time_short": row.get("Time_Short"),
            "bid_price": row.get("Best Bid Price"),
            "ask_price": row.get("Best Offer Price"),
            "spread": row.get("Spread"),
            "ltp": row.get("LTP"),
            "annualised_yield": row.get("Annualised Yield"),
            "volume": row.get("Volume"),
            "turnover": row.get("Turnover"),
            "expiry": row.get("Expiry"),
            "ca": row.get("CA")
        })

    # Insert in batches
    batch_size = 100
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        supabase.table("slb_data").insert(batch).execute()

    print(f"Inserted {len(records)} records to Supabase")
```

---

## Deployment to Netlify

### 1. Build Configuration

`netlify.toml`:
```toml
[build]
  command = "npm run build"
  publish = ".next"

[functions]
  node_bundler = "esbuild"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200

[environment]
  NEXT_PUBLIC_SITE_URL = "https://your-site.netlify.app"
```

### 2. Deploy via Git

```bash
# Initialize git if not already
git init
git add .
git commit -m "Initial commit"

# Push to GitHub
gh repo create slb-tracker --public --source=.
git push -u origin main
```

Then in Netlify:
1. **"Add new site"** → **"Import an existing project"**
2. Connect to GitHub
3. Select `slb-tracker` repository
4. Configure:
   - **Build command**: `npm run build`
   - **Publish directory**: `.next`
5. Add environment variables in Netlify dashboard
6. **Deploy site**

### 3. Environment Variables in Netlify

Go to **Site Settings** → **Environment Variables**:

```
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

---

## Testing Checklist

- [ ] User can sign up with email
- [ ] Email confirmation works
- [ ] User can log in
- [ ] Dashboard loads with data
- [ ] Symbol/Series filters work
- [ ] Chart displays correctly
- [ ] Rankings table shows data
- [ ] Theme toggle works
- [ ] Config saves to database
- [ ] Data updates from scraper
- [ ] Mobile responsive

---

## Cost Estimation

| Service | Free Tier | Paid Tier |
|---------|-----------|-----------|
| **Supabase** | 500MB DB, 1GB bandwidth | $25/month for Pro |
| **Netlify** | 100GB bandwidth, 300min build | $19/month for Pro |
| **Total (Free)** | ✅ Sufficient for MVP | |
| **Total (Paid)** | | ~$44/month |

---

## Troubleshooting

### Common Issues

1. **CORS Errors**:
   - Add your Netlify domain to Supabase allowed origins

2. **Auth Not Persisting**:
   - Check `NEXT_PUBLIC_SUPABASE_URL` is correct
   - Ensure cookies are enabled

3. **Build Failures**:
   - Check Node version matches Netlify
   - Verify all environment variables are set

4. **Database Connection**:
   - Verify RLS policies allow public reads
   - Check `service_role` key is not exposed client-side

---

## Additional Resources

- [Supabase Docs](https://supabase.com/docs)
- [Next.js Docs](https://nextjs.org/docs)
- [Netlify Docs](https://docs.netlify.com)
- [Chart.js Docs](https://www.chartjs.org/docs/)
