"""
Strong password generator.
Generates cryptographically secure passwords suitable for database credentials,
service accounts, and other high-value secrets.
"""

import secrets
import string
import argparse


def generate_password(
    length: int = 24,
    use_symbols: bool = True,
    avoid_shell_chars: bool = True,
    avoid_ambiguous: bool = True,
) -> str:
    """
    Generate a cryptographically secure password.

    Args:
        length: Total password length (default 24)
        use_symbols: Include special characters
        avoid_shell_chars: Skip $, `, \, ", ' which break shell/env parsing
        avoid_ambiguous: Skip 0/O, 1/l/I which are visually confusing

    Returns:
        A password guaranteed to contain at least one of each enabled category.
    """
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    # Curated symbol set — excludes shell-hostile characters by default
    symbols = "!@#%^&*()-_=+[]{}:,.?"

    if avoid_ambiguous:
        lowercase = lowercase.replace("l", "")
        uppercase = uppercase.replace("O", "").replace("I", "")
        digits = digits.replace("0", "").replace("1", "")

    if avoid_shell_chars:
        # Already excluded from the curated set above, but explicit for clarity
        for char in "$`\\\"'<>|;&":
            symbols = symbols.replace(char, "")

    # Build the character pool and guarantee at least one from each category
    pools = [lowercase, uppercase, digits]
    if use_symbols:
        pools.append(symbols)

    if length < len(pools):
        raise ValueError(
            f"Length {length} too short for required categories ({len(pools)})"
        )

    # One guaranteed character from each pool, fill the rest from the union
    password_chars = [secrets.choice(pool) for pool in pools]
    all_chars = "".join(pools)
    password_chars += [
        secrets.choice(all_chars) for _ in range(length - len(pools))
    ]

    # Cryptographic shuffle — secrets.SystemRandom uses os.urandom under the hood
    secrets.SystemRandom().shuffle(password_chars)

    return "".join(password_chars)


def main():
    parser = argparse.ArgumentParser(description="Generate strong passwords.")
    parser.add_argument(
        "-l", "--length", type=int, default=24, help="Password length (default: 24)"
    )
    parser.add_argument(
        "-n", "--count", type=int, default=5, help="How many to generate (default: 5)"
    )
    parser.add_argument(
        "--no-symbols", action="store_true", help="Letters and digits only"
    )
    parser.add_argument(
        "--allow-shell-chars",
        action="store_true",
        help="Include $, `, etc. (NOT recommended for .env files)",
    )
    parser.add_argument(
        "--allow-ambiguous",
        action="store_true",
        help="Include 0/O/1/l/I (harder to read but more entropy)",
    )

    args = parser.parse_args()

    print(f"\nGenerating {args.count} password(s) of length {args.length}:\n")
    for _ in range(args.count):
        pwd = generate_password(
            length=args.length,
            use_symbols=not args.no_symbols,
            avoid_shell_chars=not args.allow_shell_chars,
            avoid_ambiguous=not args.allow_ambiguous,
        )
        print(f"  {pwd}")
    print()


if __name__ == "__main__":
    main()