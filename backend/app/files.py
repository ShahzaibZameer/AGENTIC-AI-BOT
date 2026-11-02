import hashlib
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from openpyxl import Workbook, load_workbook
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
from openpyxl.utils.exceptions import InvalidFileException


MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_DOCUMENT_TEXT = 100_000
MAX_SPREADSHEET_ROWS = 1_000
MAX_SPREADSHEET_COLUMNS = 100
MAX_UPLOAD_ENTRIES = 1_000
MAX_UPLOAD_EXPANDED_SIZE = 50 * 1024 * 1024
MAX_FILE_PREVIEW = 20_000
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,119}\.(docx|xlsx)$", re.IGNORECASE)


def ensure_files_directory(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve(strict=True)


def _file_path(directory: Path, filename: str, extension: str | None = None) -> Path:
    if not isinstance(filename, str) or not _SAFE_FILENAME.fullmatch(filename):
        raise ValueError("Use a simple filename ending in .docx or .xlsx; folder paths are not allowed.")
    if extension and Path(filename).suffix.lower() != extension:
        raise ValueError(f"This operation requires a {extension} file.")
    root = ensure_files_directory(directory)
    path = root / filename
    if path.parent != root or path.is_symlink():
        raise ValueError("The requested file is outside the AgentOS files folder.")
    return path


def list_files(directory: Path) -> list[dict[str, str]]:
    root = ensure_files_directory(directory)
    return [
        {"filename": path.name, "type": path.suffix[1:].lower()}
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower())
        if path.is_file()
        and not path.is_symlink()
        and not path.name.startswith(".agentos-")
        and path.suffix.lower() in {".docx", ".xlsx"}
    ]


def downloadable_file_path(directory: Path, filename: str) -> Path:
    path = _file_path(directory, filename)
    _check_file(path)
    return path


def store_uploaded_file(directory: Path, filename: str, temporary_path: Path) -> str:
    destination = _file_path(directory, filename)
    if destination.exists():
        raise FileExistsError(f"{destination.name} already exists. Uploading never overwrites files.")
    if temporary_path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("Files larger than 10 MB are not supported.")
    _validate_office_file(temporary_path, destination.suffix.lower())
    try:
        os.link(temporary_path, destination)
    except FileExistsError as exc:
        raise FileExistsError(
            f"{destination.name} already exists. Uploading never overwrites files."
        ) from exc
    return f"Uploaded {destination.name} to the AgentOS files folder."


def read_word_document(directory: Path, filename: str) -> str:
    path = _file_path(directory, filename, ".docx")
    _check_file(path)
    document = Document(path)
    lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    preview = "\n".join(lines)
    if not preview:
        return "The Word document contains no readable text."
    if len(preview) > MAX_FILE_PREVIEW:
        return preview[:MAX_FILE_PREVIEW] + "\n[Preview truncated]"
    return preview


def read_excel_workbook(directory: Path, filename: str) -> str:
    path = _file_path(directory, filename, ".xlsx")
    _check_file(path)
    workbook = load_workbook(path, read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for worksheet in workbook.worksheets:
            lines.append(f"Sheet: {worksheet.title}")
            for row_number, row in enumerate(
                worksheet.iter_rows(max_row=200, max_col=30, values_only=True), start=1
            ):
                if not any(value is not None for value in row):
                    continue
                values = ["" if value is None else str(value)[:500] for value in row]
                lines.append(f"{row_number}: " + " | ".join(values))
                if sum(map(len, lines)) >= MAX_FILE_PREVIEW:
                    lines.append("[Preview truncated]")
                    return "\n".join(lines)[:MAX_FILE_PREVIEW]
    finally:
        workbook.close()
    return "\n".join(lines) or "The Excel workbook contains no readable cell values."


def _check_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{path.name} was not found in the AgentOS files folder.")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Only regular files in the AgentOS files folder can be changed.")
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("Files larger than 10 MB are not supported.")


