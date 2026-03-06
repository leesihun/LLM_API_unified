#!/bin/bash
# Add all changes
git add .

# Check if there is anything to commit
if ! git diff --cached --quiet; then
    # Commit with current date and time as the message
    git commit -m "$(date '+%Y-%m-%d %H:%M:%S')"

    # Pull remote changes first (rebase to keep linear history)
    echo "Pulling remote changes..."
    git pull --rebase

    # Push to the current branch's upstream
    echo "Pushing to remote..."
    git push
else
    echo "No changes to commit."
fi