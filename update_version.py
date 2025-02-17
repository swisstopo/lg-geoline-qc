import re
import os
import sys


def update_plugin_version(metadata_path, new_version):
    """
    Updates the version in the metadata.txt file of a QGIS plugin.

    Args:
        metadata_path (str): Path to the metadata.txt file.
        new_version (str): The new version number (e.g., "1.2.3").
    """
    try:
        # Remove the 'v' prefix if it exists
        if new_version.startswith("v"):
            new_version = new_version[1:]
        # Read the metadata file
        with open(metadata_path, "r") as file:
            lines = file.readlines()

        # Update the version line
        version_pattern = re.compile(r"^version\s*=\s*.*$", re.IGNORECASE)
        updated = False
        for i, line in enumerate(lines):
            if 'version' in line and version_pattern.match(line):
                lines[i] = f"version={new_version}\n"
                updated = True
                break

        if not updated:
            raise ValueError("Could not find the 'version' field in metadata.txt.")

        # Write the updated content back to the file
        with open(metadata_path, "w") as file:
            file.writelines(lines)

        print(f"Updated version to {new_version} in {metadata_path}")

    except Exception as e:
        print(f"Failed to update version: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python update_version.py <metadata_path> <new_version>")
        sys.exit(1)

    metadata_path = sys.argv[1]
    new_version = sys.argv[2]

    update_plugin_version(metadata_path, new_version)