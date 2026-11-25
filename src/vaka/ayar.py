"""Kullanıcı ayarı: ajan komut şablonu. Varsayılan olarak ajan YOKTUR.

Dosya: VAKA_AYAR (dosya yolu) > $XDG_CONFIG_HOME/vaka/ayar.toml > ~/.config/vaka/ayar.toml.
Windows: %APPDATA%\\vaka\\ayar.toml. Standart kütüphane (tomllib); bilinmeyen anahtar ValueError'dur.

    [ajan]
    komut = "benim-ajanim --gorev-dosyasi {girdi_dosyasi}"
    zaman_asimi_sn = 900
    kendi_ev = false
    tahmini_kosu_usd = 0.01
    ortam_izin = ["BENIM_AJAN_API_KEY"]   # ajana (yalnız ajana) geçirilecek sır adlı değişkenler

Betikler ve ajan, sır adlı/sır görünümlü ortam değişkenlerini varsayılan olarak GÖRMEZ (kum.miras_alinir);
`ortam_izin` (ve `vaka kos --ortam-izin AD`) yalnız ajan için adları geri açar.

Kodda model ya da sağlayıcı adı yoktur; hangi ajanın, hangi modelle koşacağı kullanıcının komutudur.
"""
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

_UST = frozenset({"ajan"})
_AJAN = frozenset({"komut", "zaman_asimi_sn", "kendi_ev", "tahmini_kosu_usd", "ortam_izin"})
ENV_AD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
YER_TUTUCULAR = ("{girdi_dosyasi}", "{baglam_dosyasi}", "{calisma}")


@dataclass(frozen=True)
class AjanAyari:
    komut: str = ""
    zaman_asimi_sn: int = 900
    kendi_ev: bool = False
    tahmini_kosu_usd: float = 0.01
    ortam_izin: tuple = ()


def varsayilan_dosya(ev, env):
    if sys.platform == "win32":
        kok = Path(env["APPDATA"]) if env.get("APPDATA") else ev / "AppData" / "Roaming"
        return kok / "vaka" / "ayar.toml"
    kok = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else ev / ".config"
    return kok / "vaka" / "ayar.toml"


def ayikla(veri):
    if not isinstance(veri, dict):
        raise ValueError("ayar tablo olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    ekstra = sorted(set(veri) - _UST)
    if ekstra:
        raise ValueError("bilinmeyen ayar anahtarı: " + ", ".join(ekstra))
    a = veri.get("ajan", {})
    if not isinstance(a, dict):
        raise ValueError("[ajan] tablo olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    ekstra = sorted(set(a) - _AJAN)
    if ekstra:
        raise ValueError("bilinmeyen [ajan] anahtarı: " + ", ".join(ekstra))
    komut = a.get("komut", "")
    if not isinstance(komut, str):
        raise ValueError("ajan.komut metin olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    zaman = a.get("zaman_asimi_sn", 900)
    if not isinstance(zaman, int) or isinstance(zaman, bool) or zaman <= 0:
        raise ValueError("ajan.zaman_asimi_sn pozitif tamsayı olmalı")
    ev = a.get("kendi_ev", False)
    if not isinstance(ev, bool):
        raise ValueError("ajan.kendi_ev true ya da false olmalı")  # noqa: TRY004 - yapılandırma sözleşmesi
    tahmin = a.get("tahmini_kosu_usd", 0.01)
    if not isinstance(tahmin, (int, float)) or isinstance(tahmin, bool) or tahmin <= 0:
        raise ValueError("ajan.tahmini_kosu_usd pozitif sayı olmalı")
    izin = a.get("ortam_izin", [])
    if not isinstance(izin, list) or not all(isinstance(x, str) and ENV_AD.fullmatch(x) for x in izin):
        raise ValueError("ajan.ortam_izin ortam değişkeni adlarından oluşan bir liste olmalı")
    return AjanAyari(komut.strip(), zaman, ev, float(tahmin), tuple(dict.fromkeys(izin)))


def toml_oku(yol):
    yol = Path(yol)
    try:
        with yol.open("rb") as f:
            return ayikla(tomllib.load(f))
    except FileNotFoundError as exc:
        raise ValueError(f"ayar dosyası yok: {yol}") from exc
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise ValueError(f"ayar.toml bozuk: {exc}") from exc


def ajan_ayari(dosya=None, env=None, ev=None):
    """dosya > VAKA_AYAR > varsayılan. Varsayılan dosya yoksa boş ayar (ajan komutu yok)."""
    env = os.environ if env is None else env
    ev = Path.home() if ev is None else Path(ev)
    if dosya is not None:
        return toml_oku(dosya)
    env_dosya = env.get("VAKA_AYAR")
    if env_dosya is not None:
        if not env_dosya.strip():
            raise ValueError("VAKA_AYAR boş olamaz")
        return toml_oku(Path(env_dosya.strip()).expanduser())
    yol = varsayilan_dosya(ev, env)
    return toml_oku(yol) if yol.is_file() else AjanAyari()
