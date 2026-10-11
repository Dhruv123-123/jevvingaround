#!/bin/sh
# Freely licensed Game Boy homebrew for testing the emulator device and the long-horizon layer. Never a commercial ROM.
#   Aevilia (Apache-2.0, ISSOtm and the AeviDev team): a Pokemon-style RPG, the stand-in for Pokemon Red.
# Downloads from the Homebrew Hub (hh.gbdev.io) into roms/homebrew/ (git-ignored).
set -e
cd "$(dirname "$0")/.."
mkdir -p roms/homebrew
[ -f roms/homebrew/aevilia.gbc ] || curl -fsSL -o roms/homebrew/aevilia.gbc https://hh3.gbdev.io/static/database-gb/entries/aevilia/aevilia.gbc
ls -l roms/homebrew
