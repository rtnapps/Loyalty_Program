#!/usr/bin/env python3
"""
Initialize SQLite Database for Tier 3 Loyalty System

This script creates all necessary tables in the SQLite database
by executing the SQL queries from create_loyalty_tables.sql
"""

import sqlite3
import os

# Database file path
DB_FILE = "loyalty.db"

def init_database():
    """Initialize the SQLite database with all required tables"""
    
    # Check if database file exists
    db_exists = os.path.exists(DB_FILE)
    
    # Connect to database (will create if doesn't exist)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Read SQL file
        sql_file = "create_loyalty_tables.sql"
        if not os.path.exists(sql_file):
            print(f"Error: SQL file '{sql_file}' not found!")
            return False
        
        with open(sql_file, 'r', encoding='utf-8') as f:
            sql_script = f.read()
        
        # Execute SQL script
        # SQLite's executescript() can handle multiple statements
        cursor.executescript(sql_script)
        
        # Commit changes
        conn.commit()
        
        if db_exists:
            print(f"✅ Database '{DB_FILE}' updated successfully!")
        else:
            print(f"✅ Database '{DB_FILE}' created successfully!")
        
        # Verify tables were created
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            ORDER BY name
        """)
        tables = cursor.fetchall()
        
        print(f"\n📊 Created/Verified {len(tables)} tables:")
        for table in tables:
            print(f"   - {table[0]}")
        
        # Check for views
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='view' 
            ORDER BY name
        """)
        views = cursor.fetchall()
        
        if views:
            print(f"\n📋 Created/Verified {len(views)} views:")
            for view in views:
                print(f"   - {view[0]}")
        
        # Check for triggers
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='trigger' 
            ORDER BY name
        """)
        triggers = cursor.fetchall()
        
        if triggers:
            print(f"\n⚙️  Created/Verified {len(triggers)} triggers:")
            for trigger in triggers:
                print(f"   - {trigger[0]}")
        
        # Check if format_type column exists (for existing databases that need migration)
        try:
            cursor.execute("PRAGMA table_info(customer_profiles)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'format_type' not in columns:
                print("⚠️  Note: format_type column missing. Run 'python migrate_add_format_type.py' to add it.")
            else:
                print("✅ format_type column verified")
        except Exception as e:
            # Not critical, continue
            pass
        
        print("\n✅ Database initialization complete!")
        return True
        
    except sqlite3.Error as e:
        print(f"❌ SQLite error: {e}")
        conn.rollback()
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Tier 3 Loyalty System - Database Initialization")
    print("=" * 60)
    print()
    
    success = init_database()
    
    if success:
        print("\n" + "=" * 60)
        print("Next steps:")
        print("1. Update tier3_step1.py to use SQLite database")
        print("2. Update app.py to use database for customer tracking")
        print("3. Test the loyalty ID validation with database persistence")
        print("=" * 60)
    else:
        print("\n❌ Database initialization failed. Please check the errors above.")