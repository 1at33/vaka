"""Doğrulanabilir olay günlüğü: ekle-yalnız JSONL, özet zinciri, içerik adresli nesne deposu. Model çağrısı yok.

Düzen (günlük dizini):

    olaylar.jsonl            her satır bir olay: kanonik JSON + LF
    nesneler/sha256/<hex>    olayların andığı içerik (ajan çıktısı, vaka dosyası ...); adı içeriğin SHA-256'sı

Olay alanları:

    surum   "vaka-gunluk/1"
    kosu    koşu kimliği (tüm olaylarda aynı)
    sira    1'den başlayan ardışık sayı
    tur     ilk olay "kosu.basladi", son olay "kosu.bitti"; arada serbest (ör. "vaka.yuklendi", "kosu.senaryo")
    zaman   UTC, ISO 8601
    veri    nesne; içerik `{"nesne": "sha256:<hex>", "boyut": n}` başvurularıyla depoya bağlanır
    onceki  bir önceki olayın `ozet`i (ilk olayda null)
    ozet    olayın `ozet` dışındaki alanlarının kanonik JSON'unun SHA-256'sı

Kanonik JSON: UTF-8, anahtarlar sıralı, boşluksuz ayraçlar, Unicode kaçışsız, NaN/Infinity yasak, anahtarlar
yalnız metin, eşleşmemiş vekil (surrogate) karakter yasak. Unicode normalleştirilmez: NFC ve NFD yazımı farklı
baytlardır, farklı özet verir (normalleştirmek iki farklı içeriği aynı özete düşürürdü).

`gunluk_dogrula` şunları yakalar: değiştirilmiş olay (özet tutmaz), yeniden sıralanmış ya da silinmiş olay (sıra
atlar, zincir kopar), başka koşudan olay, kanonik olmayan satır (ör. aynı anahtar iki kez), yarım kalmış son satır,
eksik `kosu.bitti`, eksik, değişmiş ya da boyutu tutmayan nesne. Satır sonları CRLF'ye çevrilmiş günlük (ör. git
autocrlf) geçerli sayılır: özet ayrıştırılmış olaydan hesaplanır; nesneler ise bayt bayt karşılaştırılır.

Sınır: zincir imza değildir. Dosyalara yazabilen biri tüm zinciri baştan hesaplayabilir. Günlüğü bağlamak için
son olayın özetini (baş özeti) başka bir yerde sakla (sonuç JSON'u, commit mesajı) ve `beklenen_bas` ile
karşılaştır.
"""
import hashlib
import json
import math
import os
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SURUM = "vaka-gunluk/1"
OLAY_DOSYASI = "olaylar.jsonl"
NESNE_DIZINI = "nesneler"
BASLADI, BITTI = "kosu.basladi", "kosu.bitti"
VAKA_YUKLENDI, SENARYO = "vaka.yuklendi", "kosu.senaryo"
ALANLAR = frozenset({"surum", "kosu", "sira", "tur", "zaman", "veri", "onceki", "ozet"})
OZET_DESENI = re.compile(r"sha256:[0-9a-f]{64}")
SENARYO_ALANLARI = ("vaka", "kol", "senaryo", "deneme", "gecti", "atlandi_butce", "maliyet_usd")
_IKILI = getattr(os, "O_BINARY", 0)


class GunlukHatasi(ValueError):
    """Günlük yazılamıyor ya da kanonik JSON'a çevrilemeyen veri."""


def _denetle(deger, yol="$"):
    if deger is None or isinstance(deger, (bool, int, str)):
        if isinstance(deger, str):
            try:
                deger.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise GunlukHatasi(f"{yol}: eşleşmemiş vekil karakter") from exc
        return
    if isinstance(deger, float):
        if not math.isfinite(deger):
            raise GunlukHatasi(f"{yol}: NaN/Infinity kanonik JSON'da yok")
        return
    if isinstance(deger, (list, tuple)):
        for i, x in enumerate(deger):
            _denetle(x, f"{yol}[{i}]")
        return
    if isinstance(deger, dict):
        for k, x in deger.items():
            if not isinstance(k, str):
                raise GunlukHatasi(f"{yol}: anahtar metin olmalı: {k!r}")
            _denetle(k, f"{yol}.<anahtar>")
            _denetle(x, f"{yol}.{k}")
        return
    raise GunlukHatasi(f"{yol}: JSON türü değil: {type(deger).__name__}")


