'use client'; 

import { useEffect, useState, useRef } from 'react';
import { useParams } from 'next/navigation'; 
import Head from 'next/head'; // For setting the page title
import MonopolyBoard from '../../components/MonopolyBoard'; // Adjusted path

export default function GamePage() {
    const params = useParams();
    const gameIdFromUrl = params.gameId;

    const [gameId, setGameId] = useState('');
    const [connectionStatus, setConnectionStatus] = useState('Disconnected');
    const [gameLog, setGameLog] = useState([]);
    const [agentThoughts, setAgentThoughts] = useState([]);
    const [playerCards, setPlayerCards] = useState({}); 
    const [boardLayout, setBoardLayout] = useState([]); 
    const [activePlayerForBoard, setActivePlayerForBoard] = useState(null);
    const [hoveredPlayer, setHoveredPlayer] = useState(null);
    const [hoveredSquareDetails, setHoveredSquareDetails] = useState(null);
    const [playerTooltipPosition, setPlayerTooltipPosition] = useState({ top: 0, left: 0, visible: false });
    const [squareTooltipPosition, setSquareTooltipPosition] = useState({ top: 0, left: 0, visible: false });
    const [hoveredIconRect, setHoveredIconRect] = useState(null);

    const socketRef = useRef(null);
    const gameLogDivRef = useRef(null);
    const agentThoughtsDivRef = useRef(null);
    const rightPanelRef = useRef(null); // Ref for the right panel
    const playerTooltipRef = useRef(null); // Ref for the player tooltip itself
    const MAX_LOG_ENTRIES = 200;

    // Define player colors, consistent with MonopolyBoard.jsx
    const playerColors = ['#ff6347', '#4682b4', '#32cd32', '#ffd700', '#EE82EE', '#A52A2A']; // Tomato, SteelBlue, LimeGreen, Gold, Violet, Brown

    const appendToLog = (logSetter, newEntry, maxEntries = MAX_LOG_ENTRIES) => {
        logSetter(prevLog => {
            const updatedLog = [...prevLog, newEntry];
            if (updatedLog.length > maxEntries) {
                return updatedLog.slice(updatedLog.length - maxEntries);
            }
            return updatedLog;
        });
    };
    
    useEffect(() => {
        if (gameIdFromUrl) {
            setGameId(gameIdFromUrl);
            console.log("Game ID from URL:", gameIdFromUrl);
        }
    }, [gameIdFromUrl]);

    useEffect(() => {
        if (!gameId) {
            console.log("Game ID is not set, WebSocket connection not started.");
            return;
        }
        console.log("Attempting WebSocket connection for game ID:", gameId);

        if (socketRef.current && (socketRef.current.readyState === WebSocket.OPEN || socketRef.current.readyState === WebSocket.CONNECTING)) {
            console.log("Closing existing WebSocket connection.");
            socketRef.current.close();
        }

        appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `Attempting to connect to game: ${gameId}...`, type: 'info' });
        setAgentThoughts([]);
        setPlayerCards({});
        // setBoardLayout([]); // Removed: Initial board layout will be fetched via API

        const ws = new WebSocket(`ws://localhost:8000/ws/game/${gameId}`);
        socketRef.current = ws;

        ws.onopen = () => {
            setConnectionStatus('Connected');
            appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `Connected to WebSocket for game ID: ${gameId}.`, type: 'info' });
            console.log("WebSocket connected for game ID:", gameId);
            // No longer setting boardLayout here, it's fetched by API.
            // If WS needs to send board layout updates later, the 'initial_board_layout' handler can still be used.
        };

        ws.onmessage = (event) => {
            console.log("Raw WebSocket message received:", event.data); // Log raw message
            try {
                const data = JSON.parse(event.data);
                console.log("Parsed WebSocket data:", data); // Log parsed data
                const newLogEntry = { timestamp: new Date().toLocaleTimeString(), message: data.message || JSON.stringify(data), type: data.type || 'info' };

                if (['init_log', 'game_log_event', 'error_log', 'db_log', 'method_trace', 'debug_loop', 'state_debug', 'warning_log', 'db_trace', 'debug_trace'].includes(data.type)) {
                    appendToLog(setGameLog, newLogEntry);
                } else if (data.type === 'turn_info') { 
                    appendToLog(setGameLog, { ...newLogEntry, message: `TURN INFO: ${data.data}` });
                     try {
                        const turnDataStr = String(data.data);
                        const match = turnDataStr.match(/for P(\d+)/);
                        if (match && match[1]) {
                            setActivePlayerForBoard(parseInt(match[1]));
                        }
                    } catch(e){ console.warn("Could not parse player_id from turn_info", data.data)}
                } else if (data.type === 'initial_board_layout') {
                    setBoardLayout(data.data || []); 
                    appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `Received initial board layout with ${data.data?.length || 0} squares.`, type: 'info' });
                    console.log("Board layout received and set:", data.data);
                } else if (data.type === 'agent_thinking_start') {
                    setActivePlayerForBoard(data.player_id);
                    appendToLog(setAgentThoughts, { ...newLogEntry, message: `P${data.player_id} thinking. Ctx: ${JSON.stringify(data.context)}. Actions: ${data.available_actions ? data.available_actions.join(', ') : 'N/A'}` });
                } else if (data.type === 'agent_decision') {
                    setActivePlayerForBoard(data.player_id);
                    appendToLog(setAgentThoughts, { ...newLogEntry, message: `P${data.player_id} DECIDED: Tool='${data.tool_name}', Params=${JSON.stringify(data.params)}. Thoughts: ${data.thoughts}` });
                } else if (data.type === 'action_result') {
                    setActivePlayerForBoard(data.player_id);
                    appendToLog(setAgentThoughts, { ...newLogEntry, message: `P${data.player_id} ACTION RESULT for '${data.tool_name}': Status='${data.result_status}', Msg='${data.result_message}'`, type: data.result_status === 'error' ? 'error' : 'action-result' });
                } else if (data.type === 'game_summary_data') {
                    appendToLog(setGameLog, { ...newLogEntry, message: `--- GAME SUMMARY --- \n${data.summary}`});
                } else if (data.type === 'game_end_log' || data.type === 'fatal_error') {
                     appendToLog(setGameLog, { ...newLogEntry, type: 'error'});
                } else if (data.type === 'player_state_update' && data.data) { 
                    console.log("Received player_state_update:", data.data);
                    setPlayerCards(prev => ({
                        ...prev,
                        [data.data.my_player_id]: data.data
                    }));
                    if (data.data.my_player_id === data.data.current_turn_player_id) {
                         setActivePlayerForBoard(data.data.my_player_id);
                    }
                } else {
                    appendToLog(setGameLog, newLogEntry);
                }
            } catch (e) {
                console.error("Error processing message or not JSON:", e, event.data);
                appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `Received non-JSON or malformed data: ${event.data}`, type: 'error' });
            }
        };

        ws.onclose = (event) => {
            setConnectionStatus('Disconnected');
            appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `WebSocket disconnected. Code: ${event.code}, Reason: ${event.reason || 'N/A'}`, type: event.wasClean ? 'info' : 'error' });
            console.log("WebSocket disconnected.");
        };

        ws.onerror = (error) => {
            setConnectionStatus('Error');
            const errorMessage = error && error.message ? error.message : 'Unknown WebSocket error';
            appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `WebSocket Error: ${errorMessage}`, type: 'error' });
            console.error("WebSocket Error: ", error);
        };

        return () => { 
            if (ws) {
                console.log("Closing WebSocket connection due to component unmount or gameId change.");
                ws.close();
            }
        };
    }, [gameId]);

    useEffect(() => { 
        if (gameLogDivRef.current) gameLogDivRef.current.scrollTop = gameLogDivRef.current.scrollHeight; 
        // console.log("Game log updated, boardLayout is:", boardLayout); // Debug log for boardLayout
    }, [gameLog]); // Removed boardLayout from here to avoid excessive logging if it doesn't change with gameLog

    useEffect(() => { 
        if (agentThoughtsDivRef.current) agentThoughtsDivRef.current.scrollTop = agentThoughtsDivRef.current.scrollHeight; 
    }, [agentThoughts]);
    
    // Fetch initial board layout when gameId is available
    useEffect(() => {
        if (gameId) {
            const fetchBoardLayout = async () => {
                appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `Fetching board layout for game ${gameId}...`, type: 'info' });
                try {
                    const response = await fetch(`http://localhost:8000/api/game/${gameId}/board_layout`);
                    if (!response.ok) {
                        const errorData = await response.json().catch(() => ({ detail: "Unknown error fetching layout" }));
                        throw new Error(`HTTP error ${response.status}: ${errorData.detail || "Failed to fetch board layout"}`);
                    }
                    const data = await response.json();
                    if (data.status === 'success' && data.board_layout) {
                        setBoardLayout(data.board_layout);
                        appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `Board layout loaded successfully (${data.board_layout.length} squares).`, type: 'info' });
                        console.log("Board layout fetched and set from API:", data.board_layout);
                    } else {
                        throw new Error(data.error || "Failed to load board layout from API.");
                    }
                } catch (error) {
                    console.error("Error fetching board layout:", error);
                    appendToLog(setGameLog, { timestamp: new Date().toLocaleTimeString(), message: `Error fetching board layout: ${error.message}`, type: 'error' });
                    // Optionally set boardLayout to a default or error state here
                    setBoardLayout([]); // Clear or set to default on error
                }
            };
            fetchBoardLayout();
        }
    }, [gameId]); // Runs when gameId changes
    
    // Log when boardLayout state changes
    useEffect(() => {
        console.log("boardLayout state changed:", boardLayout);
    }, [boardLayout]);

    // Define pixel art styles
    const pixelStyles = {
        container: {
            fontFamily: "'Quantico', sans-serif",
            padding: '10px',
            backgroundColor: '#000000',
            color: '#00FF00',
            minHeight: '100vh',
            display: 'flex',
            flexDirection: 'column',
            imageRendering: 'pixelated',
        },
        gamePageLayout: {
            display: 'flex',
            flexDirection: 'row',
            gap: '15px',
            width: '100%',
            flexGrow: 1,
        },
        leftPanel: {
            flex: '4', 
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
            minWidth: '750px', 
        },
        boardSection: { 
            backgroundColor: '#181818', 
            border: '4px solid #00CC00',
            boxShadow: '4px 4px 0px #008800',
            flexGrow: 1, 
            overflow: 'hidden', 
            display: 'flex',
            flexDirection: 'column',
        },
        rightPanel: {
            flex: '1',
            display: 'flex',
            flexDirection: 'column',
            gap: '15px',
            minWidth: '300px',
            maxHeight: 'calc(100vh - 20px)', // leave a little padding for the main container
            overflowY: 'hidden',
            position: 'relative',
            fontFamily: "'Quantico', sans-serif",
        },
        gameInfoSection: { 
            backgroundColor: '#181818',
            border: '2px solid #00CC00', 
            padding: '5px 8px', 
            boxShadow: '2px 2px 0px #008800', 
            fontFamily: "'Quantico', sans-serif",
        },
        gameInfoTextSmall: { 
            fontSize: '10px',
            lineHeight: '1.4',
            color: '#00FF00',
            fontFamily: "'Quantico', sans-serif",
            marginBottom: '5px',
            marginTop: '5px',
        },
        section: { 
            backgroundColor: '#181818',
            border: '4px solid #00CC00',
            padding: '10px',
            marginBottom: '0',
            boxShadow: '4px 4px 0px #008800',
        },
        header: {
            textAlign: 'center',
            fontSize: '24px', // Adjust for pixel font
            color: '#FFFF00', // Yellow for header
            padding: '10px 0',
            borderBottom: '4px solid #00FF00', // Solid border
            marginBottom: '15px', // Spacing
            textShadow: '2px 2px #FF00FF', // Magenta shadow for more pop
        },
        sectionTitle: {
            fontSize: '16px', // Adjust for pixel font
            color: '#FFFFFF', // White title for contrast
            marginBottom: '8px',
            borderBottom: '2px solid #00FF00',
            paddingBottom: '4px',
            textTransform: 'uppercase',
        },
        infoText: {
            fontSize: '12px', // Adjust for pixel font
            lineHeight: '1.6',
            color: '#00FF00', // Green text
        },
        infoValue: {
            color: '#FFFFFF',
            backgroundColor: '#0A0A0A', // Adjusted for black background
            padding: '2px 4px',
            border: '2px solid #00FF00',
        },
        statusConnected: {
            color: '#00FF00', // Bright green for connected
            fontWeight: 'bold',
        },
        statusDisconnected: {
            color: '#FF0000', // Bright red for disconnected
            fontWeight: 'bold',
        },
        logPanelSection: { 
            backgroundColor: '#181818',
            border: '4px solid #00CC00',
            padding: '10px',
            marginBottom: '0',
            boxShadow: '4px 4px 0px #008800',
            display: 'flex', 
            flexDirection: 'column',
            overflow: 'hidden', 
            fontFamily: "'Quantico', sans-serif",
        },
        playerSection: { // Specific style for player section to control its height
            backgroundColor: '#181818',
            border: '4px solid #00CC00',
            padding: '10px',
            boxShadow: '4px 4px 0px #008800',
            flexShrink: 0, // Prevent this section from shrinking
        },
        agentThoughtsSection: { // Specific style for agent thoughts to make it grow
            backgroundColor: '#181818',
            border: '4px solid #00CC00',
            padding: '10px',
            boxShadow: '4px 4px 0px #008800',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            flexGrow: 3, // Make this section grow more
            minHeight: '200px', // Ensure it has a decent minimum height
            fontFamily: "'Quantico', sans-serif",
        },
        gameLogSection: { // Specific style for game log, less growth
            backgroundColor: '#181818',
            border: '4px solid #00CC00',
            padding: '10px',
            boxShadow: '4px 4px 0px #008800',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            flexGrow: 1, // Make this section grow less
            minHeight: '150px', // Ensure it has a decent minimum height
            fontFamily: "'Quantico', sans-serif",
        },
        logDisplay: {
            backgroundColor: '#0A0A0A',
            border: '2px solid #00FF00',
            padding: '8px',
            height: '200px', 
            overflowY: 'scroll',
            fontSize: '12px', // Increased font size for Agent Thoughts, Game Log
            lineHeight: '1.6', // Adjusted line height
            color: '#00FF00',
            fontFamily: "'Quantico', sans-serif",
            flexGrow: 1,
            minHeight: '100px',
        },
        logEntry: {
            marginBottom: '4px',
            wordBreak: 'break-all',
            fontFamily: "'Quantico', sans-serif",
        },
        errorLog: {
            color: '#FF6347', // Tomato red for errors
        },
        infoLog: {
             color: '#00FF00', // Green for info
        },
        actionResultLog: {
            color: '#FFFF00', // Yellow for action results
        },
        playerCardContainer: {
            display: 'flex',
            flexWrap: 'wrap',
            gap: '10px', // Spacing between cards
        },
        playerCard: {
            border: '3px solid #00FFFF',
            padding: '10px',
            backgroundColor: '#1C1C1C', // Adjusted for black background
            minWidth: '250px',
            boxShadow: '3px 3px 0px #00AAAA',
        },
        playerCardTitle: {
            fontSize: '14px',
            color: '#FFFF00', // Yellow title
            borderBottom: '2px solid #FFFF00',
            paddingBottom: '3px',
            marginBottom: '6px',
        },
        playerPropertiesList: {
            listStyleType: 'none',
            paddingLeft: '0',
            fontSize: '10px',
            maxHeight: '80px',
            overflowY: 'auto',
            border: '1px dashed #00FF00',
            padding: '5px',
            marginTop: '5px',
        },
        propertyItem: {
            padding: '2px 0',
            color: '#90EE90', // Light green for property items
        },
        playerIcon: { 
            width: '52px',
            height: '52px',
            border: '2px solid #00FFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: '#282828', 
            cursor: 'pointer',
            boxShadow: '2px 2px 0px #00AAAA',
            fontFamily: "'Quantico', sans-serif",
            padding: '3px',
        },
        playerDetailTooltip: { 
            position: 'absolute', 
            backgroundColor: '#1E1E1E',
            border: '3px solid #FFFF00',
            padding: '15px',
            zIndex: 1000,
            color: '#FFFFFF',
            minWidth: '300px',
            boxShadow: '4px 4px 0px #AAAA00',
            fontFamily: "'Quantico', sans-serif", 
            fontSize: '12px',
            maxHeight: 'none', // Explicitly allow full height
            overflowY: 'visible',   // Explicitly allow full height
        },
        playerPropertiesListSmall: { 
            listStyleType: 'none',
            paddingLeft: '0',
            fontSize: '10px',
            maxHeight: 'none', // Explicitly allow full height
            overflowY: 'visible', // Explicitly allow full height
            border: '1px dashed #00FF00',
            padding: '5px',
            marginTop: '5px',
            backgroundColor: '#101010',
            fontFamily: "'Quantico', sans-serif",
        },
        squareDetailTooltip: { // Style for the square detail popup
            position: 'fixed', 
            bottom: '10px',
            left: '10px',
            backgroundColor: '#1E1E1E',
            border: '3px solid #FF8C00',
            padding: '10px', // Reduced padding
            zIndex: 1050, 
            color: '#FFFFFF',
            minWidth: '250px',
            maxWidth: '300px',
            maxHeight: '200px', // Added maxHeight
            overflowY: 'auto', // Added overflowY for scrolling
            boxShadow: '4px 4px 0px #CC7000', 
            fontFamily: "'Quantico', sans-serif",
            fontSize: '11px',
            lineHeight: '1.5',
        },
        tooltipTitle: {
            fontSize: '14px',
            color: '#FFFF00',
            borderBottom: '1px solid #FFFF00',
            paddingBottom: '3px',
            marginBottom: '6px',
            fontFamily: "'Quantico', sans-serif",
        },
        tooltipSection: {
            marginTop: '5px',
            fontFamily: "'Quantico', sans-serif",
        },
        tooltipDetail: {
            color: '#00FF00', // Green for detail labels
            fontFamily: "'Quantico', sans-serif",
        },
        tooltipValue: {
            color: '#FFFFFF', // White for values
            marginLeft: '5px',
            fontFamily: "'Quantico', sans-serif",
        },
    };

    const calculatePlayerTooltipPosition = (iconRect, panelRect, pixelStyles, currentTooltipRef) => {
        if (!panelRect || !pixelStyles.playerDetailTooltip || !currentTooltipRef || !currentTooltipRef.current) {
            return { top: 0, left: 0, visible: false };
        }

        const VERTICAL_OFFSET = 10; 
        const PANEL_PADDING = 5;    

        const ttWidth = parseFloat(pixelStyles.playerDetailTooltip.minWidth) || 300;
        let ttHeight = currentTooltipRef.current.offsetHeight;
        if (ttHeight === 0) {
            // Attempt a brief forced layout if height is 0 initially, then re-measure
            // This is a bit of a hack, ideally useResizeObserver or a more robust way for dynamic content height
            currentTooltipRef.current.style.maxHeight = '9999px'; // Temporarily allow full expansion
            ttHeight = currentTooltipRef.current.offsetHeight;
            currentTooltipRef.current.style.maxHeight = ''; // Reset, will be controlled by CSS or nothing
            if (ttHeight === 0) ttHeight = 320; // Fallback if still 0 after forced measure
        }

        let finalLeft = (iconRect.left - panelRect.left) + (iconRect.width / 2) - (ttWidth / 2);
        let finalTop = (iconRect.bottom - panelRect.top) + VERTICAL_OFFSET;

        finalLeft = Math.max(PANEL_PADDING, finalLeft);
        finalLeft = Math.min(finalLeft, panelRect.width - ttWidth - PANEL_PADDING);
        if (finalLeft < PANEL_PADDING) finalLeft = PANEL_PADDING; 

        if (finalTop + ttHeight > panelRect.height - PANEL_PADDING) {
            let topAbove = (iconRect.top - panelRect.top) - ttHeight - VERTICAL_OFFSET;
            if (topAbove >= PANEL_PADDING) {
                finalTop = topAbove;
            } else {
                finalTop = PANEL_PADDING; 
            }
        }
        if (finalTop < PANEL_PADDING) finalTop = PANEL_PADDING; 
        
        if (finalTop + ttHeight > panelRect.height - PANEL_PADDING) {
            finalTop = Math.max(PANEL_PADDING, panelRect.height - ttHeight - PANEL_PADDING);
            if (finalTop < PANEL_PADDING) finalTop = PANEL_PADDING; 
        }
        
        return { top: finalTop, left: finalLeft };
    };

    const handlePlayerIconMouseEnter = (playerData, event) => {
        setHoveredPlayer(playerData);
        setHoveredIconRect(event.target.getBoundingClientRect());
        setPlayerTooltipPosition(prev => ({ ...prev, top: -9999, left: -9999, visible: true })); // Render off-screen first
    };

    const handlePlayerAreaMouseLeave = () => {
        setHoveredPlayer(null);
        setHoveredIconRect(null);
        setPlayerTooltipPosition({ top: 0, left: 0, visible: false });
    };
    
    useEffect(() => {
        if (hoveredPlayer && hoveredIconRect && playerTooltipPosition.visible && playerTooltipRef.current && rightPanelRef.current) {
            requestAnimationFrame(() => { // Ensure DOM has updated from setHoveredPlayer
                 if (playerTooltipRef.current && rightPanelRef.current && hoveredIconRect) { // Double check refs
                    const iconRect = hoveredIconRect;
                    const panelRect = rightPanelRef.current.getBoundingClientRect();
                    const position = calculatePlayerTooltipPosition(iconRect, panelRect, pixelStyles, playerTooltipRef);
                    
                    if (playerTooltipPosition.top !== position.top || playerTooltipPosition.left !== position.left) {
                         setPlayerTooltipPosition(prev => ({ ...position, visible: true })); // Set final position
                    }
                }
            });
        }
    }, [hoveredPlayer, hoveredIconRect, playerTooltipPosition.visible, pixelStyles]); // Dependencies updated

    const handleSquareHover = (squareDataFromBoard, event) => {
        if (!squareDataFromBoard || !event) {
            setHoveredSquareDetails(null);
            setSquareTooltipPosition({visible: false});
            return;
        }

        let details = {
            id: squareDataFromBoard.id,
            name: squareDataFromBoard.name,
            type: squareDataFromBoard.type,
            price: squareDataFromBoard.price,
            tax_amount: squareDataFromBoard.tax_amount,
            color_group: squareDataFromBoard.color_group,
            rent_levels: squareDataFromBoard.rent_levels || [],
            rent_multipliers: squareDataFromBoard.rent_multipliers || [],
            owner: null,
            is_mortgaged: null,
            num_houses: null,
            current_rent_display: "N/A",
            owned_railroads_by_owner: null,
            owned_utilities_by_owner: null,
        };

        for (const pId in playerCards) {
            const player = playerCards[pId];
            if (player.my_properties_owned_ids?.includes(squareDataFromBoard.id)) {
                details.owner = { id: player.my_player_id, name: player.my_name };
                const ownedPropData = (player.board_squares || []).find(sq => sq.id === squareDataFromBoard.id);
                if (ownedPropData) {
                    details.is_mortgaged = ownedPropData.is_mortgaged;
                    details.num_houses = ownedPropData.num_houses;
                }
                break;
            }
        }
        
        if (details.is_mortgaged) {
            details.current_rent_display = "Mortgaged";
        } else if (details.type === 'PROPERTY' && details.rent_levels && details.rent_levels.length > 0) {
            const rentIndex = details.num_houses !== null ? Math.min(details.num_houses, details.rent_levels.length -1) : 0;
            details.current_rent_display = `$${details.rent_levels[rentIndex]}`;
        } else if (details.type === 'RAILROAD' && details.rent_levels && details.rent_levels.length > 0) {
            if (details.owner) {
                let railroadsOwned = 0;
                const ownerPlayer = playerCards[details.owner.id];
                if (ownerPlayer) {
                    boardLayout.forEach(sq => {
                        if (sq.type === 'RAILROAD' && ownerPlayer.my_properties_owned_ids?.includes(sq.id)) {
                            railroadsOwned++;
                        }
                    });
                }
                details.owned_railroads_by_owner = railroadsOwned;
                if (railroadsOwned > 0 && railroadsOwned <= details.rent_levels.length) {
                    details.current_rent_display = `$${details.rent_levels[railroadsOwned - 1]}`;
                }
            } else { 
                 details.current_rent_display = details.price ? `Price: $${details.price}` : "N/A";
            }
        } else if (details.type === 'UTILITY' && details.rent_multipliers && details.rent_multipliers.length > 0) {
            if (details.owner) {
                let utilitiesOwned = 0;
                const ownerPlayer = playerCards[details.owner.id];
                 if (ownerPlayer) {
                    boardLayout.forEach(sq => {
                        if (sq.type === 'UTILITY' && ownerPlayer.my_properties_owned_ids?.includes(sq.id)) {
                            utilitiesOwned++;
                        }
                    });
                }
                details.owned_utilities_by_owner = utilitiesOwned;
                if (utilitiesOwned > 0 && utilitiesOwned <= details.rent_multipliers.length) {
                    details.current_rent_display = `${details.rent_multipliers[utilitiesOwned - 1]}x Dice Roll`;
                }
            } else { 
                details.current_rent_display = details.price ? `Price: $${details.price}` : "N/A";
            }
        } else if (details.type === 'INCOME_TAX' || details.type === 'LUXURY_TAX') {
            details.current_rent_display = `Pay $${details.tax_amount}`;
        }

        setHoveredSquareDetails(details);

        const squareRect = event.target.getBoundingClientRect();
        const tooltipWidth = 250; 
        const tooltipHeight = 200; 
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const offset = 10; 

        let top = squareRect.bottom + offset;
        let left = squareRect.left;

        if (top + tooltipHeight > viewportHeight) {
            top = squareRect.top - tooltipHeight - offset; 
        }
        if (top < 0) {
            top = offset; 
        }

        if (left + tooltipWidth > viewportWidth) {
            left = viewportWidth - tooltipWidth - offset; 
        }
        if (left < 0) { 
            left = offset; 
        }

        setSquareTooltipPosition({ top, left, visible: true });
    };

    const handleSquareLeave = () => {
        setHoveredSquareDetails(null);
        setSquareTooltipPosition({visible: false});
    };

    return (
        <>
            <Head>
                <title>Monopoly Game: {gameId || 'Loading...'}</title>
                <link href="https://fonts.googleapis.com/css2?family=Quantico:wght@400;700&display=swap" rel="stylesheet" />
            </Head>
            <div style={pixelStyles.container}>
                {/* Header removed */}
                {/* <div style={pixelStyles.header}>Monopoly AI Battleground - Game ID: {gameId || "Loading..."}</div> */}

                <div style={pixelStyles.gamePageLayout}>
                    {/* Left Panel */}
                    <div style={pixelStyles.leftPanel}>
                        <section style={pixelStyles.boardSection}>
                        <MonopolyBoard 
                            boardSquares={boardLayout} 
                            playerStates={playerCards}
                            activePlayerId={activePlayerForBoard} 
                                onSquareHover={handleSquareHover}
                                onSquareLeave={handleSquareLeave}
                                hoveredSquareId={hoveredSquareDetails?.id}
                        />
                    </section>
                    </div>

                    {/* Right Panel */}
                    <div style={pixelStyles.rightPanel} ref={rightPanelRef}>
                        <section style={pixelStyles.gameInfoSection}> 
                            <h2 style={{...pixelStyles.sectionTitle, fontSize: '12px', marginBottom: '3px', paddingBottom: '2px'}}>Game Info</h2> 
                            <div style={pixelStyles.gameInfoTextSmall}>ID: <span style={pixelStyles.infoValue}>{gameId || 'N/A'}</span></div> 
                            <div style={pixelStyles.gameInfoTextSmall}> 
                                Status: <span style={connectionStatus === 'Connected' ? pixelStyles.statusConnected : pixelStyles.statusDisconnected}>{connectionStatus}</span>
                            </div>
                    </section>

                        <section style={pixelStyles.playerSection}> 
                            <h2 style={pixelStyles.sectionTitle}>Players</h2>
                            <div 
                                id="playersIconContainer" 
                                style={{ 
                                    display: 'flex', 
                                    flexWrap: 'wrap', 
                                    gap: '10px',
                                    padding: '5px 0' 
                                }}
                            >
                            {Object.values(playerCards).sort((a,b) => a.my_player_id - b.my_player_id).map(playerData => (
                                    <div 
                                        key={playerData.my_player_id} 
                                        style={{
                                            ...pixelStyles.playerIcon,
                                            borderColor: activePlayerForBoard === playerData.my_player_id ? '#FFFF00' : '#00FFFF',
                                            outline: hoveredPlayer?.my_player_id === playerData.my_player_id ? '2px solid #FFFFFF' : 'none',
                                            opacity: playerData.is_bankrupt ? 0.5 : 1,
                                        }}
                                        onMouseEnter={(event) => handlePlayerIconMouseEnter(playerData, event)}
                                        onMouseLeave={handlePlayerAreaMouseLeave}
                                    >
                                        <svg viewBox="0 0 16 16" width="40px" height="40px" fill={playerColors[playerData.my_player_id % playerColors.length]} xmlns="http://www.w3.org/2000/svg" style={{ display: 'block', margin: 'auto' }}>
                                            <rect x="6" y="2" width="4" height="2" /> 
                                            <rect x="5" y="4" width="6" height="2" /> 
                                            <rect x="4" y="6" width="8" height="6" /> 
                                            <rect x="2" y="12" width="12" height="2" /> 
                                        </svg>
                                </div>
                            ))}
                                {Object.keys(playerCards).length === 0 && <p style={{...pixelStyles.infoText, fontSize: '10px'}}>Waiting...</p>}
                        </div>
                    </section>

                        {hoveredPlayer && playerTooltipPosition.visible && (
                            <div 
                                ref={playerTooltipRef}
                                style={{
                                    ...pixelStyles.playerDetailTooltip,
                                    top: `${playerTooltipPosition.top}px`,
                                    left: `${playerTooltipPosition.left}px`,
                                }}
                                onMouseLeave={handlePlayerAreaMouseLeave}
                            >
                                <h3 style={{...pixelStyles.playerCardTitle, fontSize: '14px'}}>{hoveredPlayer.my_name} (P{hoveredPlayer.my_player_id}) {hoveredPlayer.is_bankrupt ? <span style={{color:'#FF0000'}}>[KO]</span>: ''}</h3>
                                <p style={{...pixelStyles.infoText, fontSize: '11px'}}>Money: <span style={pixelStyles.infoValue}>${hoveredPlayer.my_money}</span></p>
                                <p style={{...pixelStyles.infoText, fontSize: '11px'}}>Position: <span style={pixelStyles.infoValue}>{hoveredPlayer.my_position_name} ({hoveredPlayer.my_position})</span></p>
                                <p style={{...pixelStyles.infoText, fontSize: '11px'}}>In Jail: <span style={pixelStyles.infoValue}>{String(hoveredPlayer.my_in_jail)} {hoveredPlayer.my_in_jail ? `(${hoveredPlayer.my_jail_turns_remaining} turns)` : ''}</span></p>
                                <p style={{...pixelStyles.infoText, fontSize: '11px'}}>GOOJ: C:<span style={pixelStyles.infoValue}>{hoveredPlayer.my_get_out_of_jail_cards?.chance || 0}</span>,CC:<span style={pixelStyles.infoValue}>{hoveredPlayer.my_get_out_of_jail_cards?.community_chest || 0}</span></p>
                                <p style={{...pixelStyles.infoText, fontSize: '11px'}}>Props ({(hoveredPlayer.my_properties_owned_ids || []).length}):</p>
                                <ul style={pixelStyles.playerPropertiesListSmall}>
                                    {(hoveredPlayer.my_properties_owned_ids || []).map(propId => {
                                        const prop = (hoveredPlayer.board_squares || []).find(sq => sq.id === propId);
                                        let details = prop ? prop.name : `ID: ${propId}`;
                                        if (prop) {
                                            if (prop.is_mortgaged) details += ' (M)';
                                            if (prop.num_houses === 5) details += ' (H)';
                                            else if (prop.num_houses > 0) details += ` (${prop.num_houses}h)`;
                                        }
                                        return <li key={propId} style={{...pixelStyles.propertyItem, fontSize: '9px'}}>{details}</li>;
                                    })}
                                    {(hoveredPlayer.my_properties_owned_ids || []).length === 0 && <li style={{...pixelStyles.propertyItem, fontSize: '9px'}}>None</li>}
                                </ul>
                            </div>
                        )}

                        <section style={pixelStyles.agentThoughtsSection}>  {/* Use specific style */}
                        <h2 style={pixelStyles.sectionTitle}>Agent Thoughts & Decisions</h2>
                        <div 
                            ref={agentThoughtsDivRef} 
                            style={pixelStyles.logDisplay} 
                            className="hide-scrollbar-log-display"
                        >
                            {agentThoughts.map((entry, index) => (
                                <div key={index} style={{
                                    ...pixelStyles.logEntry,
                                    ...(entry.type === 'error' ? pixelStyles.errorLog :
                                       entry.type === 'action-result' ? pixelStyles.actionResultLog : pixelStyles.infoLog)
                                }}>
                                    [{entry.timestamp}] {entry.message}
                                </div>
                            ))}
                            {agentThoughts.length === 0 && <p style={pixelStyles.infoText}>Waiting for agent actions...</p>}
                        </div>
                    </section>

                        <section style={pixelStyles.gameLogSection}> {/* Use specific style */}
                        <h2 style={pixelStyles.sectionTitle}>Game Log / Events</h2>
                        <div 
                            ref={gameLogDivRef} 
                            style={pixelStyles.logDisplay} 
                            className="hide-scrollbar-log-display"
                        >
                            {gameLog.map((entry, index) => (
                                <div key={index} style={{...pixelStyles.logEntry, ...(entry.type === 'error' ? pixelStyles.errorLog : entry.type === 'info' ? pixelStyles.infoLog: {}) }}>
                                    [{entry.timestamp}] {entry.message}
                                </div>
                            ))}
                            {gameLog.length === 0 && <p style={pixelStyles.infoText}>Waiting for game events...</p>}
                        </div>
                    </section>
                </div>
                </div>

                {/* Square Detail Tooltip */}
                {hoveredSquareDetails && squareTooltipPosition.visible && (
                    <div style={{
                        ...pixelStyles.squareDetailTooltip,
                        top: `${squareTooltipPosition.top}px`,
                        left: `${squareTooltipPosition.left}px`,
                    }}>
                        <h3 style={pixelStyles.tooltipTitle}>{hoveredSquareDetails.name}</h3>
                        
                        <div style={pixelStyles.tooltipSection}>
                            <span style={pixelStyles.tooltipDetail}>Type:</span>
                            <span style={pixelStyles.tooltipValue}>{hoveredSquareDetails.type?.replace('_', ' ') || 'N/A'}</span>
                        </div>

                        {(hoveredSquareDetails.type === 'PROPERTY' || hoveredSquareDetails.type === 'RAILROAD' || hoveredSquareDetails.type === 'UTILITY') && !hoveredSquareDetails.owner && hoveredSquareDetails.price && (
                            <div style={pixelStyles.tooltipSection}>
                                <span style={pixelStyles.tooltipDetail}>Price:</span>
                                <span style={pixelStyles.tooltipValue}>${hoveredSquareDetails.price}</span>
                            </div>
                        )}

                        {hoveredSquareDetails.tax_amount && (
                            <div style={pixelStyles.tooltipSection}>
                                <span style={pixelStyles.tooltipDetail}>Tax:</span>
                                <span style={pixelStyles.tooltipValue}>${hoveredSquareDetails.tax_amount}</span>
                            </div>
                        )}

                        {hoveredSquareDetails.owner && (
                            <div style={pixelStyles.tooltipSection}>
                                <span style={pixelStyles.tooltipDetail}>Owner:</span>
                                <span style={pixelStyles.tooltipValue}>{hoveredSquareDetails.owner.name} (P{hoveredSquareDetails.owner.id})</span>
                            </div>
                        )}

                        {(hoveredSquareDetails.type === 'PROPERTY' || hoveredSquareDetails.type === 'RAILROAD' || hoveredSquareDetails.type === 'UTILITY') && hoveredSquareDetails.owner && (
                             <div style={pixelStyles.tooltipSection}>
                                <span style={pixelStyles.tooltipDetail}>Status:</span>
                                <span style={pixelStyles.tooltipValue}>
                                    {hoveredSquareDetails.is_mortgaged ? 'Mortgaged' : 'Active'}
                                </span>
                            </div>
                        )}

                        {hoveredSquareDetails.type === 'PROPERTY' && hoveredSquareDetails.num_houses !== null && !hoveredSquareDetails.is_mortgaged && (
                            <div style={pixelStyles.tooltipSection}>
                                <span style={pixelStyles.tooltipDetail}>Development:</span>
                                <span style={pixelStyles.tooltipValue}>
                                    {hoveredSquareDetails.num_houses === 5 ? 'Hotel' : `${hoveredSquareDetails.num_houses} House(s)`}
                                </span>
                            </div>
                        )}
                        
                        {(hoveredSquareDetails.type === 'PROPERTY' || hoveredSquareDetails.type === 'RAILROAD' || hoveredSquareDetails.type === 'UTILITY' || hoveredSquareDetails.type === 'INCOME_TAX' || hoveredSquareDetails.type === 'LUXURY_TAX') && (
                            <div style={pixelStyles.tooltipSection}>
                                <span style={pixelStyles.tooltipDetail}>Rent/Cost:</span>
                                <span style={pixelStyles.tooltipValue}>{hoveredSquareDetails.current_rent_display}</span>
                            </div>
                        )}


                        {/* Raw data for debugging if needed - remove for production */}
                        {/* <pre style={{fontSize:'8px', maxHeight:'50px', overflowY:'auto', marginTop:'10px', backgroundColor:'#000', padding:'3px'}}>
                            {JSON.stringify(hoveredSquareDetails, null, 2)}
                        </pre> */}
                    </div>
                )}
            </div>
        </>
    );
} 