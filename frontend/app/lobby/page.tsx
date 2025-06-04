'use client';

import React, { useEffect, useState, useRef } from 'react';
import GameTableCard from '../components/GameTableCard'; // Adjusted path
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

const MIN_ROWS = 10;
const TABLES_PER_ROW = 4;
const TOTAL_TABLE_SLOTS = MIN_ROWS * TABLES_PER_ROW;

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
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const fetchGames = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch('/api/lobby/games');
        if (!response.ok) {
          const errorMsg = `API Error: ${response.status}`;
          console.error(errorMsg);
          setError(errorMsg);
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
      } catch (e: any) {
        console.error("Failed to fetch games (catch block):", e);
        const errorMsg = e.message || "Failed to load games.";
        setError(errorMsg);
        setGames(generateFallbackGames(5)); 
      } finally {
        setIsLoading(false);
      }
    };

    fetchGames();

    const wsUrl = `ws://localhost:8000/ws/lobby`;
    socketRef.current = new WebSocket(wsUrl);

    socketRef.current.onopen = () => {
      console.log("Lobby WebSocket connected");
    };

    socketRef.current.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data as string);
        console.log("Lobby WebSocket message received:", message);

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
        console.error("Error processing lobby WebSocket message:", e, event.data);
      }
    };

    socketRef.current.onclose = () => {
      console.log("Lobby WebSocket disconnected");
    };

    socketRef.current.onerror = (err) => {
      console.error("Lobby WebSocket error:", err);
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
  for (let i = 0; i < TOTAL_TABLE_SLOTS; i++) {
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
      <div style={styles.tablesGrid}>
        {tablesToRender}
      </div>
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  lobbyContainer: {
    padding: '20px',
    backgroundColor: '#000000', // Black background
    minHeight: '100vh',
    fontFamily: "'Quantico', sans-serif",
    color: '#00FF00', // Default green text for lobby
    display: 'flex', // Added
    flexDirection: 'column', // Added
  },
  tablesGrid: {
    display: 'grid',
    gridTemplateColumns: `repeat(${TABLES_PER_ROW}, 1fr)`,
    gap: '20px',
    justifyItems: 'center',
    paddingTop: '20px', // Add padding if title was removed and error isn't always there
    flexGrow: 1, // Added to make grid take available space
    alignContent: 'flex-start', // Start grid items from top if grid itself is taller than content
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