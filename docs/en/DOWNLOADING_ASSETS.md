# Downloading assets

From the repository root, run `python scripts/download_assets.py` with Python 3.12.
Local database setup already runs this command before seeding. It prepares the seed files and both conversation tokenizers in the bind-mounted checkout.

The script reads [the asset list](../../scripts/assets/downloads.json). For each
entry it checks the local file's SHA-256. If the file is missing or differs, it
downloads a temporary copy and checks its SHA-256 before installing it. An
incorrect download stops setup and leaves any existing file in place.

To add an asset, copy a manifest entry and set its filename, repository-relative
directory, version-pinned URL, and the SHA-256 of the known-good file.
**Add the full destination path to the root `.gitignore`.** Run the script
from a checkout missing the new asset to confirm the URL and checksum.

The current seed URLs refer to an existing Git commit. Move the assets to a
versioned release and verify the downloads before retiring that history.
