'use client';
import React from 'react';

const MonopolyBoard = ({ boardSquares = [], playerStates = {}, activePlayerId = null, onSquareHover, onSquareLeave, hoveredSquareId }) => {
    if (!boardSquares || boardSquares.length === 0) {
        return <div style={{ padding: '20px', textAlign: 'center', fontFamily: 'Quantico, sans-serif' }}>Loading board data or board data is empty...</div>;
    }

    // Helper to map linear square ID (0-39) to grid positions [row, col]
    // Grid is 11x11. Rows/Cols are 0-indexed.
    // (0,0) is top-left. (10,0) is GO. (10,10) is Jail Visit. (0,10) is Free Parking. (0,0) is Go To Jail.
    const getGridPosition = (squareId) => {
        if (squareId >= 0 && squareId <= 10) return [10, 10 - squareId]; // Bottom row (GO is 0, maps to 10,10; square 10 maps to 10,0)
        if (squareId >= 11 && squareId <= 20) return [10 - (squareId - 10), 0]; // Left column (square 11 maps to 9,0; square 20 maps to 0,0)
        if (squareId >= 21 && squareId <= 30) return [0, squareId - 20];    // Top row (square 21 maps to 0,1; square 30 maps to 0,10)
        if (squareId >= 31 && squareId <= 39) return [squareId - 30, 10];   // Right column (square 31 maps to 1,10; square 39 maps to 9,10)
        return null; // Should not happen for 0-39
    };

    const boardCells = Array(11).fill(null).map(() => Array(11).fill(null));
    const playerColors = ['#ff6347', '#4682b4', '#32cd32', '#ffd700', '#EE82EE', '#A52A2A']; // Tomato, SteelBlue, LimeGreen, Gold, Violet, Brown

    boardSquares.forEach(square => {
        const pos = getGridPosition(square.id);
        if (pos) {
            boardCells[pos[0]][pos[1]] = square;
        }
    });

    const getSquareStyling = (square) => {
        let style = { color: '#222222' }; // Default high-contrast text color

        if (!square || !square.type) return style;

        switch (square.color_group) {
            case 'BROWN': style.backgroundColor = '#955436'; style.color='white'; break;
            case 'LIGHTBLUE': style.backgroundColor = '#aae0fa'; style.color = '#222222'; break; 
            case 'PINK': style.backgroundColor = '#d93a96'; style.color='white'; break;
            case 'ORANGE': style.backgroundColor = '#f7921c'; style.color = '#222222'; break; 
            case 'RED': style.backgroundColor = '#ed1b24'; style.color='white'; break;
            case 'YELLOW': style.backgroundColor = '#fff200'; style.color = '#222222'; break; 
            case 'GREEN': style.backgroundColor = '#1fb25a'; style.color='white';break;
            case 'DARKBLUE': style.backgroundColor = '#0072bb'; style.color='white';break;
            case 'RAILROAD': style.backgroundColor = '#cccccc'; style.color = '#222222'; break; // Lighter grey for railroad bg
            case 'UTILITY': style.backgroundColor = '#e6e6e6'; style.color = '#222222'; break;  // Lighter grey for utility bg
            default: style.backgroundColor = '#f0f0f0'; style.color = '#222222'; break;
        }
        if (square.type === 'CHANCE') { style.backgroundColor = '#FFD700'; style.color = '#222222'; }
        if (square.type === 'COMMUNITY_CHEST') { style.backgroundColor = '#87CEEB'; style.color = '#222222'; }
        if (square.type === 'LUXURY_TAX') { style.backgroundColor = '#d3d3d3'; style.color = '#222222'; }
        if (square.type === 'INCOME_TAX') { style.backgroundColor = '#c0c0c0'; style.color = '#222222'; }
        // Ensure corner squares with specific types also get high contrast if their default bg is light
        if (square.type === 'GO' || square.type === 'JAIL_VISITING' || square.type === 'FREE_PARKING') {
            style.backgroundColor = '#E6E6E6'; // Consistent light bg for these corners
            style.color = '#222222';
        }
        if (square.type === 'GO_TO_JAIL') {
            style.backgroundColor = '#5A5A5A'; // Darker grey for Go To Jail
            style.color = '#FFFFFF'; 
        }

        return style;
    };

    const getSquareColor = (square) => {
        // This function provides the color for the little color bar on properties.
        // It should ideally reflect the 'color_group' distinctly.
        if (!square || !square.color_group) return 'transparent'; // No bar if no color group
        switch (square.color_group) {
            case 'BROWN': return '#955436';
            case 'LIGHTBLUE': return '#aae0fa';
            case 'PINK': return '#d93a96';
            case 'ORANGE': return '#f7921c';
            case 'RED': return '#ed1b24';
            case 'YELLOW': return '#fff200';
            case 'GREEN': return '#1fb25a';
            case 'DARKBLUE': return '#0072bb';
            // For Railroads and Utilities, a neutral bar or no bar might be better if their main BG shows their type.
            // If they should have a bar, pick a representative color.
            case 'RAILROAD': return '#505050'; // Dark grey bar for railroads
            case 'UTILITY': return '#707070';  // Medium grey bar for utilities
            default: return 'transparent'; // No color bar for other types by default
        }
    };

    return (
        <div className="monopoly-board-container">
            <div className="monopoly-board">
                {boardCells.map((row, rowIndex) =>
                    row.map((square, colIndex) => {
                        const cellKey = `${rowIndex}-${colIndex}`;
                        if (square) {
                            // This is a game square on the perimeter
                            const squareStyle = getSquareStyling(square);
                            return (
                                <div 
                                    key={square.id} 
                                    className={`grid-cell square type-${square.type?.toLowerCase()} ${square.id === hoveredSquareId ? 'hovered-square' : ''}`}
                                    title={`ID: ${square.id} - ${square.name}`}
                                    style={{
                                        gridRow: `${rowIndex + 1}`,
                                        gridColumn: `${colIndex + 1}`,
                                        ...squareStyle
                                    }}
                                    onMouseEnter={(event) => onSquareHover && onSquareHover(square, event)}
                                    onMouseLeave={() => onSquareLeave && onSquareLeave()}
                                >
                                    {(square.type === 'PROPERTY' || square.type === 'RAILROAD' || square.type === 'UTILITY') && square.color_group && (
                                        <div 
                                            className="color-bar"
                                            style={{ backgroundColor: getSquareColor(square) }} 
                                        />
                                    )}
                                    <div className="square-name">{square.name}</div>
                                    {square.price && <div className="square-price">${square.price}</div>}
                                    {square.tax_amount && <div className="square-price">Pay ${square.tax_amount}</div>}
                                    <div className="player-pieces-container">
                                        {Object.values(playerStates)
                                            .filter(p => p.my_position === square.id && !p.is_bankrupt)
                                            .map(p => (
                                                <div key={p.my_player_id} title={p.my_name}
                                                     className={`player-piece ${p.my_player_id === activePlayerId ? 'active-player-piece' : ''}`}
                                                     style={{ backgroundColor: playerColors[p.my_player_id % playerColors.length] }}>
                                                    <svg viewBox="0 0 16 16" width="18px" height="18px" fill="white" xmlns="http://www.w3.org/2000/svg" style={{ display: 'block', margin: 'auto' }}>
                                                      <rect x="6" y="2" width="4" height="2" /> 
                                                      <rect x="5" y="4" width="6" height="2" /> 
                                                      <rect x="4" y="6" width="8" height="6" /> 
                                                      <rect x="2" y="12" width="12" height="2" /> 
                                                    </svg>
                                                </div>
                                        ))}
                                    </div>
                                    {/* Add house/hotel indicators here later */}
                                    {/* 
                                        The owner indicator (border color) is determined by pState (the player owning the square).
                                        Details like num_houses and is_mortgaged are currently sourced from pState.board_squares.
                                        This assumes that pState.board_squares (from player_state_update messages) accurately 
                                        reflects the state of properties owned by pState.
                                        An alternative approach could be to use the main 'square' object from the parent 
                                        map iteration if the global 'boardSquares' prop is always the single source of truth 
                                        for all square details (including houses/mortgages for all properties).
                                    */}
                                    {Object.values(playerStates).map(pState => {
                                        if (pState.my_properties_owned_ids?.includes(square.id)) {
                                            const propDetails = (pState.board_squares || []).find(sq => sq.id === square.id);
                                            let houseIndicator = '';
                                            if (propDetails?.num_houses > 0 && propDetails?.num_houses < 5) {
                                                houseIndicator = 'H'.repeat(propDetails.num_houses);
                                            } else if (propDetails?.num_houses === 5) {
                                                houseIndicator = 'HOTEL';
                                            }
                                            return (
                                                <div key={`owner-${pState.my_player_id}`} className="owner-indicator"
                                                     style={{borderColor: playerColors[pState.my_player_id % playerColors.length]}}>
                                                    {houseIndicator}
                                                </div>
                                            );
                                        }
                                        return null;
                                    })}
                                </div>
                            );
                        } else if (rowIndex === 1 && colIndex === 1) { 
                            // Render the 9x9 background area for the center, anchored at (1,1) in boardCells
                            return (
                                <div 
                                    key="center-bg-area"
                                    className="center-area-background" 
                                    style={{
                                        gridRow: `2 / span 9`, // CSS grid is 1-indexed
                                        gridColumn: `2 / span 9`,
                                        // backgroundColor: '#dAf1d2', // Replaced by background image
                                        border: '1px dashed #b0c4b1', 
                                        backgroundImage: 'url("/images/bg_pic.png")', // ASSUMED PATH
                                        backgroundSize: 'cover',
                                        backgroundPosition: 'center center',
                                        backgroundRepeat: 'no-repeat',
                                    }}
                                />
                            );
                        } else if (rowIndex > 0 && rowIndex < 10 && colIndex > 0 && colIndex < 10) {
                            // Other cells within the 9x9 center block are now covered by the spanning background or not rendered.
                            return null; 
                        }
                        // Fallback for any other cell (e.g., unused perimeter cells if mapping is ever imperfect)
                        // This should ideally not be reached if the board is mapped correctly.
                        return <div key={cellKey} className="grid-cell empty-perimeter-unused" style={{ gridRow: `${rowIndex + 1}`, gridColumn: `${colIndex + 1}`}}></div>;
                    })
                )}
            </div>
            <style jsx>{`
                .monopoly-board-container {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    padding: 10px; 
                    background-color: #cde6d0; 
                    flex-grow: 1; 
                    overflow: hidden; 
                    font-family: 'Quantico', sans-serif; 
                    width: 100%; 
                    height: 100%; 
                }
                .monopoly-board {
                    display: grid;
                    grid-template-columns: repeat(11, 1fr); 
                    grid-template-rows: repeat(11, 1fr);    
                    border: 2px solid black;
                    box-shadow: 5px 5px 15px rgba(0,0,0,0.3);
                    background-color: #f0f0f0; 
                    word-break: break-word;
                    position: relative; 
                    font-family: inherit; 
                    max-width: 100%;     
                    /* max-height: 100%; */ /* height: 100% should take precedence */
                    height: 100%; /* Explicitly set height to 100% */
                }
                .grid-cell {
                    border: 1px solid #555; 
                    display: flex;
                    flex-direction: column;
                    justify-content: flex-start; 
                    align-items: center;
                    text-align: center;
                    position: relative; 
                    font-family: inherit; 
                    font-size: 15px; 
                    font-weight: bold; 
                    padding: 5px;  
                    box-sizing: border-box;
                    overflow: hidden; 
                    background-color: #f0f0f0;
                    color: #222222; 
                    word-break: break-word;
                }
                .square .square-name {
                    font-family: inherit;
                    font-weight: bold; 
                    margin: 5px 0;
                    line-height: 1.2; /* Adjusted */
                    height: auto; 
                    min-height: 30%; 
                    overflow: hidden;
                }
                .square .square-price {
                    font-family: inherit;
                    font-weight: bold;
                    margin-top: auto; 
                    padding-bottom: 2px;
                }
                .color-bar {
                    height: 20px; /* Increased from 15px */
                    width: 100%;
                    border-bottom: 1px solid black; 
                    margin-bottom: 4px; /* Adjusted margin */
                }
                .player-pieces-container {
                    position: absolute;
                    bottom: 2px;
                    left: 2px;
                    right: 2px;
                    display: flex;
                    flex-wrap: wrap;
                    justify-content: center;
                    align-items: flex-end;
                    gap: 2px;
                }
                .player-piece {
                    width: 22px;  
                    height: 22px; 
                    border: 1px solid black;
                    border-radius: 5px; 
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 1px;
                }
                .active-player-piece {
                    box-shadow: 0 0 3px 2px yellow;
                    z-index: 10;
                }
                .owner-indicator {
                    position: absolute;
                    top: 0px;
                    left: 0px;
                    right: 0px;
                    bottom: 0px;
                    border: 3px solid transparent; /* Border color set by player */
                    pointer-events: none; /* So it doesn't interfere with clicks */
                    font-size: 15px; /* Match grid-cell or slightly larger */
                    font-weight: bold;
                    font-family: inherit; /* Will inherit Quantico */
                    color: #222222; /* Default for house/hotel text, ensuring contrast on light player borders */
                    display: flex;
                    justify-content: flex-end;
                    align-items: flex-end;
                    padding: 2px;
                    /* Text shadow might need adjustment based on border color */
                }
                .center-area-background { /* The 9x9 spanning cell for BG only */
                    /* Specific styles (bg, border, padding) are applied inline in JSX */
                    /* This class is for semantic clarity if needed */
                    display: flex; /* Added to help if text somehow wasn't centering inside, though abs pos handles it */
                    align-items: center; /* Added */
                    justify-content: center; /* Added */
                }
                .empty-center, .empty-perimeter-unused {
                     background-color: #dAf1d2;
                     border: 1px dashed #b0c4b1; /* Light grid for empty center cells */
                }
                 /* Make corner cells larger */
                .grid-cell[style*="grid-row: 1 / auto; grid-column: 1 / auto;"],
                .grid-cell[style*="grid-row: 1 / auto; grid-column: 11 / auto;"],
                .grid-cell[style*="grid-row: 11 / auto; grid-column: 1 / auto;"],
                .grid-cell[style*="grid-row: 11 / auto; grid-column: 11 / auto;"] {
                    /* You might need to adjust how getGridPosition maps to these specific cells for direct style override */
                    /* For now, direct styling of corners via their content if needed */
                }
                .type-go, .type-jail_visiting, .type-free_parking, .type-go_to_jail {
                     font-family: inherit; /* Ensure Quantico from .grid-cell */
                     font-weight: bold; /* Ensure bold from .grid-cell */
                }
                .hovered-square {
                    outline: 3px solid yellow;
                    outline-offset: -3px;
                    box-shadow: inset 0 0 10px rgba(255,255,0,0.5);
                    z-index: 10; /* Above normal cells, below logo text and tooltips */
                }
            `}</style>
        </div>
    );
};

export default MonopolyBoard;
