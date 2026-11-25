"""Vaka dosyası biçimi: yükleme, alan denetimi, bağlam metni, yeni vaka iskeleti.

Bir vaka tek bir JSON dosyasıdır. Ayrıntı: docs/VAKA-BICIMI.md. Kodda kullanıcının not düzeni varsayılmaz:
`kaynak_not` ve `kaynak_olay` serbest metindir (dosya yolu, URL, iş kaydı numarası).
"""
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

SUITLER = ("yetenek", "regresyon")
ZORUNLU = ("id", "kaynak_not", "hata_sinifi", "girdi", "beklenen", "yanlis",
           "kontrol", "referans_cozum", "negatif")
BILINEN = frozenset(ZORUNLU + (
    "suite", "kaynak_olay", "ornek", "etiket", "ortam", "varyantlar", "bos_durum_gecebilir",
    "baglam", "ipucu_yasak", "aciklama",
))
ORTAM_ALAN = frozenset({"kurulum", "kurulum_betik", "uzak", "env", "gorunur"})
VARYANT_ALAN = frozenset({"ad", "aciklama", "kurulum_ek", "girdi", "referans_cozum", "negatif", "bos_gecebilir"})
BAGLAM_ALAN = frozenset({"metin", "dosyalar"})
ID_DESENI = re.compile(r"[a-z0-9][a-z0-9-]{1,79}")
_ENV_AD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def metin(x):
    """Satır listesi ya da metin -> tek metin."""
    return "\n".join(x) if isinstance(x, list) else (x or "")


def vaka_oku(yol):
    yol = Path(yol)
    try:
        v = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{yol}: okunamadı: {exc}") from exc
    if not isinstance(v, dict):
        raise ValueError(f"{yol}: vaka bir JSON nesnesi olmalı")  # noqa: TRY004 - dosya sözleşmesi
    v["_dosya"] = str(yol)
    v.setdefault("suite", "regresyon" if yol.parent.name == "regresyon" else "yetenek")
    return v


def vaka_yukle(dizin, secim=None, suite="hepsi"):
    """Klasördeki (alt klasörler dahil) *.json vakaları. Paket: `suite` alanı, yoksa `regresyon/` klasörü."""
    vakalar = []
    for p in sorted(Path(dizin).rglob("*.json")):
        v = vaka_oku(p)
        if secim and v.get("id") not in secim:
            continue
        if suite != "hepsi" and v["suite"] != suite:
            continue
        vakalar.append(v)
    return vakalar


def eksik_alanlar(vaka):
    e = [a for a in ZORUNLU if not vaka.get(a)]
    k = vaka.get("kontrol") or {}
    if isinstance(k, dict):
        e += [f"kontrol.{a}" for a in ("komut", "gecer_cikti") if not k.get(a)]
    return e


def baglam_yolu(taban, d):
    """`baglam.dosyalar` girdisini vaka dosyasının klasörüne hapsederek çöz.

    Mutlak yol, sürücü/UNC öneki, `~` ve (sembolik bağlar çözüldükten sonra) vaka klasörü dışına çıkan yol
    reddedilir: bağlam metni ajana gider, vaka dosyası yerel herhangi bir dosyayı oraya taşıyamamalı."""
    if not isinstance(d, str) or not d.strip():
        raise ValueError(f"baglam.dosyalar girdisi boş olmayan bir yol olmalı: {d!r}")
    if d.startswith("~") or PurePosixPath(d).is_absolute() or PureWindowsPath(d).anchor:
        raise ValueError(f"baglam.dosyalar vaka klasörüne göreli olmalı (mutlak yol ve ~ yasak): {d}")
    kok = Path(taban).resolve()
    yol = (kok / d).resolve()
    if not yol.is_relative_to(kok):
        raise ValueError(f"baglam.dosyalar vaka klasörünün dışına çıkıyor: {d}")
    return yol


