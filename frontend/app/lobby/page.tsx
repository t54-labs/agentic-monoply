'use client';

import React, { useEffect, useState, useRef } from 'react';
import GameTableCard from '../components/GameTableCard'; // Adjusted path
import { getApiUrl, getWsUrl, API_CONFIG } from '../../config/api'; // Import API configuration
// import Link from 'next/link'; // Link for Home button removed

interface PlayerInfo {
  id: number;
  name: string;
  is_ai: boolean;
  is_bankrupt: boolean;
}

interface GameData {
  game_uid: string;
  status: string;
  current_players_count: number;
  max_players: number;
  players: PlayerInfo[];
  turn_count?: number;
}

// Layout configuration
const ESTIMATED_TOTAL_SLOTS = 40; 

// Function to generate fallback game data
const generateFallbackGames = (count: number): GameData[] => {
  const fallbacks: GameData[] = [];
  const playerBaseNames = ["Red", "Blu", "Grn", "Yel", "Pur", "Org", "Cyan", "Lime"]; 
  const gameBaseNames = ["Cosmic", "Galaxy", "Stellar", "Nova", "Quantum", "Nebula", "Orion", "Alpha", "Beta", "Gamma"];
  const statuses = ['in_progress', 'waiting_for_players', 'in_progress'];

  for (let i = 0; i < count; i++) {
    const maxPlayers = Math.floor(Math.random() * 5) + 4; // Random number between 4 and 8 (inclusive)
    // Ensure current players is between 4 and maxPlayers for fallback tables
    const currentPlayersCount = Math.floor(Math.random() * (maxPlayers - 4 + 1)) + 4; 
    
    const players: PlayerInfo[] = [];
    for (let j = 0; j < currentPlayersCount; j++) {
      players.push({
        id: j, 
        name: `${playerBaseNames[j % playerBaseNames.length]}${(Math.random() > 0.5 ? 'Bot' : 'Dude')}`,
        is_ai: true, 
        is_bankrupt: Math.random() < 0.05, // ~5% chance of being bankrupt for visual testing
      });
    }
    const gameStatus = statuses[i % statuses.length];
    fallbacks.push({
      game_uid: `fake-${gameBaseNames[i % gameBaseNames.length].toLowerCase().slice(0,3)}-${Math.floor(Math.random() * 10000)}`,
      status: gameStatus,
      current_players_count: currentPlayersCount,
      max_players: maxPlayers,
      players: players,
      turn_count: gameStatus === 'in_progress' ? Math.floor(Math.random() * 30) + 1 : 0,
    });
  }
  return fallbacks;
};

