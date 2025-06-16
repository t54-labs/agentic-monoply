// API Configuration for Frontend
// Manages backend URL configuration for different environments

// Get environment variables with fallback defaults
const getApiBaseUrl = (): string => {
  // In production (Vercel), use environment variable
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  
  // Development fallback
  return 'http://localhost:8000';
};

const getWsBaseUrl = (): string => {
  // In production (Vercel), use environment variable
  if (process.env.NEXT_PUBLIC_WS_BASE_URL) {
    return process.env.NEXT_PUBLIC_WS_BASE_URL;
  }
  
  // Development fallback
  return 'ws://localhost:8000';
};

// Utility function to safely join URL parts
const joinUrl = (baseUrl: string, endpoint: string): string => {
  // Remove trailing slash from base URL
  const cleanBase = baseUrl.replace(/\/$/, '');
  // Ensure endpoint starts with slash
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${cleanBase}${cleanEndpoint}`;
};

// Export configuration
export const API_CONFIG = {
  BASE_URL: getApiBaseUrl(),
  WS_BASE_URL: getWsBaseUrl(),
  
  // API Endpoints
  ENDPOINTS: {
    LOBBY_GAMES: '/api/lobby/games',
    GAME_BOARD: (gameId: string) => `/api/game/${gameId}/board_layout`,
  },
  
  // WebSocket Endpoints
  WS_ENDPOINTS: {
    LOBBY: '/ws/lobby',
    GAME: (gameId: string) => `/ws/game/${gameId}`,
  }
};

// Helper functions with proper URL joining
export const getApiUrl = (endpoint: string): string => {
  return joinUrl(API_CONFIG.BASE_URL, endpoint);
};

export const getWsUrl = (endpoint: string): string => {
  return joinUrl(API_CONFIG.WS_BASE_URL, endpoint);
};

// Debug log (only in development)
if (process.env.NODE_ENV === 'development') {
  console.log('🔧 API Configuration:', {
    API_BASE_URL: API_CONFIG.BASE_URL,
    WS_BASE_URL: API_CONFIG.WS_BASE_URL,
    NODE_ENV: process.env.NODE_ENV,
    SAMPLE_API_URL: getApiUrl('/api/lobby/games'),
    SAMPLE_WS_URL: getWsUrl('/ws/lobby'),
  });
} 