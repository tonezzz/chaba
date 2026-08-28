#!/bin/bash
#
# Generate Production Secrets
# This script generates secure secrets for production deployment
#

set -euo pipefail

SECRETS_DIR="./secrets"
mkdir -p "$SECRETS_DIR"

echo "Generating production secrets..."

# Function to generate random secret
generate_secret() {
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-32
}

# Function to generate secret file
generate_secret_file() {
    local filename="$1"
    local description="$2"
    local value="${3:-$(generate_secret)}"
    
    echo "$value" > "$SECRETS_DIR/$filename"
    chmod 600 "$SECRETS_DIR/$filename"
    echo "Generated: $filename ($description)"
}

# Generate database secrets
generate_secret_file "postgres_password.txt" "PostgreSQL password" "chabapass"
generate_secret_file "postgres_user.txt" "PostgreSQL user" "chaba"
generate_secret_file "postgres_db.txt" "PostgreSQL database" "chaba"

# Generate Activepieces secrets
generate_secret_file "ap_encryption_key.txt" "Activepieces encryption key"
generate_secret_file "ap_jwt_secret.txt" "Activepieces JWT secret"
generate_secret_file "ap_postgres_password.txt" "Activepieces PostgreSQL password" "activepiecespass"

# Generate API key placeholders (user must fill these)
echo "PLACEHOLDER_YOUR_GEMINI_API_KEY_HERE" > "$SECRETS_DIR/gemini_api_key.txt"
chmod 600 "$SECRETS_DIR/gemini_api_key.txt"
echo "Generated: gemini_api_key.txt (PLACEHOLDER - update with real key)"

echo "PLACEHOLDER_YOUR_OPENAI_API_KEY_HERE" > "$SECRETS_DIR/openai_api_key.txt"
chmod 600 "$SECRETS_DIR/openai_api_key.txt"
echo "Generated: openai_api_key.txt (PLACEHOLDER - update with real key)"

echo ""
echo "Secrets generated in $SECRETS_DIR/"
echo "IMPORTANT: Update placeholder API keys with real values before production deployment"
echo "Files are set to chmod 600 for security"
