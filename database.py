# database.py
import os
import datetime
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Text, ForeignKey, DateTime, JSON
from sqlalchemy.sql import func
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "123456")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "monoply") 

# Construct PostgreSQL DATABASE_URL
DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
metadata = MetaData()

games_table = Table(
    "games",
    metadata,
    Column("id", Integer, primary_key=True, index=True, autoincrement=True), 
    Column("game_uid", String, unique=True, index=True), 
    Column("start_time", DateTime, default=func.now()),
    Column("end_time", DateTime, nullable=True),
    Column("status", String, default="started"), 
    Column("num_players", Integer),
    Column("winner_player_id", Integer, ForeignKey("players.id", name="fk_games_winner_player_id"), nullable=True),
    Column("max_turns", Integer, nullable=True)
)

players_table = Table(
    "players",
    metadata,
    Column("id", Integer, primary_key=True, index=True, autoincrement=True), 
    Column("game_id", Integer, ForeignKey("games.id", name="fk_players_game_id"), nullable=False),
    Column("player_index_in_game", Integer, nullable=False), # 0, 1, 2, 3 for a game
    Column("agent_name", String),
    Column("agent_type", String, nullable=True) 
)

game_turns_table = Table(
    "game_turns",
    metadata,
    Column("id", Integer, primary_key=True, index=True, autoincrement=True),
    Column("game_id", Integer, ForeignKey("games.id", name="fk_turns_game_id"), nullable=False, index=True),
    Column("turn_number", Integer, nullable=False),
    Column("acting_player_game_index", Integer, nullable=False), # Player index (0-3) in this game whose turn it is
    Column("game_state_json", Text), 
    Column("timestamp", DateTime, default=func.now())
)

agent_actions_table = Table(
    "agent_actions",
    metadata,
    Column("id", Integer, primary_key=True, index=True, autoincrement=True),
    Column("game_id", Integer, ForeignKey("games.id", name="fk_actions_game_id"), nullable=False, index=True),
    Column("game_turn_id", Integer, ForeignKey("game_turns.id", name="fk_actions_game_turn_id"), nullable=True),
    Column("player_db_id", Integer, ForeignKey("players.id", name="fk_actions_player_db_id"), nullable=False),
    Column("player_game_index", Integer, nullable=False),
    Column("gc_turn_number", Integer),
    Column("action_sequence_in_gc_turn", Integer, default=1),
    Column("pending_decision_type_before", String, nullable=True),
    Column("pending_decision_context_json_before", Text, nullable=True),
    Column("available_actions_json_before", Text, nullable=True),
    Column("agent_thoughts_text", Text, nullable=True),
    Column("llm_raw_response_text", Text, nullable=True),
    Column("parsed_action_json_str", Text, nullable=True),
    Column("chosen_tool_name", String),
    Column("tool_parameters_json", Text, nullable=True),
    Column("action_result_status", String, nullable=True),
    Column("action_result_message", Text, nullable=True),
    Column("timestamp", DateTime, default=func.now())
)

def create_db_and_tables():
    try:
        # Check if the database exists, create if not (for PostgreSQL, DB itself needs to exist)
        # This is more about creating tables within an existing DB.
        # For PostgreSQL, usually the database (e.g., 'doudizhu') must be created manually first.
        # conn = engine.connect() 
        # conn.execute("commit") # Some drivers need this for CREATE DATABASE if it were here
        # conn.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}") # This syntax is MySQL specific
        # conn.close()
        print(f"Attempting to connect to database '{DB_NAME}' and create tables if they don't exist...")
        metadata.create_all(engine) # This creates tables
        print("Database tables checked/created successfully.")
    except Exception as e:
        print(f"Error connecting to database or creating tables: {e}")
        print("Please ensure the PostgreSQL server is running, the database '{DB_NAME}' exists, and connection parameters are correct.")

if __name__ == '__main__':
    # This allows you to create the DB and tables by running: python database.py
    create_db_and_tables() 