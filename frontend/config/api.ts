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

// Helper functions
export const getApiUrl = (endpoint: string): string => {
  return `${API_CONFIG.BASE_URL}${endpoint}`;
};

export const getWsUrl = (endpoint: string): string => {
  return `${API_CONFIG.WS_BASE_URL}${endpoint}`;
};

// Debug log (only in development)
if (process.env.NODE_ENV === 'development') {
  console.log('🔧 API Configuration:', {
    API_BASE_URL: API_CONFIG.BASE_URL,
    WS_BASE_URL: API_CONFIG.WS_BASE_URL,
    NODE_ENV: process.env.NODE_ENV,
  });
} 