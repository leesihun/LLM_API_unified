"""
Create a user directly via the database
Useful for initial setup or when API is not available
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.core.database import db
from passlib.context import CryptContext

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_user(username: str, password: str, role: str = "user"):
    """
    Create a user directly in the database

    Args:
        username: Username
        password: Plain text password (will be hashed)
        role: User role ("user" or "admin")
    """
    # Validate password length (bcrypt has 72-byte limit)
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        print(f"✗ Error: Password exceeds 72 bytes ({len(password_bytes)} bytes)")
        print("  Please use a shorter password")
        return False

    # Hash password
    password_hash = pwd_context.hash(password)

    # Create user
    success = db.create_user(username, password_hash, role)

    if success:
        print(f"✓ User '{username}' created successfully!")
        print(f"  Role: {role}")
        return True
    else:
        print(f"✗ Failed to create user '{username}'")
        print("  User may already exist")
        return False

def list_users():
    """List all users in the database"""
    import sqlite3

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username, role, created_at FROM users ORDER BY created_at")
            users = cursor.fetchall()

            if users:
                print()
                print("Current users in database:")
                print("-" * 60)
                for user in users:
                    print(f"  {user['username']:20} | {user['role']:10} | {user['created_at']}")
                print("-" * 60)
                print(f"Total: {len(users)} users")
            else:
                print("No users found in database")

    except Exception as e:
        print(f"Error listing users: {e}")

def main():
    """Interactive user creation"""
    print("=" * 70)
    print("Direct Database User Creation")
    print("=" * 70)
    print()

    # Show existing users
    list_users()
    print()

    # Get user input
    print("Create a new user:")
    username = input("  Username: ").strip()

    if not username:
        print("✗ Username cannot be empty")
        return

    password = input("  Password: ").strip()

    if not password:
        print("✗ Password cannot be empty")
        return

    role = input("  Role (user/admin) [user]: ").strip().lower() or "user"

    if role not in ["user", "admin"]:
        print("✗ Invalid role. Must be 'user' or 'admin'")
        return

    print()

    # Create user
    success = create_user(username, password, role)

    if success:
        print()
        list_users()

    print()

if __name__ == "__main__":
    main()
