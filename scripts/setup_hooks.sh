#!/bin/bash

# Setup script for git hooks and permissions
# Run this once after cloning the repository

echo "🔧 Setting up git hooks and script permissions..."

# Configure git to ignore file mode changes to prevent conflicts
echo "⚙️  Configuring git to ignore file permission changes..."
git config core.filemode false

# Check if Black is installed, install if needed
echo "🐍 Checking Black formatter installation..."
if ! command -v black &> /dev/null; then
    echo "📦 Installing Black formatter..."
    pip install black>=23.0.0
    if [ $? -eq 0 ]; then
        echo "✅ Black formatter installed successfully"
    else
        echo "❌ Failed to install Black formatter. Please install manually: pip install black"
    fi
else
    echo "✅ Black formatter is already installed"
fi

# Create the post-merge hook if it doesn't exist
if [ ! -f ".git/hooks/post-merge" ]; then
    echo "📝 Creating post-merge git hook..."
    cat > .git/hooks/post-merge << 'EOF'
#!/bin/bash

# Git post-merge hook to automatically set executable permissions
# This runs after every git pull/merge operation

# Set executable permissions for script files
chmod +x scripts/run_auto_validator.sh 2>/dev/null || true
chmod +x scripts/check_compatibility.sh 2>/dev/null || true
chmod +x scripts/check_requirements_changes.sh 2>/dev/null || true
chmod +x scripts/install_staging.sh 2>/dev/null || true
chmod +x scripts/setup_hooks.sh 2>/dev/null || true

echo "✅ Executable permissions restored for script files"
EOF
fi

# Make the post-merge hook executable
chmod +x .git/hooks/post-merge

# Create the pre-commit hook for Black formatting if it doesn't exist
if [ ! -f ".git/hooks/pre-commit" ]; then
    echo "📝 Creating pre-commit git hook for Black formatting..."
    cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash

# Pre-commit hook to run Black formatter on Python files

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Running Black formatter on staged Python files...${NC}"

# Get list of staged Python files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$')

if [ -z "$STAGED_FILES" ]; then
    echo -e "${GREEN}No Python files to format.${NC}"
    exit 0
fi

# Check if Black is installed
if ! command -v black &> /dev/null; then
    echo -e "${RED}Error: Black is not installed. Please install it with: pip install black${NC}"
    echo -e "${YELLOW}Or install all requirements: pip install -r requirements.txt${NC}"
    exit 1
fi

# Run Black on staged files
echo "Formatting files:"
for FILE in $STAGED_FILES; do
    echo "  - $FILE"
    black "$FILE"
    
    # Check if Black made changes
    if ! git diff --quiet "$FILE"; then
        echo -e "${YELLOW}Black formatted $FILE - adding changes to staging area${NC}"
        git add "$FILE"
    fi
done

echo -e "${GREEN}Black formatting completed successfully!${NC}"
exit 0
EOF
    chmod +x .git/hooks/pre-commit
    echo "✅ Pre-commit hook created and made executable"
else
    echo "✅ Pre-commit hook already exists"
fi

# Set executable permissions for all script files
echo "🔑 Setting executable permissions for script files..."
chmod +x scripts/*.sh 2>/dev/null || true

echo "✅ Setup complete! Git hooks are now active."
echo "📋 Git is configured to ignore file permission changes to prevent conflicts."
echo "📋 From now on, script permissions will be automatically restored after git pulls."
echo "📋 Pre-commit hook will automatically format Python files with Black before commits."