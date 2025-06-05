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
      <div style={styles.tableContainer}>
        <div style={styles.tableImage}>
          <img 
            src="/table.png" 
            alt="Empty Table" 
            style={styles.tableImg}
          />
        </div>
        
        <div style={styles.gameInfoBottom}>
          <div style={styles.emptyText}>EMPTY</div>
        </div>
      </div>
    );
  }

  const { game_uid, status, current_players_count, max_players, players = [], turn_count } = game;

  // Function to randomly select an avatar
  const getRandomAvatar = (playerId: number) => {
    // Use player ID as seed for consistent avatar selection per player
    const avatarIndex = (playerId % 8) + 1; // 1 to 8
    const avatarPath = `/avatar_${avatarIndex}.png`;
    console.log(`Player ${playerId} using avatar: ${avatarPath}`); 
    return avatarPath;
  };

  const handleImageError = (event: React.SyntheticEvent<HTMLImageElement>, playerId: number) => {
    console.error(`Failed to load avatar for player ${playerId}`);
    
    const currentSrc = event.currentTarget.src;
    const currentAvatarMatch = currentSrc.match(/avatar_(\d+)\.png/);
    
    if (currentAvatarMatch) {
      const currentAvatarNum = parseInt(currentAvatarMatch[1]);
      const nextAvatarNum = currentAvatarNum >= 8 ? 1 : currentAvatarNum + 1;
      const nextAvatarPath = `/avatar_${nextAvatarNum}.png`;
      
      if (event.currentTarget.dataset.retryCount) {
        const retryCount = parseInt(event.currentTarget.dataset.retryCount);
        if (retryCount >= 8) {
          event.currentTarget.style.display = 'none';
          const parent = event.currentTarget.parentElement;
          if (parent) {
            parent.style.backgroundColor = `hsl(${playerId * 137.5 % 360}, 70%, 60%)`;
            parent.style.border = '2px solid white';
            parent.innerHTML = playerId.toString();
            parent.style.color = 'white';
            parent.style.fontSize = '14px';
            parent.style.fontWeight = 'bold';
            parent.style.display = 'flex';
            parent.style.alignItems = 'center';
            parent.style.justifyContent = 'center';
          }
          return;
        } else {
          event.currentTarget.dataset.retryCount = (retryCount + 1).toString();
        }
      } else {
        event.currentTarget.dataset.retryCount = '1';
      }
      
      console.log(`Retrying with avatar: ${nextAvatarPath}`);
      event.currentTarget.src = nextAvatarPath;
    } else {
      event.currentTarget.src = '/avatar_1.png';
      event.currentTarget.dataset.retryCount = '1';
    }
  };

  const renderPlayerIcons = () => {
    const icons = [];
    const actualPlayerCount = players.length;
    if (actualPlayerCount === 0 && status !== 'waiting_for_players' && !game_uid.startsWith('fake-')) {
        return null;
    } else if (actualPlayerCount === 0 && (status === 'waiting_for_players' || game_uid.startsWith('fake-'))){
        return <div style={styles.noPlayersText}>Waiting for players...</div>;
    }

    for (let i = 0; i < actualPlayerCount; i++) {
      const player = players[i];
      const avatarSrc = getRandomAvatar(player.id);
      
      icons.push(
        <div 
          key={`player-icon-${player.id}-${game_uid}`}
          style={{
            ...styles.playerAvatar,
            opacity: player.is_bankrupt ? 0.5 : 1,
          }}
          title={`${player.name} (P${player.id})${player.is_bankrupt ? ' [BANKRUPT]': ''}`}
        >
          <img 
            src={avatarSrc}
            alt={player.name}
            style={styles.avatarImage}
            onError={(e) => handleImageError(e, player.id)}
            onLoad={() => console.log(`Successfully loaded avatar for player ${player.id}: ${avatarSrc}`)}
          />
          {player.is_bankrupt && <div style={styles.bankruptOverlay}>X</div>}
        </div>
      );
    }
    return icons;
  };

  let statusDisplay = status;
  let statusColor = '#FFFF00'; // Yellow for initializing/waiting

  // Map status to English display names
  switch(status) {
    case 'in_progress':
        statusDisplay = `Playing (Turn ${turn_count || 1})`;
        statusColor = '#00FF00'; // Bright Green
        break;
    case 'completed':
    case 'max_turns_reached':
    case 'aborted_no_winner':
        statusDisplay = "Finished";
        statusColor = '#FF6347'; // Tomato Red
        break;
    case 'initializing':
        statusDisplay = "Starting...";
        statusColor = '#FFFF00'; // Yellow for init
        break;
    case 'waiting_for_players':
        statusDisplay = "Waiting...";
        statusColor = '#FFA500'; // Orange for waiting
        break;
    default:
        statusDisplay = status.replace(/_/g, ' ').toUpperCase();
        statusColor = '#BBBBBB'; // Grey for unknown status
        break;
  }

  return (
    <Link href={game_uid.startsWith('fake-') ? '#' : `/game/${game_uid}`} passHref style={{ textDecoration: 'none', pointerEvents: game_uid.startsWith('fake-') ? 'none' : 'auto' }}>
      <div style={styles.tableContainer}>
        <div style={styles.tableImage}>
          <img 
            src="/table.png" 
            alt="Game Table" 
            style={styles.tableImg}
          />
          <div style={styles.playersOnTable}>
            {players && players.length > 0 ? renderPlayerIcons() : null}
          </div>
        </div>
        
        <div style={styles.gameInfoBottom}>
          <div style={{ ...styles.gameStatus, color: statusColor }}>
            {statusDisplay}
          </div>
          <div style={styles.playerCount}>
            {current_players_count}/{max_players} Players
          </div>
        </div>
      </div>
    </Link>
  );
};

