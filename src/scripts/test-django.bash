#!/usr/bin/env bash

# Run the CI Django checks and tests in the isolated docker-compose.test.yml stack.

set -euo pipefail

cd "$(dirname "$0")/../.."

parser_fixtures="src/ranking/tests/fixtures/parsers/**"
project=clist-test
compose_file="$PWD/docker-compose.test.yml"
# The explicit project name wins over COMPOSE_PROJECT_NAME, which could otherwise point `down` at the main stack.
compose=(docker compose --project-name "$project" -f "$compose_file")

if ! git lfs version >/dev/null 2>&1; then
    echo "git-lfs is required to check the parser fixtures." >&2
    exit 1
fi
lfs_files=$(git lfs ls-files --name-only --include="$parser_fixtures")
if [ -z "$lfs_files" ]; then
    echo "No Git LFS parser fixtures are tracked under $parser_fixtures." >&2
    exit 1
fi
# Check file contents rather than `git lfs ls-files` markers, which also flag locally modified archives.
lfs_pointer_header="version https://git-lfs.github.com/spec/v1"
unfetched=()
while IFS= read -r path; do
    if [ ! -f "$path" ] || cmp -s -n "${#lfs_pointer_header}" "$path" <(printf "%s" "$lfs_pointer_header"); then
        unfetched+=("$path")
    fi
done <<<"$lfs_files"
if [ "${#unfetched[@]}" -gt 0 ]; then
    echo "Git LFS parser fixtures are missing or pointers, not fetched archives:" >&2
    printf "  %s\n" "${unfetched[@]}" >&2
    echo "Fetch them with: git lfs pull --include=\"$parser_fixtures\"" >&2
    exit 1
fi

# `down --remove-orphans` removes every container labelled with the project, so refuse when one of them was not
# created from this compose file.
teardown() {
    local containers foreign
    containers=$(docker ps --all --filter "label=com.docker.compose.project=$project" \
        --format '{{.Names}}\t{{.Label "com.docker.compose.project.config_files"}}') || return 1
    foreign=$(awk -F '\t' -v file="$compose_file" 'NF && $2 != file' <<<"$containers")
    if [ -n "$foreign" ]; then
        echo "Refusing to remove Compose project $project: these containers were not created from $compose_file:" >&2
        sed 's/^/  /' <<<"$foreign" >&2
        return 1
    fi
    "${compose[@]}" down --volumes --remove-orphans
}

cleanup() {
    local status=$?
    # A stack left behind fails the run, while a failing run keeps its own status.
    if ! teardown && [ "$status" -eq 0 ]; then
        status=1
    fi
    exit "$status"
}

teardown
trap cleanup EXIT
# Disable default attestations without build.provenance, which requires Compose 2.39 or later.
BUILDX_NO_DEFAULT_ATTESTATIONS=1 "${compose[@]}" build
"${compose[@]}" run --rm tests
