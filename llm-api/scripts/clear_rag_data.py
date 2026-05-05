"""
Clear RAG Data Utility Script

Use this script to clear RAG indices, documents, and metadata after switching embedding models.
Since bge-m3 (1024-dim) is incompatible with old bge-base-en (768-dim) indices,
all existing FAISS indices must be rebuilt by re-uploading documents.

Usage:
    python clear_rag_data.py [--all] [--user USERNAME] [--uploads]

Options:
    --all          Clear all RAG data for all users (requires confirmation)
    --user USER    Clear RAG data for specific user only
    --uploads      Also clear user uploads directory (permanent data loss!)
    --force        Skip confirmation prompts

Examples:
    python clear_rag_data.py --all
    python clear_rag_data.py --user admin
    python clear_rag_data.py --user admin --uploads --force
"""
import shutil
import argparse
from pathlib import Path
import config


def confirm_action(message: str) -> bool:
    """Ask for user confirmation"""
    response = input(f"{message} (yes/no): ").lower().strip()
    return response in ["yes", "y"]


def clear_rag_for_user(username: str, clear_uploads: bool = False):
    """Clear RAG data for a specific user"""
    print(f"\n[CLEARING] RAG data for user: {username}")
    
    # RAG directories
    user_docs_dir = config.RAG_DOCUMENTS_DIR / username
    user_index_dir = config.RAG_INDEX_DIR / username
    user_metadata_dir = config.RAG_METADATA_DIR / username
    
    dirs_to_clear = [
        (user_docs_dir, "Documents"),
        (user_index_dir, "FAISS Indices"),
        (user_metadata_dir, "Metadata")
    ]
    
    if clear_uploads:
        user_uploads_dir = config.UPLOAD_DIR / username
        dirs_to_clear.append((user_uploads_dir, "User Uploads"))
    
    for dir_path, name in dirs_to_clear:
        if dir_path.exists():
            try:
                shutil.rmtree(dir_path)
                print(f"  [OK] Cleared {name}: {dir_path}")
            except Exception as e:
                print(f"  [ERROR] Failed to clear {name}: {e}")
        else:
            print(f"  [SKIP] {name} doesn't exist: {dir_path}")


def clear_all_rag_data(clear_uploads: bool = False):
    """Clear RAG data for all users"""
    print("\n[CLEARING] RAG data for ALL users")
    
    # Get all user directories from RAG metadata
    if not config.RAG_METADATA_DIR.exists():
        print("  [INFO] No RAG metadata directory found")
        return
    
    usernames = set()
    for user_dir in config.RAG_METADATA_DIR.iterdir():
        if user_dir.is_dir():
            usernames.add(user_dir.name)
    
    if not usernames:
        print("  [INFO] No users found with RAG data")
        return
    
    print(f"  Found {len(usernames)} users with RAG data: {', '.join(sorted(usernames))}")
    
    for username in sorted(usernames):
        clear_rag_for_user(username, clear_uploads)


def main():
    parser = argparse.ArgumentParser(
        description="Clear RAG data after embedding model change",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Clear all RAG data (preserves uploads):
    python clear_rag_data.py --all
  
  Clear specific user's RAG data:
    python clear_rag_data.py --user admin
  
  Clear everything including uploads:
    python clear_rag_data.py --all --uploads --force
        """
    )
    
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clear RAG data for all users"
    )
    parser.add_argument(
        "--user",
        type=str,
        metavar="USERNAME",
        help="Clear RAG data for specific user only"
    )
    parser.add_argument(
        "--uploads",
        action="store_true",
        help="Also clear user uploads directory (CAUTION: permanent data loss!)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.all and not args.user:
        parser.error("Must specify either --all or --user USERNAME")
    
    if args.all and args.user:
        parser.error("Cannot use --all and --user together")
    
    # Show warning and get confirmation
    print("=" * 80)
    print("RAG DATA CLEARING UTILITY")
    print("=" * 80)
    print("\nWARNING: This will delete:")
    print("  - RAG document collections")
    print("  - FAISS vector indices")
    print("  - Collection metadata")
    if args.uploads:
        print("  - User uploaded files (PERMANENT DATA LOSS!)")
    
    print("\nReason: Embedding model changed from bge-base-en (768-dim) to bge-m3 (1024-dim)")
    print("All documents must be re-uploaded to rebuild indices with new embeddings.")
    
    if args.all:
        print(f"\nTarget: ALL users")
    else:
        print(f"\nTarget: User '{args.user}'")
    
    # Confirmation
    if not args.force:
        print()
        if not confirm_action("Proceed with clearing?"):
            print("\n[CANCELLED] No data was deleted.")
            return
        
        if args.uploads:
            print("\n[!] You are about to delete user uploads (original files)!")
            if not confirm_action("Are you ABSOLUTELY SURE?"):
                print("\n[CANCELLED] No data was deleted.")
                return
    
    # Execute clearing
    print("\n" + "=" * 80)
    if args.all:
        clear_all_rag_data(args.uploads)
    else:
        clear_rag_for_user(args.user, args.uploads)
    
    print("\n" + "=" * 80)
    print("[COMPLETED] RAG data clearing finished")
    print("\nNext steps:")
    print("  1. Ensure multilingual models are in place:")
    print(f"     - {config.RAG_EMBEDDING_MODEL}")
    print(f"     - {config.RAG_RERANKER_MODEL}")
    print("  2. Restart the server (python run_backend.py)")
    print("  3. Re-upload documents to rebuild collections")
    print("=" * 80)


if __name__ == "__main__":
    main()