// Updated styles for the new design
const styles: { [key: string]: React.CSSProperties } = {
  tableContainer: {
    width: '100%',
    maxWidth: '460px',
    minWidth: '460px',
    height: '380px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    margin: '10px',
    cursor: 'pointer',
    position: 'relative',
    fontFamily: "'Quantico', sans-serif",
  },
  
  tableImage: {
    width: '100%',
    height: '100%%',
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  
  tableImg: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
  },
  
  playersOnTable: {
    position: 'absolute',
    top: '0%',
    left: '20%',
    right: '20%',
    bottom: '20%',
    display: 'flex',
    flexWrap: 'wrap',
    justifyContent: 'center',
    alignItems: 'center',
    gap: '15px',
  },
  
  playerAvatar: {
    width: '80px',
    height: '80px',
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  
  avatarImage: {
    width: '100%',
    height: '100%',
    borderRadius: '50%',
    objectFit: 'cover',
  },
  
  bankruptOverlay: {
    position: 'absolute',
    top: '0',
    left: '0',
    right: '0',
    bottom: '0',
    // backgroundColor: 'rgba(255, 0, 0, 0.7)',
    color: 'white',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '18px',
    fontWeight: 'bold',
    borderRadius: '50%',
  },
  
  gameInfoBottom: {
    marginTop: '-40px',
    textAlign: 'center',
    width: '100%',
  },
  
  gameId: {
    fontSize: '18px',
    color: '#FFFF00',
    fontWeight: 'bold',
    margin: '4px 0',
    fontFamily: "'Quantico', sans-serif",
  },
  
  gameStatus: {
    fontSize: '14px',
    fontWeight: 'bold',
    margin: '4px 0',
    fontFamily: "'Quantico', sans-serif",
  },
  
  playerCount: {
    fontSize: '14px',
    color: '#FFFFFF',
    margin: '4px 0',
    fontFamily: "'Quantico', sans-serif",
  },
  
  emptyText: {
    fontSize: '20px',
    fontWeight: 'bold',
    color: '#888888',
    textTransform: 'uppercase',
    fontFamily: "'Quantico', sans-serif",
    margin: '4px 0',
  },
  
  emptyCard: {
    width: '460px',
    height: '380px',
    border: '2px dashed #444444',
    borderRadius: '8px',
    backgroundColor: 'rgba(16, 16, 16, 0.5)',
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
  
  noPlayersText: {
    fontSize: '12px',
    color: '#777777',
    fontStyle: 'italic',
    textAlign: 'center',
  }
};

export default GameTableCard; 