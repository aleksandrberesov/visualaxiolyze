#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAME="visualaxiolyze"
TAG=""
OUTPUT_DIR=""

# Parse named arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --image-name) IMAGE_NAME="$2"; shift 2 ;;
        --tag)        TAG="$2";        shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# Resolve version from pyproject.toml if --tag not supplied
if [[ -z "$TAG" ]]; then
    PYPROJECT="$ROOT/deps/repo_vdag/pyproject.toml"
    TAG=$(grep -E '^version\s*=\s*"' "$PYPROJECT" | head -1 | sed -E 's/version\s*=\s*"(.+)"/\1/')
    if [[ -z "$TAG" ]]; then
        echo "Error: could not read version from $PYPROJECT. Pass --tag explicitly." >&2
        exit 1
    fi
    echo "Detected version: $TAG"
fi

# Compute build number as sum of commits across all repos
_count_commits() {
    local n
    n=$(git -C "$1" rev-list --count HEAD 2>/dev/null) || echo 0
    echo "${n:-0}"
}
BUILD_NUMBER=$(( $(_count_commits "$ROOT") + $(_count_commits "$ROOT/deps/repo_vdag") + $(_count_commits "$ROOT/deps/repo_glm") ))
echo "Build number: $BUILD_NUMBER"

TAG="$TAG.$BUILD_NUMBER"
echo "Full tag: $TAG"

TAR_NAME="${IMAGE_NAME}_${TAG}.tar"
if [[ -n "$OUTPUT_DIR" ]]; then
    mkdir -p "$OUTPUT_DIR"
    TAR_FILE="$OUTPUT_DIR/$TAR_NAME"
else
    TAR_FILE="$TAR_NAME"
fi

echo "Updating submodules..."
git submodule update --init --recursive

echo "Building Docker image: ${IMAGE_NAME}:${TAG}..."
docker build --build-arg BUILD_NUMBER="$BUILD_NUMBER" -t "${IMAGE_NAME}:${TAG}" "$ROOT"

echo "Saving Docker image to $TAR_FILE..."
docker save -o "$TAR_FILE" "${IMAGE_NAME}:${TAG}"

echo "Done! Image saved as $TAR_FILE"
