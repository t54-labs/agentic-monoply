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

# 配置
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
        """打印API测试结果"""
        status_color = '\033[92m' if response.status_code < 400 else '\033[91m'  # 绿色/红色
        reset_color = '\033[0m'
        
        print(f"\n{'='*60}")
        print(f"{status_color}[{method}] {endpoint} - {response.status_code}{reset_color}")
        
        if data:
            print(f"请求数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        try:
            result = response.json()
            print(f"响应数据: {json.dumps(result, indent=2, ensure_ascii=False)}")
        except:
            print(f"响应文本: {response.text}")
        
        print(f"响应时间: {response.elapsed.total_seconds():.3f}s")
        print(f"{'='*60}")
    
    # 基础API测试
    def test_lobby_games(self):
        """测试获取游戏列表"""
        try:
            response = self.session.get(f"{self.base_url}/api/lobby/games")
            self.print_result("/api/lobby/games", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试获取游戏列表失败: {e}")
            return None
    
    def test_board_layout(self, game_id: str = "test_game"):
        """测试获取棋盘布局"""
        try:
            response = self.session.get(f"{self.base_url}/api/game/{game_id}/board_layout")
            self.print_result(f"/api/game/{game_id}/board_layout", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试获取棋盘布局失败: {e}")
            return None
    
    # 管理员API测试
    def test_games_status(self):
        """测试获取游戏状态"""
        try:
            response = self.session.get(f"{self.base_url}/api/admin/games/status")
            self.print_result("/api/admin/games/status", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试获取游戏状态失败: {e}")
            return None
    
    def test_create_game(self):
        """测试创建新游戏"""
        try:
            response = self.session.post(f"{self.base_url}/api/admin/games/create")
            self.print_result("/api/admin/games/create", "POST", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试创建游戏失败: {e}")
            return None
    
    def test_trigger_maintenance(self):
        """测试触发维护"""
        try:
            response = self.session.post(f"{self.base_url}/api/admin/games/maintain")
            self.print_result("/api/admin/games/maintain", "POST", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试触发维护失败: {e}")
            return None
    
    def test_get_config(self):
        """测试获取配置"""
        try:
            response = self.session.get(f"{self.base_url}/api/admin/config")
            self.print_result("/api/admin/config", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试获取配置失败: {e}")
            return None
    
    def test_update_config(self, config_data: Dict[str, Any]):
        """测试更新配置"""
        try:
            response = self.session.post(
                f"{self.base_url}/api/admin/config",
                json=config_data
            )
            self.print_result("/api/admin/config", "POST", response, config_data)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试更新配置失败: {e}")
            return None
    
    def test_create_default_agents(self):
        """测试创建默认代理"""
        try:
            response = self.session.post(f"{self.base_url}/api/admin/agents/create_random")
            self.print_result("/api/admin/agents/create_random", "POST", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试创建默认代理失败: {e}")
            return None
    
    def test_get_agents(self):
        """测试获取代理列表"""
        try:
            response = self.session.get(f"{self.base_url}/api/admin/agents")
            self.print_result("/api/admin/agents", "GET", response)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试获取代理列表失败: {e}")
            return None
    
    def test_create_game_tokens(self, token_data: Dict[str, Any]):
        """测试创建游戏令牌账户"""
        try:
            response = self.session.post(
                f"{self.base_url}/api/admin/agents/create_game_tokens",
                json=token_data
            )
            self.print_result("/api/admin/agents/create_game_tokens", "POST", response, token_data)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试创建游戏令牌失败: {e}")
            return None
    
    def test_reset_agent_balance(self, agent_id: int, balance_data: Dict[str, Any]):
        """测试重置代理余额"""
        try:
            response = self.session.post(
                f"{self.base_url}/api/admin/agents/{agent_id}/reset_game_balance",
                json=balance_data
            )
            self.print_result(f"/api/admin/agents/{agent_id}/reset_game_balance", "POST", response, balance_data)
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            print(f"❌ 测试重置代理余额失败: {e}")
            return None

class WebSocketTester:
    def __init__(self, ws_base_url: str = WS_BASE_URL):
        self.ws_base_url = ws_base_url
        self.messages = []
        self.connected = False
    
    def on_message(self, ws, message):
        """WebSocket消息回调"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n🔄 [{timestamp}] WebSocket收到消息:")
        try:
            data = json.loads(message)
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except:
            print(message)
        self.messages.append(message)
    
    def on_error(self, ws, error):
        """WebSocket错误回调"""
        print(f"❌ WebSocket错误: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """WebSocket关闭回调"""
        print(f"🔒 WebSocket连接关闭: {close_status_code} - {close_msg}")
        self.connected = False
    
    def on_open(self, ws):
        """WebSocket打开回调"""
        print("✅ WebSocket连接已建立")
        self.connected = True
    
    def test_lobby_websocket(self, duration: int = 10):
        """测试大厅WebSocket"""
        print(f"\n🚀 测试大厅WebSocket连接 (持续{duration}秒)...")
        
        try:
            ws = websocket.WebSocketApp(
                f"{self.ws_base_url}/ws/lobby",
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_open=self.on_open
            )
            
            # 在独立线程中运行WebSocket
            wst = threading.Thread(target=ws.run_forever)
            wst.daemon = True
            wst.start()
            
            # 等待指定时间
            time.sleep(duration)
            
            # 关闭连接
            ws.close()
            print(f"📊 总共收到 {len(self.messages)} 条消息")
            
        except Exception as e:
            print(f"❌ 测试大厅WebSocket失败: {e}")
    
    def test_game_websocket(self, game_id: str = "test_game", duration: int = 10):
        """测试游戏WebSocket"""
        print(f"\n🚀 测试游戏WebSocket连接 (游戏ID: {game_id}, 持续{duration}秒)...")
        
        try:
            ws = websocket.WebSocketApp(
                f"{self.ws_base_url}/ws/game/{game_id}",
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_open=self.on_open
            )
            
            # 在独立线程中运行WebSocket
            wst = threading.Thread(target=ws.run_forever)
            wst.daemon = True
            wst.start()
            
            # 等待指定时间
            time.sleep(duration)
            
            # 关闭连接
            ws.close()
            print(f"📊 总共收到 {len(self.messages)} 条消息")
            
        except Exception as e:
            print(f"❌ 测试游戏WebSocket失败: {e}")

def main():
    """主测试函数"""
    print("🎯 垄断游戏平台API测试工具")
    print("=" * 50)
    
    # 检查服务器是否可访问
    try:
        response = requests.get(f"{BASE_URL}/api/admin/games/status", timeout=5)
        print(f"✅ 服务器连接正常 (状态码: {response.status_code})")
    except Exception as e:
        print(f"❌ 无法连接到服务器: {e}")
        print(f"请确保服务器在 {BASE_URL} 运行")
        return
    
    # HTTP API测试
    print("\n🔍 开始HTTP API测试...")
    api_tester = APITester()
    
    # 基础API测试
    print("\n📋 基础API测试:")
    api_tester.test_lobby_games()
    api_tester.test_board_layout()
    
    # 管理员API测试
    print("\n🔧 管理员API测试:")
    
    # 获取游戏状态
    games_status = api_tester.test_games_status()
    
    # 获取配置
    config = api_tester.test_get_config()
    
    # 获取代理列表
    agents = api_tester.test_get_agents()
    
    # 创建默认代理（如果没有代理）
    if agents and len(agents.get('agents', [])) == 0:
        print("\n📝 没有发现代理，创建默认代理...")
        api_tester.test_create_default_agents()
        time.sleep(2)  # 等待创建完成
        agents = api_tester.test_get_agents()  # 重新获取代理列表
    
    # # 测试配置更新
    # if config:
    #     test_config = {
    #         "concurrent_games": 1,
    #         "auto_restart": True,
    #         "maintenance_interval": 60
    #     }
    #     api_tester.test_update_config(test_config)
    
    # # 测试创建游戏令牌
    # if agents and agents.get('agents'):
    #     token_data = {
    #         "game_token": "AMNP",
    #         "initial_balance": 1500.0,
    #         "network": "solana"
    #     }
    #     api_tester.test_create_game_tokens(token_data)
    
    # # 测试重置代理余额
    # if agents and agents.get('agents'):
    #     first_agent = agents['agents'][0]
    #     balance_data = {
    #         "game_token": "AMNP",
    #         "new_balance": 2000.0
    #     }
    #     api_tester.test_reset_agent_balance(first_agent['id'], balance_data)
    
    # # 创建新游戏
    # api_tester.test_create_game()
    
    # # 触发维护
    # api_tester.test_trigger_maintenance()
    
    # # WebSocket测试
    # print("\n🌐 开始WebSocket测试...")
    # ws_tester = WebSocketTester()
    
    # # 测试大厅WebSocket
    # ws_tester.test_lobby_websocket(duration=5)
    
    # # 如果有游戏在运行，测试游戏WebSocket
    # if games_status and games_status.get('games'):
    #     first_game = games_status['games'][0]
    #     game_uid = first_game.get('game_uid', 'test_game')
    #     ws_tester.test_game_websocket(game_uid, duration=5)
    # else:
    #     ws_tester.test_game_websocket('test_game', duration=5)
    
    print("\n✅ 所有测试完成!")
    print("=" * 50)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc() 