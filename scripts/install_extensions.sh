#!/bin/bash
# Install VS Code extensions recommended for the project

extensions=(
    "ms-python.python"
    "ms-python.vscode-pylance"
    "ms-toolsai.jupyter"
    "charliermarsh.ruff"
    "ms-python.black-formatter"
    "ms-toolsai.datawrangler"
    "mtxr.sqltools"
    "mtxr.sqltools-driver-pg"
    "eamodio.gitlens"
    "quarto.quarto"
)

for ext in "${extensions[@]}"; do
    code --install-extension "$ext" --force
done

echo "All extensions installed!"
