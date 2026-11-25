"""Pytest: src yolu; testler geliştiricinin ayar.toml dosyasına ve ortamına bağlanmasın."""
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[1]
SRC = str(KOK / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

ORNEK = KOK / "ornek" / "vakalar"


@pytest.fixture(autouse=True)
def vaka_ayar_izole(monkeypatch, tmp_path):
    monkeypatch.delenv("VAKA_AYAR", raising=False)
    monkeypatch.delenv("VAKA_KAL", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))


def mini_vaka(**ek):
    """Sentetik, hızlı bir vaka: x.txt içindeki 'a' 'y' olmalı; 'z' yanlış davranış."""
    v = {
        "id": "mini-01",
        "suite": "yetenek",
        "hata_sinifi": "deneme",
        "kaynak_not": "notlar/deneme.md",
        "ortam": {"kurulum_betik": ["printf 'a\\n' > x.txt", "git add x.txt", "git commit --quiet --message=ilk"]},
        "girdi": "x.txt içeriğini y yap.",
        "beklenen": "x.txt = y",
        "yanlis": "x.txt = z",
        "kontrol": {"komut": ["test \"$(git log -1 --format=%H)\" = \"$(cat ../taban-commit)\" || exit 3",
                              "test \"$(cat x.txt)\" = y || exit 4", "echo SONUC=uygun"],
                    "gecer_cikti": "SONUC=uygun"},
        "referans_cozum": ["echo y > x.txt"],
        "negatif": ["echo z > x.txt"],
        "_dosya": str(Path("mini-01.json")),
    }
    v.update(ek)
    return v
