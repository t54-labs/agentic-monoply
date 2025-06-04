import Link from 'next/link';
import React from 'react';

// Define the expected shape of a player object within a game
interface PlayerInfo {
  id: number;
  name: string;
  is_ai: boolean;
  is_bankrupt: boolean;
}

// Define the expected shape of the game prop
interface GameTableCardProps {
  game: {
    game_uid: string;
    status: string; // e.g., "initializing", "in_progress", "completed", "waiting_for_players"
    current_players_count: number;
    max_players: number;
    players: PlayerInfo[];
    turn_count?: number; // Optional, might not always be relevant for all statuses
  };
  isEmpty?: boolean; // Flag to indicate if this is an empty table placeholder
}

const GameTableCard: React.FC<GameTableCardProps> = ({ game, isEmpty }) => {
  if (isEmpty) {
    return (
      <div style={styles.emptyCard}>
        <p style={styles.emptyTextLarge}>EMPTY</p>
      </div>
    );
  }

  const { game_uid, status, current_players_count, max_players, players = [], turn_count } = game;

  const renderPlayerIcons = () => {
    const icons = [];
    const actualPlayerCount = players.length;
    if (actualPlayerCount === 0 && status !== 'waiting_for_players' && !game_uid.startsWith('fake-')) {
        // Optionally show a placeholder if no players but game is active (e.g. in_progress)
        // For now, just return null if no players to render.
        return null;
    } else if (actualPlayerCount === 0 && (status === 'waiting_for_players' || game_uid.startsWith('fake-'))){
        // For waiting or fake games with 0 current players, show something like "Waiting..." or a generic icon placeholder
        // This case should ideally be handled by the fake data generator to have at least 1 player if status is waiting.
        // Or, show a clear text. For now, returning null to avoid broken icon rendering.
        return <div style={styles.noPlayersText}>Waiting for players...</div>;
    }

    const playerIconColors = ['#ff6347', '#4682b4', '#32cd32', '#ffd700', '#EE82EE', '#A52A2A', '#F08080', '#20B2AA']; 

    for (let i = 0; i < actualPlayerCount; i++) {
      const player = players[i];
      icons.push(
        <div 
          key={`player-icon-${player.id}-${game_uid}`}
          style={{
            ...styles.playerLobbyIcon,
            backgroundColor: player.is_bankrupt ? '#404040' : playerIconColors[player.id % playerIconColors.length],
          }}
          title={`${player.name} (P${player.id})${player.is_bankrupt ? ' [BANKRUPT]': ''}`}
        >
            <svg viewBox="0 0 16 16" width="80%" height="80%" fill={player.is_bankrupt ? '#777' : 'white'} xmlns="http://www.w3.org/2000/svg" style={{ display: 'block', margin: 'auto' }}>
                <rect x="6" y="2" width="4" height="2" /> 
                <rect x="5" y="4" width="6" height="2" /> 
                <rect x="4" y="6" width="8" height="6" /> 
                <rect x="2" y="12" width="12" height="2" /> 
            </svg>
        </div>
      );
    }
    return icons;
  };

  let statusDisplay = status;
  let statusColor = '#FFFF00'; // Yellow for initializing/waiting (Quantico theme)

  // Map status to English display names
  switch(status) {
    case 'in_progress':
        statusDisplay = `In Progress (Turn: ${turn_count || 1})`;
        statusColor = '#00FF00'; // Bright Green
        break;
    case 'completed':
    case 'max_turns_reached':
    case 'aborted_no_winner':
        statusDisplay = "Finished";
        statusColor = '#FF6347'; // Tomato Red
        break;
    case 'initializing':
        statusDisplay = "Initializing...";
        statusColor = '#FFFF00'; // Yellow for init
        break;
    case 'waiting_for_players':
        statusDisplay = "Waiting for Players...";
        statusColor = '#FFA500'; // Orange for waiting
        break;
    default:
        // If status is unknown, display it as is, maybe with a default color
        statusDisplay = status.replace(/_/g, ' ').toUpperCase(); // Format unknown status slightly
        statusColor = '#BBBBBB'; // Grey for unknown status
        break;
  }

  return (
    <Link href={game_uid.startsWith('fake-') ? '#' : `/game/${game_uid}`} passHref style={{ textDecoration: 'none', pointerEvents: game_uid.startsWith('fake-') ? 'none' : 'auto' }}>
      <div style={{...styles.card, opacity: game_uid.startsWith('fake-') ? 0.85 : 1}}>
        <div style={styles.gameInfoTop}>
          <h3 style={styles.gameUid}>GAME: {game_uid.startsWith('fake-') ? game_uid.slice(5,12).toUpperCase() : game_uid.slice(-6).toUpperCase()}</h3>
          <p style={{ ...styles.gameStatus, color: statusColor }}>
            {statusDisplay}
          </p>
          <p style={styles.playerCount}>
            Players: {current_players_count}/{max_players}
          </p>
        </div>
        <div style={styles.playerIconsRow}>
            {players && players.length > 0 ? renderPlayerIcons() : <div style={styles.noPlayersText}>{(status === 'waiting_for_players' || game_uid.startsWith('fake-')) && current_players_count === 0 ? "Waiting for players..." : ""}</div>}
        </div>
      </div>
    </Link>
  );
};

