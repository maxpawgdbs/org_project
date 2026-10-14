"""Read cell values from a simple XLSX without extra dependencies."""

import json
import posixpath
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def read_xlsx(filename):
    with zipfile.ZipFile(filename) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{S}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{S}t")))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall(f"{P}Relationship")}
        sheets = {}
        for sheet in workbook.find(f"{S}sheets"):
            target = targets[sheet.attrib[f"{R}id"]]
            path = posixpath.normpath(posixpath.join("xl", target.lstrip("/")))
            if path.startswith("xl/xl/"):
                path = path[3:]
            root = ET.fromstring(archive.read(path))
            rows = []
            for row in root.iter(f"{S}row"):
                values = {}
                for cell in row.findall(f"{S}c"):
                    kind = cell.attrib.get("t")
                    value = cell.find(f"{S}v")
                    if kind == "inlineStr":
                        text = "".join(node.text or "" for node in cell.iter(f"{S}t"))
                    elif value is None:
                        text = ""
                    elif kind == "s":
                        text = shared[int(value.text)]
                    else:
                        text = value.text or ""
                    if text:
                        values[cell.attrib["r"]] = text
                if values:
                    rows.append(values)
            sheets[sheet.attrib["name"]] = rows
        return sheets


if __name__ == "__main__":
    print(json.dumps(read_xlsx(Path(sys.argv[1])), ensure_ascii=False, indent=2))
