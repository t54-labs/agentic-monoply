#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地API测试脚本
用于测试垄断游戏平台的所有API接口
"""

import requests
import json
import time
import asyncio
import websocket
import threading
from datetime import datetime
from typing import Dict, Any, Optional
import sys

# config
BASE_URL = "http://localhost:8000"
# BASE_URL = "https://agentic-monopoly-a8125b787674.herokuapp.com/"
WS_BASE_URL = "ws://localhost:8000"

class APITester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def print_result(self, endpoint: str, method: str, response: requests.Response, data: Any = None):
        status_color = '\033[92m' if response.status_code < 400 else '\033[91m'
        reset_color = '\033[0m'
        
        print(f"\n{'='*60}")
        print(f"{status_color}[{method}] {endpoint} - {response.status_code}{reset_color}")
        
        if data:
            print(f"request data: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        try:
            result = response.json()
            print(f"response data: {json.dumps(result, indent=2, ensure_ascii=False)}")
        except:
            print(f"response text: {response.text}")
        
        print(f"response time: {response.elapsed.total_seconds():.3f}s")
        print(f"{'='*60}")
    
    def test_lobby_games(self):
        try:
            response = self.session.get(f"{self.base_url}/api/lobby/games")
            self.print_result("/api/lobby/games", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test get lobby games failed: {e}")
            return None
    
    def test_board_layout(self, game_id: str = "test_game"):
        try:
            response = self.session.get(f"{self.base_url}/api/game/{game_id}/board_layout")
            self.print_result(f"/api/game/{game_id}/board_layout", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test get board layout failed: {e}")
            return None
    
    def test_games_status(self):
        try:
            response = self.session.get(f"{self.base_url}/api/admin/games/status")
            self.print_result("/api/admin/games/status", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test get games status failed: {e}")
            return None
    
    def test_create_game(self):
        try:
            response = self.session.post(f"{self.base_url}/api/admin/games/create")
            self.print_result("/api/admin/games/create", "POST", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test create game failed: {e}")
            return None
    
    def test_trigger_maintenance(self):
        try:
            response = self.session.post(f"{self.base_url}/api/admin/games/maintain")
            self.print_result("/api/admin/games/maintain", "POST", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test trigger maintenance failed: {e}")
            return None
    
    def test_get_config(self):  
        try:
            response = self.session.get(f"{self.base_url}/api/admin/config")
            self.print_result("/api/admin/config", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test get config failed: {e}")
            return None
    
    def test_update_config(self, config_data: Dict[str, Any]):
        try:
            response = self.session.post(
                f"{self.base_url}/api/admin/config",
                json=config_data
            )
            self.print_result("/api/admin/config", "POST", response, config_data)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test update config failed: {e}")
            return None
    
    def test_create_default_agents(self):
        try:
            response = self.session.post(f"{self.base_url}/api/admin/agents/create_random")
            self.print_result("/api/admin/agents/create_random", "POST", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test create default agents failed: {e}")
            return None
    
    def test_get_agents(self):
        try:
            response = self.session.get(f"{self.base_url}/api/admin/agents")
            self.print_result("/api/admin/agents", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test get agents failed: {e}")
            return None
    
    def test_create_game_tokens(self, token_data: Dict[str, Any]):
        try:
            response = self.session.post(
                f"{self.base_url}/api/admin/agents/create_game_tokens",
                json=token_data
            )
            self.print_result("/api/admin/agents/create_game_tokens", "POST", response, token_data)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test create game tokens failed: {e}")
            return None
    
    def test_reset_agent_balance(self, agent_id: int, balance_data: Dict[str, Any]):
        try:
            response = self.session.post(
                f"{self.base_url}/api/admin/agents/{agent_id}/reset_game_balance",
                json=balance_data
            )
            self.print_result(f"/api/admin/agents/{agent_id}/reset_game_balance", "POST", response, balance_data)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ test reset agent balance failed: {e}")
            return None

class WebSocketTester:
    def __init__(self, ws_base_url: str = WS_BASE_URL):
        self.ws_base_url = ws_base_url
        self.messages = []
        self.connected = False
    
    def on_message(self, ws, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n🔄 [{timestamp}] WebSocket received message:")
        try:
            data = json.loads(message)
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except:
            print(message)
        self.messages.append(message)
    
    def on_error(self, ws, error):
        print(f"❌ WebSocket error: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        print(f"🔒 WebSocket connection closed: {close_status_code} - {close_msg}")
        self.connected = False
    
    def on_open(self, ws):
        print("✅ WebSocket connection established")
        self.connected = True
    
    def test_lobby_websocket(self, duration: int = 10):
        print(f"\n🚀 test lobby websocket (duration: {duration} seconds)...")
        
        try:
            ws = websocket.WebSocketApp(
                f"{self.ws_base_url}/ws/lobby",
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_open=self.on_open
            )
            
            wst = threading.Thread(target=ws.run_forever)
            wst.daemon = True
            wst.start()
            
            time.sleep(duration)
            
            ws.close()
            print(f"📊 total messages received: {len(self.messages)}")
            
        except Exception as e:
            print(f"❌ test lobby websocket failed: {e}")
    
    def test_game_websocket(self, game_id: str = "test_game", duration: int = 10):
        print(f"\n🚀 test game websocket (game_id: {game_id}, duration: {duration} seconds)...")
        
        try:
            ws = websocket.WebSocketApp(
                f"{self.ws_base_url}/ws/game/{game_id}",
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_open=self.on_open
            )
            
            wst = threading.Thread(target=ws.run_forever)
            wst.daemon = True
            wst.start()
            
            time.sleep(duration)
            
            ws.close()
            print(f"📊 total messages received: {len(self.messages)}")
            
        except Exception as e:
            print(f"❌ test game websocket failed: {e}")

def main():
    print("🎯 monopoly game platform API test tool")
    print("=" * 50)
    
    try:
        response = requests.get(f"{BASE_URL}/api/admin/games/status", timeout=5)
        print(f"✅ server connected (status code: {response.status_code})")
    except Exception as e:
        print(f"❌ cannot connect to server: {e}")
        print(f"please ensure the server is running at {BASE_URL}")
        return
    
    print("\n🔍 start HTTP API test...")
    api_tester = APITester()
    
    print("\n📋 start basic API test:")
    api_tester.test_lobby_games()
    api_tester.test_board_layout()
    
    print("\n🔧 start admin API test:")
    
    games_status = api_tester.test_games_status()
    
    config = api_tester.test_get_config()
    
    agents = api_tester.test_get_agents()
    
    if agents and len(agents.get('agents', [])) == 0:
        print("\n📝 no agents found, creating default agents...")
        api_tester.test_create_default_agents()
        time.sleep(2)
        agents = api_tester.test_get_agents()
    
    # if config:
    #     test_config = {
    #         "concurrent_games": 1,
    #         "auto_restart": True,
    #         "maintenance_interval": 60
    #     }
    #     api_tester.test_update_config(test_config)
    
    # if agents and agents.get('agents'):
    #     token_data = {
    #         "game_token": "AMNP",
    #         "initial_balance": 1500.0,
    #         "network": "solana"
    #     }
    #     api_tester.test_create_game_tokens(token_data)
    
    # if agents and agents.get('agents'):
    #     first_agent = agents['agents'][0]
    #     balance_data = {
    #         "game_token": "AMNP",
    #         "new_balance": 2000.0
    #     }
    #     api_tester.test_reset_agent_balance(first_agent['id'], balance_data)
    
    # api_tester.test_create_game()
    
    # api_tester.test_trigger_maintenance()
    
    # print("\n🌐 start websocket test...")
    # ws_tester = WebSocketTester()
    
    # ws_tester.test_lobby_websocket(duration=5)
    
    # if games_status and games_status.get('games'):
    #     first_game = games_status['games'][0]
    #     game_uid = first_game.get('game_uid', 'test_game')
    #     ws_tester.test_game_websocket(game_uid, duration=5)
    # else:
    #     ws_tester.test_game_websocket('test_game', duration=5)
    
    print("\n✅ all tests completed!")
    print("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ test interrupted by user")
    except Exception as e:
        print(f"\n❌ test error: {e}")
        import traceback
        traceback.print_exc() 