def kanonik_json(deger):
    """Belirlenimci JSON baytları (özet girdisi). Aykırı tür/değer GunlukHatasi."""
    _denetle(deger)
    return json.dumps(deger, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def ozet_bayt(icerik):
    return "sha256:" + hashlib.sha256(icerik).hexdigest()


def ozet_json(deger):
    return ozet_bayt(kanonik_json(deger))


def olay_ozeti(olay):
    return ozet_json({k: v for k, v in olay.items() if k != "ozet"})


def _simdi():
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _nesne_yolu(dizin, ozet):
    if not isinstance(ozet, str) or not OZET_DESENI.fullmatch(ozet):
        raise GunlukHatasi(f"geçersiz nesne özeti: {ozet!r}")
    return Path(dizin) / NESNE_DIZINI / "sha256" / ozet.removeprefix("sha256:")


def _dosyaya_ekle(yol, bayt, yeni):
    bayrak = os.O_WRONLY | os.O_APPEND | _IKILI | ((os.O_CREAT | os.O_EXCL) if yeni else 0)
    fd = os.open(yol, bayrak, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(bayt)
        f.flush()
        os.fsync(f.fileno())


def nesne_yaz(dizin, icerik):
    """İçeriği depoya yaz (varsa dokunma); başvuru `{"nesne": "sha256:..", "boyut": n}` döndür."""
    if isinstance(icerik, str):
        icerik = icerik.encode("utf-8")
    ozet = ozet_bayt(icerik)
    hedef = _nesne_yolu(dizin, ozet)
    if hedef.exists():
        if hedef.read_bytes() != icerik:
            raise GunlukHatasi(f"depoda {ozet} adıyla farklı içerik var (depo bozuk)")
        return {"nesne": ozet, "boyut": len(icerik)}
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(f".{hedef.name}.{secrets.token_hex(4)}.gecici")
    fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _IKILI, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(icerik)
            f.flush()
            os.fsync(f.fileno())
        os.replace(gecici, hedef)
    finally:
        if gecici.exists():
            gecici.unlink()
    return {"nesne": ozet, "boyut": len(icerik)}


def nesne_oku(dizin, basvuru):
    """Başvurulan içeriği oku ve doğrula; tutmazsa GunlukHatasi."""
    yol = _nesne_yolu(dizin, basvuru.get("nesne"))
    if yol.is_symlink() or not yol.is_file():
        raise GunlukHatasi(f"nesne yok: {basvuru['nesne']}")
    icerik = yol.read_bytes()
    if ozet_bayt(icerik) != basvuru["nesne"]:
        raise GunlukHatasi(f"nesne değişmiş: {basvuru['nesne']}")
    if basvuru.get("boyut") != len(icerik):
        raise GunlukHatasi(f"nesne boyutu tutmuyor: {basvuru['nesne']}")
    return icerik


class Gunluk:
    """Ekle-yalnız yazıcı. Yeni günlük `Gunluk.ac(dizin, veri)` ile açılır; var olan günlüğe eklenmez."""

    def __init__(self, dizin, kosu, saat=None):
        self.dizin = Path(dizin)
        self.kosu = kosu
        self._saat = saat or _simdi
        self._olaylar = []

    @classmethod
    def ac(cls, dizin, veri=None, saat=None):
        dizin = Path(dizin)
        if (dizin / OLAY_DOSYASI).exists():
            raise GunlukHatasi(f"günlük zaten var (yeni bir dizin ver): {dizin / OLAY_DOSYASI}")
        dizin.mkdir(parents=True, exist_ok=True)
        g = cls(dizin, uuid.uuid4().hex, saat)
        g.ekle(BASLADI, veri or {})
        return g

    @property
    def yol(self):
        return self.dizin / OLAY_DOSYASI

    @property
    def bas_ozet(self):
        return self._olaylar[-1]["ozet"] if self._olaylar else None

    @property
    def olaylar(self):
        return tuple(self._olaylar)

    @property
    def kapali(self):
        return bool(self._olaylar) and self._olaylar[-1]["tur"] == BITTI

    def nesne(self, icerik):
        return nesne_yaz(self.dizin, icerik)

    def ekle(self, tur, veri=None):
        if not isinstance(tur, str) or not tur:
            raise GunlukHatasi("olay türü boş olmayan metin olmalı")
        if self.kapali:
            raise GunlukHatasi("kapanmış günlüğe olay eklenemez")
        if (tur == BASLADI) == bool(self._olaylar):
            raise GunlukHatasi(f"ilk olay ve yalnız ilk olay {BASLADI} olur")
        veri = {} if veri is None else veri
        if not isinstance(veri, dict):
            raise GunlukHatasi("olay verisi nesne olmalı")
        olay = {"surum": SURUM, "kosu": self.kosu, "sira": len(self._olaylar) + 1, "tur": tur,
                "zaman": self._saat(), "veri": json.loads(kanonik_json(veri)), "onceki": self.bas_ozet}
        olay["ozet"] = olay_ozeti(olay)
        if not self._olaylar:
            self.dizin.mkdir(parents=True, exist_ok=True)
        _dosyaya_ekle(self.yol, kanonik_json(olay) + b"\n", yeni=not self._olaylar)
        self._olaylar.append(olay)
        return olay

    def kapat(self, veri=None):
        """`kosu.bitti` yaz; `durum_ozeti` oynatmanın (indirge) özetidir, doğrulamada yeniden hesaplanır."""
        veri = dict(veri or {})
        veri["durum_ozeti"] = ozet_json(indirge(self._olaylar))
        return self.ekle(BITTI, veri)


def nesne_basvurulari(deger):
    """Verideki `{"nesne": ..., "boyut": ...}` başvuruları."""
    if isinstance(deger, dict):
        if "nesne" in deger:
            yield deger
        for x in deger.values():
            yield from nesne_basvurulari(x)
    elif isinstance(deger, list):
        for x in deger:
            yield from nesne_basvurulari(x)


def indirge(olaylar):
    """Oynatma: olaylardan koşu durumu (BITTI'den öncesi). Aynı olaylar her zaman aynı durumu verir."""
    d = {"kosu": None, "olay": 0, "turler": {}, "vakalar": {}, "senaryolar": []}
    for o in olaylar:
        if o["tur"] == BITTI:
            break
        d["kosu"] = o["kosu"]
        d["olay"] += 1
        d["turler"][o["tur"]] = d["turler"].get(o["tur"], 0) + 1
        v = o["veri"]
        if o["tur"] == VAKA_YUKLENDI:
            d["vakalar"][str(v.get("id"))] = (v.get("dosya") or {}).get("nesne")
        elif o["tur"] == SENARYO:
            d["senaryolar"].append({k: v.get(k) for k in SENARYO_ALANLARI})
    return d


def ozet_satirlari(olaylar):
    """Vaka ve kol başına: geçen/koşu, bütçeden atlanan, bildirilen maliyet."""
    gruplar = {}
    for s in indirge(olaylar)["senaryolar"]:
        g = gruplar.setdefault((s["vaka"], s["kol"]), [0, 0, 0, 0.0])
        if s["atlandi_butce"]:
            g[2] += 1
            continue
        g[1] += 1
        g[0] += bool(s["gecti"])
        g[3] += s["maliyet_usd"] or 0.0
    return [[v, k or "-", f"{g[0]}/{g[1]}", g[2], f"{g[3]:.4f}"] for (v, k), g in gruplar.items()]


OZET_BASLIK = ["vaka", "kol", "geçen/koşu", "atlanan", "maliyet_usd"]


@dataclass
class Dogrulama:
    gecerli: bool
    sorunlar: list = field(default_factory=list)
    olaylar: list = field(default_factory=list)
    bas_ozet: str | None = None
    tamam: bool = False
    kosu: str | None = None
    satir_sonu: str = "LF"

    def sozluk(self):
        return {"gecerli": self.gecerli, "sorunlar": self.sorunlar, "olay_sayisi": len(self.olaylar),
                "bas_ozet": self.bas_ozet, "tamam": self.tamam, "kosu": self.kosu, "satir_sonu": self.satir_sonu}


def _satirlar(veri, sorunlar):
    """(satır no, bayt) çiftleri ve satır sonu türü. Yarım son satır sorun olarak yazılır, ayrıştırılmaz."""
    parcalar = veri.split(b"\n")
    if parcalar[-1]:
        sorunlar.append(f"satır {len(parcalar)}: son satır yarım (yazma kesilmiş)")
    parcalar = parcalar[:-1]
    crlf = sum(p.endswith(b"\r") for p in parcalar)
    tur = "CRLF" if crlf == len(parcalar) and crlf else ("KARISIK" if crlf else "LF")
    return [(i, p[:-1] if p.endswith(b"\r") else p) for i, p in enumerate(parcalar, 1)], tur


def _olay_coz(no, ham, sorunlar):
    if not ham.strip():
        sorunlar.append(f"satır {no}: boş satır")
        return None
    try:
        olay = json.loads(ham.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        sorunlar.append(f"satır {no}: JSON okunamadı: {exc}")
        return None
    if not isinstance(olay, dict) or set(olay) != ALANLAR:
        sorunlar.append(f"satır {no}: olay alanları {sorted(ALANLAR)} olmalı")
        return None
    try:
        kanonik = kanonik_json(olay)
    except GunlukHatasi as exc:
        sorunlar.append(f"satır {no}: {exc}")
        return None
    if kanonik != ham:
        sorunlar.append(f"satır {no}: kanonik JSON değil (elle düzenlenmiş ya da yinelenen anahtar)")
    return olay


def gunluk_dogrula(dizin, tamam_sart=True, beklenen_bas=None):
    """Günlüğü baştan sona denetle; tüm sorunları topla (ilk hatada durmaz)."""
    dizin = Path(dizin)
    sorunlar = []
    try:
        veri = (dizin / OLAY_DOSYASI).read_bytes()
    except OSError as exc:
        return Dogrulama(False, [f"günlük okunamadı: {exc}"])
    if not veri:
        return Dogrulama(False, ["günlük boş"])
    satirlar, satir_sonu = _satirlar(veri, sorunlar)
    olaylar, onceki_ozet, onceki_sira, kosu, bitti_sira = [], None, 0, None, None
    for no, ham in satirlar:
        olay = _olay_coz(no, ham, sorunlar)
        if olay is None:
            continue
        sira, tur = olay["sira"], olay["tur"]
        if olay["surum"] != SURUM:
            sorunlar.append(f"satır {no}: bilinmeyen sürüm {olay['surum']!r}")
        if not isinstance(tur, str) or not isinstance(olay["veri"], dict) or not isinstance(olay["zaman"], str):
            sorunlar.append(f"satır {no}: tur/zaman metin, veri nesne olmalı")
            continue
        if kosu is None:
            kosu = olay["kosu"]
        elif olay["kosu"] != kosu:
            sorunlar.append(f"satır {no}: başka bir koşunun olayı ({olay['kosu']})")
        if not isinstance(sira, int) or isinstance(sira, bool) or sira != onceki_sira + 1:
            sorunlar.append(f"satır {no}: sıra bozuk: {onceki_sira}'den sonra {sira!r} (silinmiş ya da yer "
                            "değiştirmiş olay)")
        if olay["onceki"] != onceki_ozet:
            sorunlar.append(f"satır {no}: zincir kopuk: `onceki` bir önceki olayın özeti değil")
        if olay["ozet"] != olay_ozeti(olay):
            sorunlar.append(f"satır {no}: olay özeti tutmuyor (olay değiştirilmiş)")
        if (tur == BASLADI) != (not olaylar):
            sorunlar.append(f"satır {no}: {BASLADI} yalnız ilk olay olabilir ve ilk olay odur")
        if bitti_sira is not None:
            sorunlar.append(f"satır {no}: {BITTI} sonrasında olay")
        if tur == BITTI:
            bitti_sira = sira
            beklenen = olay["veri"].get("durum_ozeti")
            if beklenen is not None and beklenen != ozet_json(indirge(olaylar)):
                sorunlar.append(f"satır {no}: oynatma tutmuyor: olaylardan kurulan durum `durum_ozeti` değil")
        for b in nesne_basvurulari(olay["veri"]):
            try:
                nesne_oku(dizin, b)
            except GunlukHatasi as exc:
                sorunlar.append(f"satır {no}: {exc}")
            except OSError as exc:
                sorunlar.append(f"satır {no}: nesne okunamadı: {exc}")
        olaylar.append(olay)
        onceki_ozet = olay["ozet"] if isinstance(olay["ozet"], str) else None
        onceki_sira = sira if isinstance(sira, int) else onceki_sira + 1
    tamam = bitti_sira is not None
    if tamam_sart and not tamam and olaylar:
        sorunlar.append(f"{BITTI} yok: koşu yarım kalmış ya da günlüğün sonu silinmiş")
    bas = olaylar[-1]["ozet"] if olaylar else None
    if beklenen_bas is not None and bas != beklenen_bas:
        sorunlar.append(f"baş özeti beklenenden farklı: {bas} != {beklenen_bas}")
    return Dogrulama(not sorunlar and bool(olaylar), sorunlar, olaylar, bas, tamam, kosu, satir_sonu)


# --- vaka kos bağlantısı -------------------------------------------------------------------------------------

def kos_gunlugu_ac(dizin, bilgi, vakalar):
    """`vaka kos --gunluk`: koşuyu ve her vaka dosyasının o anki içeriğini (nesne olarak) kaydet."""
    g = Gunluk.ac(dizin, bilgi)
    for v in vakalar:
        g.ekle(VAKA_YUKLENDI, {"id": v.get("id"), "suite": v.get("suite"),
                               "dosya": g.nesne(Path(v["_dosya"]).read_bytes())})
    return g


def senaryo_kaydet(gunluk, vaka_id, kol, s):
    """Tek bir ajan koşusu (ya da bütçeden atlanan koşu). Çıktılar zaten maskelenmiştir; nesne olarak saklanır."""
    veri = {"vaka": vaka_id, "kol": kol, "senaryo": s.get("senaryo"), "deneme": s.get("deneme"),
            "gecti": s.get("gecti"), "atlandi_butce": bool(s.get("atlandi_butce")),
            "maliyet_usd": s.get("maliyet_usd"), "ajan_cikis": s.get("ajan_cikis"), "sure_sn": s.get("sure_sn")}
    for ad in ("ajan_cikti", "kontrol_cikti"):
        if s.get(ad) is not None:
            veri[ad] = gunluk.nesne(s[ad])
    return gunluk.ekle(SENARYO, veri)
