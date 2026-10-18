#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "======================================================"
echo "🚀 AUTOMATED NVIDIA CUDA REPOSITORY UPGRADE UTILITY"
echo "======================================================"

# 1. Ask the user for the target Fedora version number
read -p "Enter the target Fedora version you are upgrading to (e.g., 44, 45): " FEDORA_VERSION

# 2. Check if input is empty
if [ -z "$FEDORA_VERSION" ]; then
    echo "❌ Error: Version number cannot be empty."
    exit 1
fi

REPO_URL="https://developer.download.nvidia.com/compute/cuda/repos/fedora${FEDORA_VERSION}/x86_64/cuda-fedora${FEDORA_VERSION}.repo"

echo -e "\n🔄 Step 1: Mapping new NVIDIA repository path for Fedora ${FEDORA_VERSION}..."
sudo dnf config-manager addrepo --from-repofile="$REPO_URL"

echo -e "\n✨ Step 2: Refreshing DNF metadata packages..."
sudo dnf clean expire-cache
sudo dnf check-update || true

echo -e "\n🎉 Success! Your global Fedora system is now mapped to the CUDA Release drawer for Fedora ${FEDORA_VERSION}."
echo "You can now safely run 'sudo dnf upgrade' to fetch the updated toolkit files."
echo "======================================================"