// Basic styles (can be moved to a CSS module or a global stylesheet)
const styles: { [key: string]: React.CSSProperties } = {
  card: {
    width: '260px', 
    height: '220px', // Increased height to accommodate player icons row better
    border: '3px solid #00FF00', 
    borderRadius: '0px', 
    backgroundColor: '#1C1C1C', 
    margin: '10px',
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'space-between', 
    alignItems: 'center',
    padding: '15px',
    boxShadow: '4px 4px 0px #008800', 
    position: 'relative', 
    cursor: 'pointer',
    color: '#00FF00', 
    fontFamily: "'Quantico', sans-serif",
  },
  emptyCard: {
    width: '260px',
    height: '220px',
    border: '3px dashed #444444', 
    borderRadius: '0px',
    backgroundColor: '#101010', 
    margin: '10px',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    color: '#555555',
    fontFamily: "'Quantico', sans-serif",
  },
  emptyTextLarge: { 
    fontSize: '28px', 
    fontWeight: 'bold',
    color: '#444444', 
    textTransform: 'uppercase',
  },
  playerIconsRow: { 
    display: 'flex',
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    flexWrap: 'wrap', 
    gap: '6px', // Reduced gap slightly
    width: '100%',   
    marginTop: 'auto', // Push to the bottom if space-between is used on card
    paddingTop: '10px', // Space above the icon row
    minHeight: '34px', // Ensure it has some height even if empty for layout consistency
  },
  playerLobbyIcon: { // New distinct style for lobby player icons
    width: '28px',  
    height: '28px', 
    border: '1px solid #111111', // Darker border for icons
    boxSizing: 'border-box',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '2px', 
  },
  gameInfoTop: { 
    textAlign: 'center',
    width: '100%',
  },
  gameUid: {
    fontSize: '18px',
    margin: '0 0 10px 0',
    color: '#FFFF00', 
    fontWeight: 'bold',
    fontFamily: "'Quantico', sans-serif",
  },
  gameStatus: {
    fontSize: '15px', 
    margin: '0 0 10px 0',
    fontWeight: 'bold',
    fontFamily: "'Quantico', sans-serif",
  },
  playerCount: {
    fontSize: '15px', 
    margin: '0',
    color: '#FFFFFF', 
    fontFamily: "'Quantico', sans-serif",
    fontWeight: 'bold',
  },
  noPlayersText: {
    fontSize: '12px',
    color: '#777777',
    fontStyle: 'italic',
    width: '100%',
    textAlign: 'center',
  }
};

export default GameTableCard; 