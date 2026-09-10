"""向 v3 合成法务稿注入可验证的 OOXML 修订和批注。"""
from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from .models import RevisionSet


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("w", W)


def _tag(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def _change(kind: str, text: str, revision: RevisionSet, identifier: str) -> ET.Element:
    node = ET.Element(_tag(W, kind), {
        _tag(W, "id"): identifier,
        _tag(W, "author"): revision.author,
        _tag(W, "date"): revision.date,
    })
    run = ET.SubElement(node, _tag(W, "r"))
    ET.SubElement(run, _tag(W, "delText" if kind == "del" else "t")).text = text
    return node


def inject_revisions(path: Path, revision: RevisionSet) -> Path:
    with ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    document = ET.fromstring(files["word/document.xml"])
    replaced = False
    for paragraph in document.iter(_tag(W, "p")):
        for position, child in enumerate(list(paragraph)):
            text = child.find(f".//{_tag(W, 't')}")
            if text is None or text.text != revision.deleted_text:
                continue
            paragraph.remove(child)
            nodes = (
                ET.Element(_tag(W, "commentRangeStart"), {_tag(W, "id"): "0"}),
                _change("del", revision.deleted_text, revision, "1"),
                _change("ins", revision.inserted_text, revision, "2"),
                ET.Element(_tag(W, "commentRangeEnd"), {_tag(W, "id"): "0"}),
            )
            reference = ET.Element(_tag(W, "r"))
            ET.SubElement(reference, _tag(W, "commentReference"), {_tag(W, "id"): "0"})
            for offset, node in enumerate((*nodes, reference)):
                paragraph.insert(position + offset, node)
            replaced = True
            break
        if replaced:
            break
    if not replaced:
        raise ValueError("未找到法务修订锚点")
    files["word/document.xml"] = ET.tostring(document, encoding="utf-8", xml_declaration=True)

    settings = ET.fromstring(files["word/settings.xml"])
    if settings.find(_tag(W, "trackRevisions")) is None:
        settings.insert(0, ET.Element(_tag(W, "trackRevisions")))
    files["word/settings.xml"] = ET.tostring(settings, encoding="utf-8", xml_declaration=True)

    comments = ET.Element(_tag(W, "comments"))
    comment = ET.SubElement(comments, _tag(W, "comment"), {
        _tag(W, "id"): "0", _tag(W, "author"): revision.author, _tag(W, "date"): revision.date,
    })
    paragraph = ET.SubElement(comment, _tag(W, "p"))
    run = ET.SubElement(paragraph, _tag(W, "r"))
    ET.SubElement(run, _tag(W, "t")).text = revision.comment
    files["word/comments.xml"] = ET.tostring(comments, encoding="utf-8", xml_declaration=True)

    rels = ET.fromstring(files["word/_rels/document.xml.rels"])
    ET.SubElement(rels, _tag(PR, "Relationship"), {
        "Id": "rIdV3Comments",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
        "Target": "comments.xml",
    })
    files["word/_rels/document.xml.rels"] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)

    content_types = ET.fromstring(files["[Content_Types].xml"])
    ET.SubElement(content_types, _tag(CT, "Override"), {
        "PartName": "/word/comments.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
    })
    files["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)

    with NamedTemporaryFile(delete=False, suffix=".docx", dir=path.parent) as stream:
        temporary = Path(stream.name)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for name, payload in files.items():
                archive.writestr(name, payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def extract_revision_text(path: Path, *, accept_changes: bool) -> str:
    with ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    parts: list[str] = []
    for paragraph in document.iter(_tag(W, "p")):
        for child in paragraph.iter():
            if child.tag == _tag(W, "delText") and not accept_changes and child.text:
                parts.append(child.text)
            elif child.tag == _tag(W, "t") and child.text:
                parts.append(child.text)
        parts.append("\n")
    return "".join(parts)
