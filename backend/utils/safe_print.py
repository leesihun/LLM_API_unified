"""
Safe print utility for Windows console compatibility
Automatically replaces emojis with ASCII alternatives on Windows
"""
import sys

# Emoji replacements for Windows console
EMOJI_REPLACEMENTS = {
    '✅': '[OK]',
    '❌': '[X]',
    '⚠️': '[!]',
    '🏁': '[DONE]',
    '🔧': '[TOOL]',
    '🚀': '[START]',
    '👋': '[BYE]',
    '📦': '[PKG]',
}


def safe_print(*args, **kwargs):
    """
    Print with automatic emoji replacement on Windows
    
    Args:
        *args: Arguments to print
        **kwargs: Keyword arguments for print()
    """
    if sys.platform == 'win32':
        # Convert all args to strings and replace emojis
        safe_args = []
        for arg in args:
            text = str(arg)
            for emoji, replacement in EMOJI_REPLACEMENTS.items():
                text = text.replace(emoji, replacement)
            safe_args.append(text)
        print(*safe_args, **kwargs)
    else:
        # On non-Windows, print normally with emojis
        print(*args, **kwargs)


# Make it easy to use
if __name__ == "__main__":
    # Test
    safe_print("✅ Success")
    safe_print("❌ Error")
    safe_print("⚠️ Warning")