def _validate_office_file(path: Path, extension: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_UPLOAD_ENTRIES:
                raise ValueError("The Office file contains too many internal parts.")
            if sum(member.file_size for member in members) > MAX_UPLOAD_EXPANDED_SIZE:
                raise ValueError("The Office file expands beyond the supported size.")
            if any(member.flag_bits & 0x1 for member in members):
                raise ValueError("Encrypted Office files are not supported.")
            names = {member.filename for member in members}
            if "[Content_Types].xml" not in names or "_rels/.rels" not in names:
                raise ValueError("The uploaded file is not a valid Office document.")
            if extension == ".docx" and "word/document.xml" not in names:
                raise ValueError("The uploaded file is not a valid .docx Word document.")
            if extension == ".xlsx" and "xl/workbook.xml" not in names:
                raise ValueError("The uploaded file is not a valid .xlsx Excel workbook.")
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid Office document.") from exc

    try:
        if extension == ".docx":
            Document(path)
        else:
            workbook = load_workbook(path, read_only=True, data_only=True)
            workbook.close()
    except (
        ValueError,
        KeyError,
        OSError,
        zipfile.BadZipFile,
        PackageNotFoundError,
        InvalidFileException,
    ) as exc:
        raise ValueError("The uploaded file could not be opened as a valid Office document.") from exc


def _save_new_file(path: Path, save: Any) -> None:
    if path.exists():
        raise FileExistsError(f"{path.name} already exists. Choose a different filename.")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".agentos-", suffix=path.suffix, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        save(temporary_path)
        if temporary_path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError("The generated file is larger than 10 MB.")
        os.link(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def create_word_document(directory: Path, filename: str, title: str, content: str) -> str:
    path = _file_path(directory, filename, ".docx")
    title = _bounded_text(title, "title", 200)
    content = _bounded_text(content, "content", MAX_DOCUMENT_TEXT)
    document = Document()
    document.add_heading(title, level=1)
    for paragraph in content.splitlines():
        document.add_paragraph(paragraph)
    _save_new_file(path, document.save)
    return f"Created Word document {path.name} in the AgentOS files folder."


def create_excel_workbook(
    directory: Path,
    filename: str,
    sheet_name: str,
    headers: list[str],
    rows: list[list[str]],
) -> str:
    path = _file_path(directory, filename, ".xlsx")
    if not isinstance(sheet_name, str) or not sheet_name.strip() or len(sheet_name) > 31:
        raise ValueError("Sheet names must contain 1 to 31 characters.")
    if any(character in sheet_name for character in r"\/:*?[]"):
        raise ValueError("Sheet names cannot contain / \\ : * ? [ or ].")
    if not headers or len(headers) > MAX_SPREADSHEET_COLUMNS:
        raise ValueError(f"Provide between 1 and {MAX_SPREADSHEET_COLUMNS} column headers.")
    if len(rows) > MAX_SPREADSHEET_ROWS:
        raise ValueError(f"Provide no more than {MAX_SPREADSHEET_ROWS} data rows.")
    if len(headers) * (len(rows) + 1) > 100_000:
        raise ValueError("The workbook is too large; provide fewer cells.")
    for value in [*headers, *(cell for row in rows for cell in row)]:
        _bounded_text(value, "cell value", 32_000)
        validate_spreadsheet_value(value)
    if any(len(row) != len(headers) for row in rows):
        raise ValueError("Each data row must contain the same number of cells as the headers.")

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    _save_new_file(path, workbook.save)
    return f"Created Excel workbook {path.name} with {len(rows)} data rows."


def update_word_document(
    directory: Path,
    filename: str,
    find_text: str,
    replace_text: str,
    expected_hash: str | None = None,
) -> str:
    path = _file_path(directory, filename, ".docx")
    _check_file(path)
    _check_expected_hash(path, expected_hash)
    find_text = _bounded_text(find_text, "text to find", MAX_DOCUMENT_TEXT)
    replace_text = _bounded_text(replace_text, "replacement text", MAX_DOCUMENT_TEXT)
    if not find_text:
        raise ValueError("Text to find cannot be empty.")
    document = Document(path)
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    matches = sum(paragraph.text.count(find_text) for paragraph in paragraphs)
    if not matches:
        raise ValueError(f"The requested text was not found in {path.name}.")
    for paragraph in paragraphs:
        if find_text in paragraph.text:
            paragraph.text = paragraph.text.replace(find_text, replace_text)
    _save_replacement(path, document.save, expected_hash)
    return f"Updated {matches} text occurrence(s) in {path.name}."


def update_excel_cell(
    directory: Path,
    filename: str,
    sheet_name: str,
    cell: str,
    value: str,
    expected_hash: str | None = None,
) -> str:
    path = _file_path(directory, filename, ".xlsx")
    _check_file(path)
    _check_expected_hash(path, expected_hash)
    sheet_name = _bounded_text(sheet_name, "sheet name", 31)
    value = _bounded_text(value, "cell value", 32_000)
    validate_spreadsheet_value(value)
    cell = _valid_cell(cell)

    workbook = load_workbook(path)
    if sheet_name not in workbook.sheetnames:
        raise ValueError(f"Sheet {sheet_name!r} was not found in {path.name}.")
    workbook[sheet_name][cell.upper()] = value
    _save_replacement(path, workbook.save, expected_hash)
    workbook.close()
    return f"Updated cell {cell.upper()} on sheet {sheet_name!r} in {path.name}."


def read_excel_cell(directory: Path, filename: str, sheet_name: str, cell: str) -> str:
    path = _file_path(directory, filename, ".xlsx")
    _check_file(path)
    sheet_name = _bounded_text(sheet_name, "sheet name", 31)
    cell = _valid_cell(cell)
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"Sheet {sheet_name!r} was not found in {path.name}.")
        value = workbook[sheet_name][cell].value
        return "" if value is None else str(value)
    finally:
        workbook.close()


def rename_file(
    directory: Path,
    filename: str,
    new_filename: str,
    expected_hash: str | None = None,
) -> str:
    source, destination = validate_file_rename(directory, filename, new_filename)
    _check_expected_hash(source, expected_hash)
    # A same-directory hard link creates the new name only if it does not exist.
    os.link(source, destination)
    source.unlink()
    return f"Renamed {source.name} to {destination.name}."


def validate_file_rename(directory: Path, filename: str, new_filename: str) -> tuple[Path, Path]:
    source = _file_path(directory, filename)
    destination = _file_path(directory, new_filename)
    _check_file(source)
    if source.suffix.lower() != destination.suffix.lower():
        raise ValueError("Renaming must keep the original file type.")
    if source == destination:
        raise ValueError("The new filename must be different from the current filename.")
    if destination.exists():
        raise FileExistsError(f"{destination.name} already exists; it will not be overwritten.")
    return source, destination


def file_hash(directory: Path, filename: str) -> str:
    path = _file_path(directory, filename)
    _check_file(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute_approved_operation(
    directory: Path, operation: str, arguments: dict[str, Any], expected_hash: str
) -> str:
    if operation == "update_word_document":
        return update_word_document(directory, **arguments, expected_hash=expected_hash)
    if operation == "update_excel_cell":
        return update_excel_cell(directory, **arguments, expected_hash=expected_hash)
    if operation == "rename_agent_file":
        return rename_file(directory, **arguments, expected_hash=expected_hash)
    raise ValueError("This file operation is not allowed.")


def _save_replacement(path: Path, save: Any, expected_hash: str | None) -> None:
    if expected_hash:
        _check_expected_hash(path, expected_hash)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".agentos-", suffix=path.suffix, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        save(temporary_path)
        if temporary_path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError("The updated file would be larger than 10 MB.")
        if expected_hash:
            _check_expected_hash(path, expected_hash)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _check_expected_hash(path: Path, expected_hash: str | None) -> None:
    if expected_hash and hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("The file changed after approval was requested. Ask the agent to create a new approval.")


def _bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{label.capitalize()} must be text no longer than {maximum} characters.")
    return value


def validate_spreadsheet_value(value: str) -> None:
    if value.lstrip().startswith("="):
        raise ValueError("Excel formulas are not supported; cell values must be plain text.")


def _valid_cell(cell: str) -> str:
    if not isinstance(cell, str) or not re.fullmatch(r"[A-Za-z]{1,3}[1-9][0-9]{0,6}", cell):
        raise ValueError("Provide a single valid Excel cell such as A1 or BC42.")
    column, row = coordinate_from_string(cell.upper())
    if column_index_from_string(column) > 16_384 or row > 1_048_576:
        raise ValueError("The requested cell is outside Excel's supported range.")
    return cell.upper()
