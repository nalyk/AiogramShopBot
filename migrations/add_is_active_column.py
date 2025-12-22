"""
Migration script: Add is_active column to categories table.

This migration adds the is_active column for archive/soft-delete functionality.
Categories with sold items can be archived (is_active=0) instead of deleted.

IMPORTANT: Backup your database before running this migration!

Usage:
    python -m migrations.add_is_active_column
"""

import shutil
import sqlite3
import os


def migrate_database(db_path: str = "shop.db"):
    """
    Add is_active column to categories table.
    """
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return False

    # Create backup
    backup_path = f"{db_path}.is_active_backup"
    print(f"Creating backup at {backup_path}...")
    shutil.copy2(db_path, backup_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if is_active column already exists
        cursor.execute("PRAGMA table_info(categories)")
        columns = {col[1] for col in cursor.fetchall()}

        if 'is_active' in columns:
            print("is_active column already exists. Migration not needed.")
            return True

        print("Adding is_active column to categories table...")
        cursor.execute("ALTER TABLE categories ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL")

        # Verify the migration
        cursor.execute("PRAGMA table_info(categories)")
        columns = {col[1] for col in cursor.fetchall()}

        if 'is_active' not in columns:
            raise Exception("Failed to add is_active column")

        conn.commit()
        print("\n✅ Migration completed successfully!")
        print(f"Backup saved at: {backup_path}")
        print("All existing categories have is_active=1 (active)")
        return True

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        print(f"Transaction rolled back - database unchanged.")
        print(f"If needed, manual restore available at: {backup_path}")
        return False

    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    db_path = sys.argv[1] if len(sys.argv) > 1 else "shop.db"
    success = migrate_database(db_path)
    sys.exit(0 if success else 1)
