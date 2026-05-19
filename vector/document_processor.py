"""
文档文本提取与清洗
支持格式：.txt  .md  .pdf  .docx
"""
import re
from pathlib import Path


SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


def extract_text(file_path: Path) -> str:
    """从文件中提取纯文本"""
    suffix = file_path.suffix.lower()

    if suffix in (".txt", ".md"):
        return file_path.read_text(encoding="utf-8")

    if suffix == ".pdf":
        return _extract_pdf(file_path)

    if suffix == ".docx":
        return _extract_docx(file_path)

    raise ValueError(f"不支持的文件格式：{suffix}")


def clean_text(text: str) -> str:
    """清洗文本：规范化换行、去除乱码、合并多余空行"""
    # 统一换行符
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 去除每行首尾空白
    lines = [line.strip() for line in text.split("\n")]
    # 合并超过2个连续空行为1个
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    # 过滤乱码：保留中文、英文、数字、常用标点和空白
    cleaned = re.sub(r"[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\w\s\.\,\!\?\:\;\"\'\-\(\)\[\]\{\}\/\\\#\@\%\&\*\+\=\<\>\~\`\|\^]", "", cleaned)
    return cleaned.strip()


def _extract_pdf(file_path: Path) -> str:
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError("请安装 pymupdf：pip install pymupdf")

    doc = fitz.open(str(file_path))
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n\n".join(pages)


def _extract_docx(file_path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        raise ImportError("请安装 python-docx：pip install python-docx")

    doc = Document(str(file_path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)
