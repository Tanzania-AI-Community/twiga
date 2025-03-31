#!/bin/bash

# create-release.sh - Automates the release process
# Usage: ./create-release.sh x.y.z

set -e  # Exit immediately if a command exits with a non-zero status

# Check if version parameter is provided (i.e. if number of args $# is not equal to (-ne) 1)
if [ $# -ne 1 ]; then
    echo "Error: Version number required"
    echo "Usage: $0 x.y.z" # $0 is the name of the script itself
    exit 1
fi

# Assigns the first argument to the VERSION variable
VERSION=$1

# Validate version format
if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version must be in the format x.y.z"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" # BASH_SOURCE[0] is the path of the script itself and dirname extracts the directory name
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)" # store the root directory in the ROOT_DIR variable (i.e. the twiga folder)
ALL_CONTRIBUTORS_SCRIPT="${SCRIPT_DIR}/all-contributors.sh" # store the path of the all-contributors script in the ALL_CONTRIBUTORS_SCRIPT variable

cd "${ROOT_DIR}"

# Ensure git is clean before proceeding
if [[ -n $(git status --porcelain) ]]; then
    echo "Error: Working directory is not clean. Commit or stash changes before creating a release."
    exit 1
fi

echo "Starting release process for version ${VERSION}..."

# 1. Checkout development branch
echo "Checking out development branch..."
git checkout development
git pull origin development

# 2. Create release branch
BRANCH_NAME="release/${VERSION}"
echo "Creating release branch: ${BRANCH_NAME}..."
git checkout -b "${BRANCH_NAME}"

# 3. Update version in pyproject.toml
echo "Updating version in pyproject.toml..."
# sed is a stream editor that can perform basic text transformations on an input stream (a file or input from a pipeline)
sed -i.bak "s/version = \"[0-9]*\.[0-9]*\.[0-9]*\"/version = \"${VERSION}\"/" pyproject.toml
rm -f pyproject.toml.bak # remove backup file automatically created by sed

#! Skipping tests since they are run in the CI pipeline as soon as a PR is opened

# 4. Run all-contributors script (if applicable)
echo "Running all-contributors script..."
read -p "Do you want to add new contributors for this release? (y/n): " add_contributors
if [[ "$add_contributors" =~ ^[Yy]$ ]]; then
    echo "Please add any contributors who should be recognized in this release."
    bash "${ALL_CONTRIBUTORS_SCRIPT}" interactive
else
    echo "Skipping contributor additions."
fi

# 5. Commit changes
echo "Committing changes..."
# Check if .all-contributorsrc or README.md were modified
if git status --porcelain | grep -q -E '\.all-contributorsrc|README\.md'; then
    echo "Contributors were updated. Adding files to commit..."
    git add pyproject.toml .all-contributorsrc README.md
    git commit -m "chore: bump version to ${VERSION} and update contributors"
else
    # If no contributor changes, just commit the version bump
    git add pyproject.toml
    git commit -m "chore: bump version to ${VERSION}"
fi

# 6. Push branch to remote
echo "Pushing branch to remote..."
git push -u origin "${BRANCH_NAME}"

# 7. Open a PR
echo "Creating pull request..."
# This uses the GitHub CLI if available, otherwise provides instructions
if command -v gh &> /dev/null; then
    gh pr create --base development --head "${BRANCH_NAME}" \
        --title "Release ${VERSION}" \
        --body "This PR contains the changes for release ${VERSION}."
else
    echo "GitHub CLI not installed. Please create a PR manually from ${BRANCH_NAME} to development."
    echo "You can do this by visiting: https://github.com/$(git config --get remote.origin.url | sed -n 's/.*github.com[:\/]\(.*\)\.git/\1/p')/pull/new/${BRANCH_NAME}...development"
fi

echo "Release preparation complete! Version ${VERSION} is ready for review."
