#!/bin/bash
IMAGE_NAME="visualaxiolyze"
TAG="latest"
TAR_FILE="${IMAGE_NAME}_${TAG}.tar"

# Ensure script stops on error
set -e

echo "Updating submodules..."
git submodule update --init --recursive

echo "Building Docker image: ${IMAGE_NAME}:${TAG}..."
docker build -t "${IMAGE_NAME}:${TAG}" .

echo "Saving Docker image to $TAR_FILE..."
docker save -o $TAR_FILE "${IMAGE_NAME}:${TAG}"

echo "Done! Image saved as $TAR_FILE"