const LobbyPage: React.FC = () => {
  const [games, setGames] = useState<GameData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const fetchGames = async () => {
      setIsLoading(true);
      try {
        // Use API configuration instead of hardcoded URL
        const apiUrl = getApiUrl(API_CONFIG.ENDPOINTS.LOBBY_GAMES);
        console.log('🌐 Fetching games from:', apiUrl);
        
        const response = await fetch(apiUrl);
        if (!response.ok) {
          const errorMsg = `API Error: ${response.status}`;
          console.error(errorMsg);
          setGames(generateFallbackGames(5)); 
          return; 
        }
        const data = await response.json();
        if (data && data.length > 0) {
          setGames(data);
        } else {
          console.log("API returned no games, showing fallback.");
          setGames(generateFallbackGames(5)); 
        }
      } catch (e: unknown) {
        console.error("Failed to fetch games (catch block):", e);
        const errorMsg = e instanceof Error ? e.message : "Failed to load games.";
        console.error(errorMsg);
        setGames(generateFallbackGames(5)); 
      } finally {
        setIsLoading(false);
      }
    };

    fetchGames();

    // Use WebSocket configuration instead of hardcoded URL
    const wsUrl = getWsUrl(API_CONFIG.WS_ENDPOINTS.LOBBY);
    console.log('🔌 Connecting to WebSocket:', wsUrl);
    
    socketRef.current = new WebSocket(wsUrl);

    socketRef.current.onopen = () => {
      console.log("✅ Lobby WebSocket connected to:", wsUrl);
    };

    socketRef.current.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data as string);
        console.log("📨 Lobby WebSocket message received:", message);

        if (message.type === 'game_added') {
          setGames(prevGames => {
            const isPrevFallback = prevGames.length > 0 && prevGames.every(g => g.game_uid.startsWith('fake-'));
            if (isPrevFallback) return [message.data];

            if (prevGames.find(g => g.game_uid === message.data.game_uid)) {
              return prevGames.map(g => g.game_uid === message.data.game_uid ? message.data : g);
            }
            return [...prevGames, message.data];
          });
        } else if (message.type === 'game_status_update') {
          setGames(prevGames => 
            prevGames.map(game => 
              game.game_uid === message.data.game_uid 
                ? { ...game, ...message.data } 
                : game
            )
          );
        } else if (message.type === 'game_removed') { 
            setGames(prevGames => prevGames.filter(game => game.game_uid !== message.data.game_uid));
        }

      } catch (e) {
        console.error("❌ Error processing lobby WebSocket message:", e, event.data);
      }
    };

    socketRef.current.onclose = () => {
      console.log("🔌 Lobby WebSocket disconnected");
    };

    socketRef.current.onerror = (err) => {
      console.error("❌ Lobby WebSocket error:", err);
    };

    return () => {
      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, []); 

  if (isLoading) {
    return <div style={styles.centeredMessage}>loading</div>;
  }

  const tablesToRender = [];
  const totalGames = games.length;
  const displaySlots = Math.max(totalGames, ESTIMATED_TOTAL_SLOTS);
  
  for (let i = 0; i < displaySlots; i++) {
    if (i < games.length) {
      tablesToRender.push(<GameTableCard key={games[i].game_uid} game={games[i]} />);
    } else {
      tablesToRender.push(
        <GameTableCard 
          key={`empty-${i}`}
          game={{
            game_uid: `empty-slot-${i}`,
            status: 'empty',
            current_players_count: 0,
            max_players: 0,
            players: [],
            turn_count: 0
          }} 
          isEmpty={true} 
        />
      );
    }
  }

  return (
    <div style={styles.lobbyContainer}>
      <div style={styles.backgroundOverlay}></div>
      <div style={styles.tablesGrid}>
        {tablesToRender}
      </div>
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  lobbyContainer: {
    padding: '10px', // 减少padding以适应手机屏幕
    backgroundImage: 'url(/lobby_bg.png)', // 使用背景图片
    backgroundSize: 'cover', // 覆盖整个容器
    backgroundPosition: 'center', // 居中显示
    backgroundRepeat: 'no-repeat', // 不重复
    backgroundAttachment: 'fixed', // 固定背景
    minHeight: '100vh',
    fontFamily: "'Quantico', sans-serif",
    color: '#00FF00', // Default green text for lobby
    display: 'flex', // Added
    flexDirection: 'column', // Added
    position: 'relative', // 为了添加半透明遮罩层
  },
  backgroundOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.3)', // 半透明黑色遮罩
    pointerEvents: 'none', // 不阻止鼠标事件
    zIndex: 1,
  },
  tablesGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(460px, 1fr))', // 最小宽度460px，自适应变大
    gap: '20px',
    justifyItems: 'center',
    paddingTop: '10px',
    flexGrow: 1, 
    alignContent: 'flex-start', 
    width: '100%',
    maxWidth: '2380px', // 限制最大宽度：5*460px + 4*20px(gap) = 2380px，确保最多5列
    margin: '0 auto', // 居中显示
    boxSizing: 'border-box',
    position: 'relative',
    zIndex: 2,
  },
  centeredMessage: { // For loading message
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    minHeight: 'calc(100vh - 40px)', // Adjusted for padding
    fontSize: '22px', // Larger font
    fontWeight: 'bold',
    color: '#00FF00', // Green text
    fontFamily: "'Quantico', sans-serif",
    textAlign: 'center',
  },
  errorMessage: { // New style for compact error message at the top
    textAlign: 'center',
    color: '#FF6347', // Tomato Red
    fontSize: '18px',
    fontWeight: 'bold',
    fontFamily: "'Quantico', sans-serif",
    padding: '10px 0 20px 0', // Padding around the error message
    flexShrink: 0, // Prevent error message from shrinking if lobbyContainer is flex column
  },
   // homeButtonContainer and homeButton styles removed
};

export default LobbyPage; 