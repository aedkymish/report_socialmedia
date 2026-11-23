"""Reads a browser cookie export in any common format and converts it.

Supported:
- Netscape cookies.txt (tab- or space-separated; "Get cookies.txt LOCALLY")
- JSON list (Cookie-Editor, EditThisCookie) or {"cookies": [...]} objects
Never logs or prints cookie values.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CookieFileReport:
    path: str
    exists: bool = False
    size: int = 0
    format: str = "unknown"          # netscape | json | unknown
    cookies: list[dict] = field(default_factory=list)
    problem: str = ""                # human-readable reason when nothing was parsed


class CookieFile:
    def __init__(self, path: str):
        self.path = path or ""

    # ---------------------------------------------------------------- reading
    def read(self) -> CookieFileReport:
        report = CookieFileReport(self.path)
        p = Path(self.path) if self.path else None
        if not p or not p.is_file():
            report.problem = "الملف غير موجود داخل الحاوية."
            return report
        report.exists = True
        report.size = p.stat().st_size
        text = p.read_bytes().decode("utf-8-sig", errors="ignore")  # strips a BOM
        stripped = text.lstrip()
        if not stripped:
            report.problem = "الملف فارغ."
            return report

        if stripped[0] in "[{":
            report.format = "json"
            try:
                report.cookies = self._from_json(json.loads(stripped))
            except (ValueError, TypeError, AttributeError) as exc:
                report.problem = f"الملف يبدو JSON لكنه غير صالح: {exc.__class__.__name__}"
                return report
        elif stripped[:1] == "<":
            report.problem = "الملف صفحة HTML وليس ملف cookies (ربما حُفظت صفحة بدلاً من التصدير)."
            return report
        else:
            report.format = "netscape"
            report.cookies = self._from_netscape(text)

        if not report.cookies and not report.problem and "=" in stripped and ";" in stripped \
                and "\t" not in stripped:
            report.problem = ("الملف نص Cookie منسوخ من أدوات المطوّر (name=value; ...) وليس ملف تصدير. "
                              "استخدم إضافة Get cookies.txt LOCALLY واضغط Export.")
        if not report.cookies and not report.problem:
            report.problem = (
                "لم يُقرأ أي cookie. المتوقع: ملف Netscape (7 أعمدة في كل سطر) أو JSON. "
                + self._shape_hint(text)
            )
        return report

    def load(self) -> list[dict]:
        return self.read().cookies

    @staticmethod
    def _from_netscape(text: str) -> list[dict]:
        cookies = []
        for raw in text.splitlines():
            raw = raw.rstrip("\r\n")
            http_only = raw.startswith("#HttpOnly_")
            line = raw[len("#HttpOnly_"):] if http_only else raw
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                parts = line.split(None, 6)  # space-separated variant
            if len(parts) < 6:
                continue
            if len(parts) == 6:  # empty value got eaten by whitespace split
                parts.append("")
            domain, _sub, cpath, secure, expires, name, value = parts[:7]
            cookies.append(_cookie(domain, name, value.strip(), cpath, secure.upper() == "TRUE",
                                   http_only, expires))
        return [c for c in cookies if c["name"] and c["domain"]]

    @staticmethod
    def _from_json(data) -> list[dict]:
        if isinstance(data, dict):
            data = data.get("cookies") or data.get("Cookies") or []
        cookies = []
        for c in data:
            if not isinstance(c, dict) or not c.get("name") or not c.get("domain"):
                continue
            cookies.append(_cookie(
                c["domain"], c["name"], str(c.get("value", "")), c.get("path") or "/",
                bool(c.get("secure")), bool(c.get("httpOnly")),
                c.get("expirationDate") or c.get("expires") or c.get("expiry") or 0,
            ))
        return cookies

    @staticmethod
    def _shape_hint(text: str) -> str:
        """Describe the first data line's structure without revealing contents."""
        for line in text.splitlines():
            if line.strip() and not line.startswith("#"):
                return (f"أول سطر بيانات فيه {line.count(chr(9))} علامة Tab "
                        f"و{len(line.split())} جزءاً مفصولاً بمسافات.")
        return "الملف لا يحتوي إلا تعليقات (#)."

    # ------------------------------------------------------------- converting
    def as_netscape_path(self) -> str:
        """Path of a Netscape-format file for yt-dlp (converted copy if needed)."""
        report = self.read()
        if report.format == "netscape" and report.cookies:
            return self.path
        if not report.cookies:
            return ""
        digest = hashlib.sha256(Path(self.path).read_bytes()).hexdigest()[:16]
        out = Path(tempfile.gettempdir()) / f"cookies_{digest}.txt"
        if not out.exists():
            lines = ["# Netscape HTTP Cookie File"]
            for c in report.cookies:
                prefix = "#HttpOnly_" if c["httpOnly"] else ""
                sub = "TRUE" if c["domain"].startswith(".") else "FALSE"
                lines.append("\t".join([
                    prefix + c["domain"], sub, c["path"], "TRUE" if c["secure"] else "FALSE",
                    str(c.get("expires", 0)), c["name"], c["value"],
                ]))
            out.write_text("\n".join(lines) + "\n", encoding="utf-8")
            out.chmod(0o600)
        return str(out)


def _cookie(domain, name, value, path, secure, http_only, expires) -> dict:
    cookie = {"name": str(name), "value": value, "domain": str(domain).strip(), "path": path or "/",
              "secure": secure, "httpOnly": http_only}
    try:
        exp = int(float(expires))
        if exp > 0:
            cookie["expires"] = exp
    except (TypeError, ValueError):
        pass
    return cookie
