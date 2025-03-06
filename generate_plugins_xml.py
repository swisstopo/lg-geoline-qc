#!/usr/bin/env python3

"""
Script to generate a QGIS plugins.xml repository file based on plugin metadata.
"""

import os
import sys
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import datetime


def read_metadata(metadata_file):
    """Read metadata.txt and return a dictionary of values."""
    metadata = {}
    with open(metadata_file, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                metadata[key.strip()] = value.strip()
    return metadata


def create_plugins_xml(plugin_name, version, metadata, base_url):
    """Create the plugins.xml file structure."""
    root = ET.Element("plugins")
    plugin = ET.SubElement(root, "pyqgis_plugin", name="GeoLines QC", version=version)

    # Add required elements
    ET.SubElement(plugin, "description").text = metadata.get("description", "")
    ET.SubElement(plugin, "homepage").text = metadata.get("homepage", "")
    ET.SubElement(plugin, "qgis_minimum_version").text = metadata.get(
        "qgisMinimumVersion", "3.0"
    )
    ET.SubElement(plugin, "file_name").text = f"{plugin_name}.{version}.zip"
    ET.SubElement(plugin, "author_name").text = metadata.get("author", "")

    # Download URL
    download_url = f"{base_url}/qgis/plugins/{plugin_name}.{version}.zip"
    ET.SubElement(plugin, "download_url").text = download_url

    # Add metadata
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
    ET.SubElement(plugin, "uploaded_by").text = "GitHub Actions"
    ET.SubElement(plugin, "create_date").text = now
    ET.SubElement(plugin, "update_date").text = now

    # Optional elements
    ET.SubElement(plugin, "experimental").text = metadata.get("experimental", "False")
    ET.SubElement(plugin, "deprecated").text = metadata.get("deprecated", "False")
    ET.SubElement(plugin, "tracker").text = metadata.get("tracker", "")
    ET.SubElement(plugin, "repository").text = metadata.get("repository", "")
    ET.SubElement(plugin, "tags").text = metadata.get("tags", "")

    # Pretty print XML
    rough_string = ET.tostring(root, "utf-8")
    reparsed = xml.dom.minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ")

    return pretty_xml


def main():
    """Main function."""
    if len(sys.argv) < 4:
        print("Usage: python generate_plugins_xml.py PLUGIN_NAME VERSION BASE_URL")
        sys.exit(1)

    plugin_name = sys.argv[1]
    version = sys.argv[2]
    base_url = sys.argv[3]
    metadata_file = "metadata.txt"

    if not os.path.exists(metadata_file):
        print(f"Error: {metadata_file} not found.")
        sys.exit(1)

    metadata = read_metadata(metadata_file)
    xml_content = create_plugins_xml(plugin_name, version, metadata, base_url)

    # Write to file
    output_dir = "dist"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "plugins.xml")

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(xml_content)

    print(f"Generated plugins.xml at {output_file}")


if __name__ == "__main__":
    main()
