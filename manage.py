#!/usr/bin/env python3
"""Alina Bot Management Script"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta


def reset_database():
    """Reset database to initial state"""
    db_path = os.getenv("DB_PATH", "alina.db")
    if os.path.exists(db_path):
        response = input(f"Delete {db_path}? [y/N]: ")
        if response.lower() == 'y':
            os.remove(db_path)
            print(f"Database {db_path} deleted")
    else:
        print("Database not found")


def show_stats():
    """Show database statistics"""
    db_path = os.getenv("DB_PATH", "alina.db")
    if not os.path.exists(db_path):
        print("Database not found")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # User stats
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM messages")
    messages = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE is_active = 1 AND end_date > datetime('now')")
    active_subs = cursor.fetchone()[0]
    
    print(f"Database Statistics:")
    print(f"  Users: {users}")
    print(f"  Messages: {messages}")
    print(f"  Active Subscriptions: {active_subs}")
    
    conn.close()


def add_test_subscription(user_id: int, days: int = 30):
    """Add test subscription for user"""
    db_path = os.getenv("DB_PATH", "alina.db")
    if not os.path.exists(db_path):
        print("Database not found")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    end_date = datetime.now() + timedelta(days=days)
    cursor.execute("""
        INSERT INTO subscriptions (user_id, plan_type, end_date, is_active)
        VALUES (?, 'test', ?, 1)
    """, (user_id, end_date))
    
    conn.commit()
    conn.close()
    
    print(f"Added {days}-day subscription for user {user_id}")


def run_bot():
    """Run the bot"""
    from bot import main
    main()


def main():
    parser = argparse.ArgumentParser(description="Alina Bot Manager")
    parser.add_argument("command", choices=["run", "stats", "reset-db", "add-sub"])
    parser.add_argument("--user-id", type=int, help="User ID for subscription")
    parser.add_argument("--days", type=int, default=30, help="Subscription days")
    
    args = parser.parse_args()
    
    # Load environment
    from dotenv import load_dotenv
    load_dotenv()
    
    if args.command == "run":
        run_bot()
    elif args.command == "stats":
        show_stats()
    elif args.command == "reset-db":
        reset_database()
    elif args.command == "add-sub":
        if not args.user_id:
            print("--user-id required for add-sub command")
            sys.exit(1)
        add_test_subscription(args.user_id, args.days)


if __name__ == "__main__":
    main()
