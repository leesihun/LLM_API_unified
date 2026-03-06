"""
Script to create multiple users
Run this to bulk-create users for testing
"""
import requests

# Configuration
API_URL = "http://localhost:10007"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "administrator"

# Users to create
USERS = [
    {"username": "user1", "password": "password123", "role": "user"},
    {"username": "user2", "password": "password123", "role": "user"},
    {"username": "user3", "password": "password123", "role": "user"},
    {"username": "testuser", "password": "testpass", "role": "user"},
]

def login_admin():
    """Login as admin and get token"""
    response = requests.post(
        f"{API_URL}/api/auth/login",
        data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        raise Exception(f"Admin login failed: {response.status_code}")

def create_user(username, password, role, token):
    """Create a single user"""
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(
        f"{API_URL}/api/admin/users",
        json={"username": username, "password": password, "role": role},
        headers=headers
    )

    return response.status_code == 200, response.json()

def main():
    print("=" * 70)
    print("User Creation Script")
    print("=" * 70)
    print()

    # Login as admin
    print("Logging in as admin...")
    try:
        token = login_admin()
        print("✓ Admin login successful")
        print()
    except Exception as e:
        print(f"✗ Failed to login: {e}")
        return

    # Create users
    print(f"Creating {len(USERS)} users...")
    print()

    for user in USERS:
        success, response = create_user(
            user["username"],
            user["password"],
            user["role"],
            token
        )

        if success:
            print(f"✓ Created: {user['username']} (role: {user['role']})")
        else:
            error = response.get("detail", "Unknown error")
            if "already exists" in str(error).lower():
                print(f"⊘ Skipped: {user['username']} (already exists)")
            else:
                print(f"✗ Failed: {user['username']} - {error}")

    print()
    print("=" * 70)
    print("Done!")
    print("=" * 70)
    print()

    # List all users
    print("Fetching all users...")
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{API_URL}/api/admin/users", headers=headers)

    if response.status_code == 200:
        users = response.json()
        print(f"Total users in system: {len(users)}")
        print()
        for u in users:
            print(f"  - {u['username']} (role: {u['role']}, created: {u['created_at']})")

    print()

if __name__ == "__main__":
    main()
