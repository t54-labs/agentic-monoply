# 🚀 Frontend Deployment Guide

## 📋 Environment Variables Configuration

This frontend is designed to work with different backend environments through environment variables.

### 🔧 Local Development Setup

1. **Create `.env.local` file** in the frontend root directory:
   ```bash
   # Local Development Configuration
   NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
   NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000
   ```

2. **Start your local backend server** on port 8000
3. **Run frontend development server**:
   ```bash
   npm run dev
   ```

### 🌐 Production Deployment (Vercel)

#### 1. Deploy to Vercel

```bash
# Option 1: Using Vercel CLI
npm install -g vercel
vercel

# Option 2: Connect GitHub repo to Vercel Dashboard
# Visit https://vercel.com/dashboard
# Import your GitHub repository
```

#### 2. Configure Environment Variables in Vercel

In your Vercel project dashboard:

1. Go to **Settings** → **Environment Variables**
2. Add the following variables:

```bash
# Production Configuration
NEXT_PUBLIC_API_BASE_URL=https://your-heroku-app.herokuapp.com
NEXT_PUBLIC_WS_BASE_URL=wss://your-heroku-app.herokuapp.com
```

**Important Notes:**
- ✅ Use `https://` for API calls (Heroku provides HTTPS automatically)
- ✅ Use `wss://` for WebSocket connections (secure WebSocket)
- ⚠️ Replace `your-heroku-app` with your actual Heroku app name

#### 3. Deploy and Test

After setting environment variables:
1. Trigger a new deployment in Vercel
2. Test the deployed frontend with your Heroku backend

### 🔐 HTTPS & WSS Configuration

#### Heroku Backend HTTPS Setup

**Good News:** Heroku automatically provides HTTPS for all apps! 🎉

- **HTTP URL**: `http://your-app.herokuapp.com` (redirects to HTTPS)
- **HTTPS URL**: `https://your-app.herokuapp.com` ✅
- **WebSocket WS**: `ws://your-app.herokuapp.com/ws/...` 
- **WebSocket WSS**: `wss://your-app.herokuapp.com/ws/...` ✅

**No additional configuration needed** - Heroku handles SSL certificates automatically.

#### Frontend Configuration

The frontend automatically uses the correct protocol based on environment variables:

**Local Development:**
```javascript
// config/api.ts automatically detects:
API_BASE_URL: 'http://localhost:8000'     // HTTP for local
WS_BASE_URL: 'ws://localhost:8000'        // WS for local
```

**Production (Vercel + Heroku):**
```javascript
// Environment variables in Vercel:
API_BASE_URL: 'https://your-app.herokuapp.com'  // HTTPS for production
WS_BASE_URL: 'wss://your-app.herokuapp.com'     // WSS for production
```

### 🛠️ Technical Implementation

The frontend uses a centralized configuration system:

```typescript
// config/api.ts
export const API_CONFIG = {
  BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
  WS_BASE_URL: process.env.NEXT_PUBLIC_WS_BASE_URL || 'ws://localhost:8000',
  // ... endpoints
};
```

**Usage in components:**
```typescript
import { getApiUrl, getWsUrl, API_CONFIG } from '../config/api';

// API calls
const response = await fetch(getApiUrl('/api/lobby/games'));

// WebSocket connections
const ws = new WebSocket(getWsUrl('/ws/lobby'));
```

### 🧪 Testing Different Environments

#### Test Local Backend from Deployed Frontend

1. **Temporarily** set Vercel environment variables to your local machine:
   ```bash
   NEXT_PUBLIC_API_BASE_URL=http://your-local-ip:8000
   NEXT_PUBLIC_WS_BASE_URL=ws://your-local-ip:8000
   ```

2. **Make sure your local backend accepts external connections:**
   ```bash
   # In your backend, bind to all interfaces
   uvicorn server:app --host=0.0.0.0 --port=8000
   ```

#### Test Production Backend from Local Frontend

1. **Update your local `.env.local`:**
   ```bash
   NEXT_PUBLIC_API_BASE_URL=https://your-heroku-app.herokuapp.com
   NEXT_PUBLIC_WS_BASE_URL=wss://your-heroku-app.herokuapp.com
   ```

2. **Restart your local frontend:**
   ```bash
   npm run dev
   ```

### 🚨 Troubleshooting

#### Common Issues

1. **CORS Errors**
   - Make sure your Heroku backend allows your Vercel domain in CORS settings
   - Add your Vercel URL to the backend's allowed origins

2. **WebSocket Connection Failures**
   - Verify you're using `wss://` (not `ws://`) for production
   - Check browser developer tools for specific error messages

3. **API Not Found (404)**
   - Verify your backend is running and accessible
   - Check the exact URL in browser developer tools Network tab

4. **Environment Variables Not Working**
   - Ensure variables start with `NEXT_PUBLIC_` prefix
   - Redeploy after changing environment variables in Vercel
   - Check Vercel deployment logs for any issues

#### Debug Information

The frontend logs configuration in development mode:
```javascript
// Check browser console for:
🔧 API Configuration: {
  API_BASE_URL: "https://your-app.herokuapp.com",
  WS_BASE_URL: "wss://your-app.herokuapp.com",
  NODE_ENV: "production"
}
```

### 🎯 Quick Deployment Checklist

- [ ] Backend deployed to Heroku with HTTPS working
- [ ] Frontend environment variables configured in Vercel
- [ ] Both `NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_WS_BASE_URL` set
- [ ] HTTPS/WSS protocols used for production URLs
- [ ] CORS configured in backend for Vercel domain
- [ ] Test API calls and WebSocket connections work

---

🎮 **Once configured correctly, your frontend will seamlessly connect to your backend regardless of environment!**
