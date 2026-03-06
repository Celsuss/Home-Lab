# justfile — Helm chart maintenance tasks
# Requires: helm, yamlfmt
# Install yamlfmt: sudo pacman -S yamlfmt  (or: yay -S yamlfmt-bin)

charts_dir := "helm/charts"

# Run all checks — suitable for CI and pre-commit hooks
check: lint template format-check

# Lint all Helm charts with helm lint
lint:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=0
    charts=$(find {{charts_dir}} -maxdepth 2 -name "Chart.yaml" -printf "%h\n" | sort)
    for chart in $charts; do
        echo "Linting $chart ..."
        if ! helm lint "$chart"; then
            failed=$((failed + 1))
        fi
    done
    if [ "$failed" -gt 0 ]; then
        echo ""
        echo "ERROR: $failed chart(s) failed linting"
        exit 1
    fi
    echo ""
    echo "All charts passed linting"

# Render all Helm charts with helm template (skips wrapper charts without downloaded deps)
template:
    #!/usr/bin/env bash
    set -uo pipefail
    failed=0
    charts=$(find {{charts_dir}} -maxdepth 2 -name "Chart.yaml" -printf "%h\n" | sort)
    for chart in $charts; do
        # Skip wrapper charts whose dependencies haven't been downloaded yet
        if grep -q "^dependencies:" "$chart/Chart.yaml" 2>/dev/null && \
           { [ ! -d "$chart/charts" ] || [ -z "$(ls -A "$chart/charts" 2>/dev/null)" ]; }; then
            echo "Skipping $chart (run 'helm dependency update $chart' first)"
            continue
        fi
        echo "Templating $chart ..."
        if ! helm template --generate-name "$chart" --namespace default > /dev/null; then
            failed=$((failed + 1))
        fi
    done
    if [ "$failed" -gt 0 ]; then
        echo ""
        echo "ERROR: $failed chart(s) failed templating"
        exit 1
    fi
    echo ""
    echo "All charts passed templating"

# Apply YAML formatting fixes in-place
format:
    yamlfmt

# Check YAML formatting without modifying files (exits non-zero if fixes needed)
format-check:
    yamlfmt -dry -lint
