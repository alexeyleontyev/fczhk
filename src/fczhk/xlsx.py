"""Read cached values from a Google Sheets XLSX export without rewriting it."""

import posixpath
import re
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
DATE_TAB = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_sheets(path: Path, *, dated_only: bool = True) -> dict[str, dict[str, str]]:
    """Return cached cell values, including zeros, without evaluating formulas."""
    with zipfile.ZipFile(path) as archive:
        ns = {"x": SPREADSHEET_NS}
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = [
                "".join(node.text or "" for node in item.findall(".//x:t", ns))
                for item in root.findall("x:si", ns)
            ]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        sheets = {}
        for item in workbook.findall("x:sheets/x:sheet", ns):
            name = item.attrib["name"]
            if dated_only:
                if not DATE_TAB.fullmatch(name):
                    continue
                date.fromisoformat(name)
            target = targets[item.attrib[f"{{{REL_NS}}}id"]]
            member = posixpath.normpath(
                target.lstrip("/") if target.startswith("/xl/") else posixpath.join("xl", target)
            )
            root = ET.fromstring(archive.read(member))
            cells = {}
            for cell in root.findall(".//x:sheetData/x:row/x:c", ns):
                value = cell.find("x:v", ns)
                if cell.attrib.get("t") == "inlineStr":
                    inline = cell.find("x:is", ns)
                    raw = "".join(node.text or "" for node in inline.findall(".//x:t", ns))
                elif value is None:
                    raw = ""
                elif cell.attrib.get("t") == "s":
                    raw = strings[int(value.text)]
                else:
                    raw = value.text or ""
                if raw != "":
                    cells[cell.attrib["r"]] = raw.strip()
            sheets[name] = cells
    return sheets
