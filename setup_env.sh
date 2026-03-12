#!/bin/bash

# Check dependencies
dependencies=("direnv" "realpath" "env" "grep" "cut" "sed" "comm" "rm" "echo" "touch" "dirname" "tr")

for dep in "${dependencies[@]}"; do
    if ! command -v $dep &>/dev/null; then
        echo "Error: $dep is not installed." >&2
        exit 1
    fi
done

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
source "$project_root/tools/direnv_src.sh"

envrc_path="$project_root/firmware/.envrc"

export IDF_TOOLS_PATH="$project_root/.espressif"
echo "export IDF_TOOLS_PATH=$IDF_TOOLS_PATH" >> "$envrc_path"

echo -e "\n\nCalling esp-idf/install.sh...\n"
"$project_root/bsp/esp-idf/install.sh" esp32c6

echo -e "\n\nSourcing esp-idf/export.sh...\n"
direnvsrc "$project_root/bsp/esp-idf/export.sh" "$envrc_path"

# Check for idf_tools.py
if ! command -v idf_tools.py &>/dev/null; then
    echo "Error: idf_tools.py is not found. Ensure ESP-IDF tools are set up correctly." >&2
    exit 1
fi

echo -e "\n\nCalling idf_tools.py install-python-env...\n"
idf_tools.py install-python-env

echo -e "\nDone!"