def baglam_metni(vaka):
    """`baglam` kolunun ajana verdiği metin: kullanıcının kendi kural/not alıntısı. Yoksa None.

    `baglam.metin` doğrudan metindir; `baglam.dosyalar` vaka dosyasına göre göreli yollardır (kullanıcının
    notlarından alıntı) ve vaka dosyasının klasöründen dışarı çıkamaz (`baglam_yolu`; aykırısı ValueError).
    Metin vakanın kimliğini ya da kontrolün geçer çıktısını içeremez (sızıntı)."""
    b = vaka.get("baglam")
    if not b:
        return None
    parcalar = []
    if b.get("metin"):
        parcalar.append(metin(b["metin"]).strip())
    taban = Path(vaka.get("_dosya", ".")).parent
    dosyalar = b.get("dosyalar") or []
    if not isinstance(dosyalar, list):
        raise ValueError("baglam.dosyalar bir yol listesi olmalı")  # noqa: TRY004 - dosya sözleşmesi
    for d in dosyalar:
        parcalar.append(baglam_yolu(taban, d).read_text(encoding="utf-8").strip())
    govde = "\n\n".join(p for p in parcalar if p)
    if not govde:
        return None
    return "# Bağlam\n\nAşağıdaki kayıtlar kullanıcının kendi notlarından gelir; ilgili olduğunda uygula.\n\n" + govde + "\n"


def baglam_sizintisi(vaka, govde):
    """Bağlamda vaka/kontrol izi var mı? Varsa açıklama, yoksa None."""
    izler = [vaka.get("id"), (vaka.get("kontrol") or {}).get("gecer_cikti")]
    for iz in filter(None, izler):
        if iz in govde:
            return f"bağlamda vaka izi: {iz}"
    return None


def bicim_hatalari(vaka):
    """Eksik alanların ötesinde biçim hataları (tür, bilinmeyen anahtar, ipucu sızıntısı)."""
    h = []
    ekstra = sorted(k for k in set(vaka) - BILINEN if not k.startswith("_"))
    if ekstra:
        h.append("bilinmeyen alan: " + ", ".join(ekstra))
    vid = vaka.get("id")
    if vid and (not isinstance(vid, str) or not ID_DESENI.fullmatch(vid)):
        h.append("id küçük harf, rakam ve tire olmalı")
    if vaka.get("suite") not in SUITLER:
        h.append("suite yetenek ya da regresyon olmalı")
    k = vaka.get("kontrol")
    if k is not None and not isinstance(k, dict):
        h.append("kontrol bir nesne olmalı")
    ortam = vaka.get("ortam") or {}
    if not isinstance(ortam, dict):
        h.append("ortam bir nesne olmalı")
        ortam = {}
    ekstra = sorted(set(ortam) - ORTAM_ALAN)
    if ekstra:
        h.append("bilinmeyen ortam alanı: " + ", ".join(ekstra))
    for ad in (ortam.get("env") or {}):
        if not _ENV_AD.fullmatch(ad):
            h.append(f"ortam.env adı geçersiz: {ad}")
    for i, var in enumerate(vaka.get("varyantlar") or []):
        if not isinstance(var, dict) or not var.get("ad"):
            h.append(f"varyantlar[{i}] ad ister")
            continue
        ekstra = sorted(set(var) - VARYANT_ALAN)
        if ekstra:
            h.append(f"varyant {var['ad']}: bilinmeyen alan: " + ", ".join(ekstra))
    b = vaka.get("baglam")
    if b is not None:
        if not isinstance(b, dict) or set(b) - BAGLAM_ALAN:
            h.append("baglam yalnız metin ve dosyalar alır")
        else:
            try:
                govde = baglam_metni(vaka) or ""
            except OSError as exc:
                h.append(f"baglam dosyası okunamadı: {exc.filename}")
            except ValueError as exc:
                h.append(str(exc))
            else:
                s = baglam_sizintisi(vaka, govde)
                if s:
                    h.append(s)
    girdiler = [vaka.get("girdi") or ""] + [v.get("girdi") or "" for v in vaka.get("varyantlar") or []
                                            if isinstance(v, dict)]
    for ifade in vaka.get("ipucu_yasak") or []:
        if any(ifade.lower() in g.lower() for g in girdiler):
            h.append(f"görev metni kuralı ele veriyor: '{ifade}'")
    return h


def iskelet(vid, suite="yetenek"):
    """`vaka yeni` için boş vaka. Zorunlu alanlar boş bırakılır: doldurulana kadar doğrulama GEÇERSİZ der."""
    return {
        "id": vid,
        "suite": suite,
        "hata_sinifi": "",
        "kaynak_not": "",
        "kaynak_olay": "",
        "ortam": {"kurulum": "", "kurulum_betik": [], "env": {}},
        "girdi": "",
        "beklenen": "",
        "yanlis": "",
        "kontrol": {"komut": [], "gecer_cikti": "TEMIZ"},
        "referans_cozum": [],
        "negatif": [],
        "varyantlar": [],
        "baglam": {"metin": ""},
        "ipucu_yasak": [],
    }
