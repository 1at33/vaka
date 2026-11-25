"""vaka komut satırı.

  vaka dogrula [--vakalar DIZIN] [--suite yetenek|regresyon|hepsi] [--vaka ID]... [--json F] [--md F]
  vaka kos --butce-usd X [--ajan KOMUT] [--kol ikisi|baglam|baglamsiz] [--tekrar N] [--gunluk DIZIN] [--json F]
  vaka yeni ID [--suite yetenek|regresyon] [--vakalar DIZIN]
  vaka liste [--vakalar DIZIN] [--suite ...]
  vaka hakem-sina (--ornek-hakem saf|saglam | --hakem KOMUT --butce-usd X | --hakem-py DOSYA.py:AD --butce-usd X)
  vaka hakem-sina --liste
  vaka dogrula-gunluk DIZIN [--beklenen-bas OZET] [--yarim-kabul] [--olaylar] [--json F]

Varsayılan mod `dogrula`dır ve model çağırmaz. `kos` yalnız bir ajan komutu (--ajan ya da ayar.toml) VE
açık bir bütçe (--butce-usd) verilince çalışır.

Betikler ve ajan sır adlı (KEY/TOKEN/SECRET/PASSW/CREDENTIAL/AUTH) ya da sır görünümlü ortam değişkenlerini
görmez. Ajanın kendi API anahtarı: `vaka kos --ortam-izin AD` ya da ayar.toml'da `[ajan] ortam_izin = ["AD"]`.

Çıkış kodları: 0 tamam; 1 geçersiz vaka, vaka yok ya da ayar hatası; 2 ajan en az bir koşuda kaldı
(`baglamsiz` kolunun kalması beklenen bulgudur, sayılmaz) ya da kullanım hatası; 3 bütçe doldu (atlanan koşu var).
`hakem-sina`: 0 hiçbir saldırı kandırmadı; 1 hakem hatası ya da denetim tutmadı (hakem geçersiz); 2 en az bir
saldırı kandırdı ya da kullanım hatası; 3 bütçe doldu. `dogrula-gunluk`: 0 geçerli; 1 geçersiz ya da okunamadı.
"""
import argparse
import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from vaka import __version__, hakem
from vaka.ajan import KOLLAR, ajan_kos, kollar
from vaka.ayar import ENV_AD, ajan_ayari
from vaka.bicim import ID_DESENI, baglam_metni, iskelet, vaka_yukle
from vaka.butce import Butce
from vaka.dogrula import vaka_dogrula
from vaka.gunluk import (
    OZET_BASLIK,
    GunlukHatasi,
    gunluk_dogrula,
    kos_gunlugu_ac,
    ozet_bayt,
    ozet_satirlari,
    senaryo_kaydet,
)
from vaka.rapor import (
    AJAN_BASLIK,
    DOGRULAMA_BASLIK,
    FARK_BASLIK,
    ajan_satirlari,
    dogrulama_satirlari,
    dosya_yaz,
    json_yaz,
    kol_farki,
    md_yaz,
    ozet_oran,
    tablo,
)

VARSAYILAN_DIZIN = Path("vakalar")


def _yaz(metin_, dosya=None):
    """CRLF ya da TextIOWrapper olmayan stdout'ta da LF bas."""
    dosya = dosya or sys.stdout
    tampon = getattr(dosya, "buffer", None)
    if tampon is not None:
        dosya.flush()
        tampon.write((metin_ + "\n").encode("utf-8"))
        tampon.flush()
    else:
        dosya.write(metin_ + "\n")


def _ortak(p):
    p.add_argument("--vakalar", type=Path, default=VARSAYILAN_DIZIN,
                   help="vaka klasörü (alt klasörler dahil; regresyon/ alt klasörü regresyon paketidir)")
    p.add_argument("--suite", choices=("yetenek", "regresyon", "hepsi"))
    p.add_argument("--vaka", action="append", help="yalnız bu vaka kimliği (tekrarlanabilir)")


def _rapor_args(p):
    p.add_argument("--json", type=Path, help="sonuç JSON dosyası")
    p.add_argument("--md", type=Path, help="sonuç Markdown dosyası")


def parser():
    ap = argparse.ArgumentParser(prog="vaka", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"vaka {__version__}")
    alt = ap.add_subparsers(dest="komut", required=True)
    d = alt.add_parser("dogrula", help="vakaları doğrula: referans geçer, negatif kalır, boş durum geçmez")
    _ortak(d)
    _rapor_args(d)
    k = alt.add_parser("kos", help="gerçek ajanı vakalarda koştur (bütçe zorunlu)")
    _ortak(k)
    _rapor_args(k)
    k.add_argument("--ajan", help="ajan komut şablonu (ayar.toml [ajan] komut yerine)")
    k.add_argument("--ayar", type=Path, help="ayar.toml yolu (VAKA_AYAR yerine)")
    k.add_argument("--butce-usd", type=float, required=True, metavar="X",
                   help="SERT maliyet sınırı (USD). Dolunca yeni koşu başlamaz; kalanlar atlanır")
    k.add_argument("--butce-defter", type=Path, metavar="DOSYA",
                   help="paralel süreçler arasında ortak maliyet defteri (vars.: geçici dosya)")
    k.add_argument("--tahmini-kosu-usd", type=float, metavar="X",
                   help="koşu başı maliyet tohumu (ayar.toml'daki değerin yerine)")
    k.add_argument("--kol", choices=("ikisi",) + KOLLAR, default="ikisi")
    k.add_argument("--tekrar", type=int, default=1, help="her senaryo kaç kez (pass@k)")
    k.add_argument("--varyant-tekrar", type=int, help="varyantlar kaç kez (vars. --tekrar)")
    k.add_argument("--ajan-env", action="append", default=[], metavar="AD=DEGER", help="ajana ek ortam")
    k.add_argument("--ortam-izin", action="append", default=[], metavar="AD",
                   help="ayıklanan sır adlı değişkeni (ör. ajanın API anahtarı) yalnız ajana geçir (tekrarlanabilir)")
    k.add_argument("--gunluk", type=Path, metavar="DIZIN",
                   help="doğrulanabilir olay günlüğü yaz (yeni dizin; bkz. vaka dogrula-gunluk)")
    y = alt.add_parser("yeni", help="olay notundan yeni vaka iskeleti yaz")
    y.add_argument("id")
    y.add_argument("--vakalar", type=Path, default=VARSAYILAN_DIZIN)
    y.add_argument("--suite", choices=("yetenek", "regresyon"), default="yetenek")
    liste = alt.add_parser("liste", help="vakaları listele")
    _ortak(liste)
    h = alt.add_parser("hakem-sina", help="otomatik hakemi bilinen hilelere karşı dene (hazır hakemler model çağırmaz)")
    h.add_argument("--ornek-hakem", choices=tuple(hakem.ORNEK_HAKEMLER), help="hazır hakem (model çağrısı yok)")
    h.add_argument("--hakem", metavar="KOMUT", help="hakem komut şablonu; girdi stdin'de ve {girdi_dosyasi}'nda")
    h.add_argument("--hakem-py", metavar="DOSYA.py:AD", help="Python hakemi (bu süreçte, ortam ayıklanmadan çalışır)")
    h.add_argument("--liste", action="store_true", help="saldırıları ve görevleri listele")
    h.add_argument("--saldiri", action="append", metavar="ID", help="yalnız bu saldırı (tekrarlanabilir)")
    h.add_argument("--gorev", action="append", metavar="ID", help="yalnız bu görev (tekrarlanabilir)")
    h.add_argument("--tekrar", type=int, default=1, help="her girdi kaç kez sorulur (rastgele hakemler için)")
    h.add_argument("--esik", type=float, default=hakem.ESIK, help="puan veren hakemde GEÇTİ eşiği")
    h.add_argument("--butce-usd", type=float, metavar="X", help="SERT maliyet sınırı (--hakem/--hakem-py ile zorunlu)")
    h.add_argument("--butce-defter", type=Path, metavar="DOSYA", help="paralel süreçlerle ortak maliyet defteri")
    h.add_argument("--tahmini-kosu-usd", type=float, default=0.01, metavar="X", help="çağrı başı maliyet tohumu")
    h.add_argument("--zaman-asimi-sn", type=int, default=120, help="komut hakemde çağrı başı zaman aşımı")
    h.add_argument("--ortam-izin", action="append", default=[], metavar="AD",
                   help="ayıklanan sır adlı değişkeni yalnız hakem komutuna geçir (tekrarlanabilir)")
    h.add_argument("--hakem-env", action="append", default=[], metavar="AD=DEGER", help="hakem komutuna ek ortam")
    h.add_argument("--kendi-ev", action="store_true", help="hakem komutu kendi HOME'unla çalışsın")
    _rapor_args(h)
    g = alt.add_parser("dogrula-gunluk", help="olay günlüğünü doğrula (özet zinciri, sıra, nesneler) ve özetle")
    g.add_argument("dizin", type=Path)
    g.add_argument("--beklenen-bas", metavar="OZET", help="son olayın beklenen özeti (sonuç JSON'undaki bas_ozet)")
    g.add_argument("--yarim-kabul", action="store_true", help="kosu.bitti olmayan (yarım) günlüğü kabul et")
    g.add_argument("--olaylar", action="store_true", help="olayları tek tek listele")
    g.add_argument("--json", type=Path, help="doğrulama sonucu JSON dosyası")
    return ap


def _yukle(a, varsayilan_suite):
    try:
        return vaka_yukle(a.vakalar, set(a.vaka) if a.vaka else None, a.suite or varsayilan_suite)
    except ValueError as exc:
        _yaz(f"hata: {exc}", sys.stderr)
        return None


def dogrula_komutu(a):
    vakalar = _yukle(a, "hepsi")
    if not vakalar:
        _yaz("vaka bulunamadı" if vakalar is not None else "vakalar okunamadı", sys.stderr)
        return 1
    sonuc = [vaka_dogrula(v) for v in vakalar]
    _yaz(tablo(dogrulama_satirlari(sonuc), DOGRULAMA_BASLIK))
    for s in sonuc:
        for p in s["sorunlar"]:
            _yaz(f"  ! {s['id']}: {p}", sys.stderr)
    if a.json:
        json_yaz(a.json, "dogrulama", sonuc)
    if a.md:
        md_yaz(a.md, "dogrulama", sonuc)
    return 0 if all(s["gecerli"] for s in sonuc) else 1


def kos_komutu(a):
    try:
        ayar = ajan_ayari(a.ayar)
    except ValueError as exc:
        _yaz(f"ayar hatası: {exc}", sys.stderr)
        return 1
    if a.ajan:
        ayar = replace(ayar, komut=a.ajan)
    gecersiz = [x for x in a.ortam_izin if not ENV_AD.fullmatch(x)]
    if gecersiz:
        _yaz("--ortam-izin bir ortam değişkeni adı olmalı: " + ", ".join(gecersiz), sys.stderr)
        return 2
    ayar = replace(ayar, ortam_izin=tuple(dict.fromkeys(ayar.ortam_izin + tuple(a.ortam_izin))))
    if not ayar.komut:
        _yaz("ajan komutu yok: --ajan ver ya da ayar.toml'da [ajan] komut yaz. "
             "Varsayılan olarak ajan koşmaz; `vaka dogrula` model çağırmaz.", sys.stderr)
        return 1
    if a.butce_usd < 0 or a.tekrar < 1 or (a.varyant_tekrar is not None and a.varyant_tekrar < 0):
        _yaz("--butce-usd >= 0, --tekrar >= 1 olmalı", sys.stderr)
        return 2
    vakalar = _yukle(a, "yetenek")
    if not vakalar:
        _yaz("vaka bulunamadı", sys.stderr)
        return 1
    for v in vakalar:  # bozuk bağlam (vaka klasörü dışı yol, eksik dosya) bütçe harcanmadan durdurur
        try:
            baglam_metni(v)
        except (OSError, ValueError) as exc:
            _yaz(f"hata: {v.get('id') or v.get('_dosya')}: {exc}", sys.stderr)
            return 1
    ek = {}
    for x in a.ajan_env:
        if "=" not in x:
            _yaz(f"--ajan-env AD=DEGER olmalı: {x}", sys.stderr)
            return 2
        ad, deger = x.split("=", 1)
        ek[ad] = deger
    _yaz(ortam_bildirimi(ayar.ortam_izin, ek), sys.stderr)
    gunluk = None
    if a.gunluk:
        bilgi = {"arac": "vaka", "surum": __version__, "komut_ozeti": ozet_bayt(ayar.komut.encode("utf-8")),
                 "kol": a.kol, "tekrar": a.tekrar, "varyant_tekrar": a.varyant_tekrar, "butce_usd": a.butce_usd,
                 "ortam_izin": list(ayar.ortam_izin), "ajan_env_adlari": list(ek)}
        try:
            gunluk = kos_gunlugu_ac(a.gunluk, bilgi, vakalar)
        except (OSError, GunlukHatasi) as exc:
            _yaz(f"günlük açılamadı: {exc}", sys.stderr)
            return 1
    with tempfile.TemporaryDirectory(prefix="vaka-butce-") as gecici:
        defter = a.butce_defter or Path(gecici) / "defter.txt"
        butce = Butce(a.butce_usd, defter, a.tahmini_kosu_usd or ayar.tahmini_kosu_usd)
        if gunluk is None:
            return _kos(a, ayar, vakalar, ek, butce)
        try:
            return _kos(a, ayar, vakalar, ek, butce, gunluk)
        except BaseException as exc:
            if not gunluk.kapali:  # yarım koşu: kesildiği günlüğe yazılır, doğrulama yine yakalar
                try:
                    gunluk.kapat({"kesildi": type(exc).__name__})
                except (OSError, GunlukHatasi):
                    pass
            raise


def ortam_bildirimi(izin, ek, env=None):
    """Ajana geçirilen değişkenlerin ADLARI (değerleri asla) tek satırda."""
    env = os.environ if env is None else env
    gecen = [ad for ad in izin if ad in env]
    satir = "ortam: sır adlı/sır görünümlü değişkenler ayıklandı; ajana geçirilen: " + (", ".join(gecen) or "yok")
    eksik = [ad for ad in izin if ad not in env]
    if eksik:
        satir += " (ortamda yok: " + ", ".join(eksik) + ")"
    if ek:
        satir += "; --ajan-env: " + ", ".join(ek)
    return satir


def _kos(a, ayar, vakalar, ek, butce, gunluk=None):
    sonuc = []
    for v in vakalar:
        for kol in kollar(v, a.kol):
            gozlemci = None if gunluk is None else (lambda s, v=v, kol=kol: senaryo_kaydet(gunluk, v["id"], kol, s))
            sonuc.append(ajan_kos(v, ayar, kol=kol, tekrar=a.tekrar, varyant_tekrar=a.varyant_tekrar,
                                  butce=butce, ek_env=ek, gozlemci=gozlemci))
    _yaz(tablo(ajan_satirlari(sonuc), AJAN_BASLIK))
    for kol in dict.fromkeys(s["kol"] for s in sonuc):
        g, k, at, o = ozet_oran(sonuc, kol)
        _yaz(f"{kol or '-'}: {g}/{k} = {'-' if o is None else format(o, '.3f')} (bütçeden atlanan: {at})")
    fark = kol_farki(sonuc)
    if fark:
        _yaz("\nBağlamın katkısı (geçme oranı):\n" + tablo(fark, FARK_BASLIK))
    bilgi = {"sinir_usd": butce.sinir, "harcanan_usd": round(butce.harcanan(), 6),
             "defter": str(a.butce_defter) if a.butce_defter else None}
    ek_bilgi = f" (defter {a.butce_defter})" if a.butce_defter else ""
    _yaz(f"Harcanan: {bilgi['harcanan_usd']:.4f} USD / sınır {butce.sinir} USD{ek_bilgi}")
    kod = 0 if all(s["gecti"] is not False for s in sonuc if s["kol"] != "baglamsiz") else 2
    if kod == 0 and any(s.get("atlandi_butce") for s in sonuc):
        kod = 3
    kayit = None
    if gunluk is not None:
        gunluk.kapat({"cikis_kodu": kod, "harcanan_usd": bilgi["harcanan_usd"], "sinir_usd": butce.sinir})
        kayit = {"dizin": str(gunluk.dizin), "bas_ozet": gunluk.bas_ozet}
        _yaz(f"Günlük: {gunluk.dizin} (baş özeti {gunluk.bas_ozet})")
    if a.json:
        json_yaz(a.json, "ajan", sonuc, bilgi, gunluk=kayit)
    if a.md:
        md_yaz(a.md, "ajan", sonuc, bilgi, gunluk=kayit)
    return kod


def yeni_komutu(a):
    if not ID_DESENI.fullmatch(a.id):
        _yaz("id küçük harf, rakam ve tire olmalı", sys.stderr)
        return 2
    dizin = a.vakalar / "regresyon" if a.suite == "regresyon" else a.vakalar
    yol = dizin / f"{a.id}.json"
    if yol.exists():
        _yaz(f"zaten var: {yol}", sys.stderr)
        return 1
    dizin.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(iskelet(a.id, a.suite), ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    _yaz(f"yazıldı: {yol}\nAlanları doldur, sonra: vaka dogrula --vakalar {a.vakalar} --vaka {a.id}")
    return 0


def liste_komutu(a):
    vakalar = _yukle(a, "hepsi")
    if vakalar is None:
        return 1
    _yaz(tablo([[v.get("id", "?"), v["suite"], v.get("hata_sinifi", "-"), len(v.get("varyantlar") or []),
                 "evet" if v.get("baglam") else "-"] for v in vakalar],
               ["vaka", "paket", "sınıf", "varyant", "bağlam"]))
    return 0


def _hakem_liste():
    _yaz(tablo([[s.id, ", ".join(s.turler), s.aciklama] for s in hakem.SALDIRILAR], ["saldırı", "görev türleri",
                                                                                        "açıklama"]))
    _yaz("")
    _yaz(tablo([[g.id, g.tur] for g in hakem.GOREVLER], ["görev", "tür"]))
    return 0


def _hakem_sec(a):
    """(hakem, ad) ya da hata kodu."""
    secilen = [x for x in (a.ornek_hakem, a.hakem, a.hakem_py) if x]
    if len(secilen) != 1:
        _yaz("tam bir hakem ver: --ornek-hakem saf|saglam, --hakem KOMUT ya da --hakem-py DOSYA.py:AD", sys.stderr)
        return 2
    if a.ornek_hakem:
        return hakem.ORNEK_HAKEMLER[a.ornek_hakem], f"ornek:{a.ornek_hakem}"
    if a.butce_usd is None:
        _yaz("kullanıcı hakemi model çağırabilir: --butce-usd zorunlu (hazır hakemlerde gerekmez)", sys.stderr)
        return 2
    if a.hakem_py:
        try:
            return hakem.py_hakem_yukle(a.hakem_py), a.hakem_py
        except Exception as exc:  # noqa: BLE001 - kullanıcı kodu yüklenirken her hata olabilir
            _yaz(f"hakem yüklenemedi: {exc}", sys.stderr)
            return 1
    gecersiz = [x for x in a.ortam_izin if not ENV_AD.fullmatch(x)]
    if gecersiz:
        _yaz("--ortam-izin bir ortam değişkeni adı olmalı: " + ", ".join(gecersiz), sys.stderr)
        return 2
    ek = {}
    for x in a.hakem_env:
        if "=" not in x:
            _yaz(f"--hakem-env AD=DEGER olmalı: {x}", sys.stderr)
            return 2
        ad, deger = x.split("=", 1)
        ek[ad] = deger
    _yaz("ortam: sır adlı/sır görünümlü değişkenler ayıklandı; hakeme geçirilen: "
         + (", ".join(x for x in a.ortam_izin if x in os.environ) or "yok"), sys.stderr)
    return hakem.KomutHakem(a.hakem, a.zaman_asimi_sn, a.ortam_izin, ek, a.kendi_ev), "komut"


def hakem_komutu(a):
    if a.liste:
        return _hakem_liste()
    if a.tekrar < 1 or (a.butce_usd is not None and a.butce_usd < 0) or a.zaman_asimi_sn < 1:
        _yaz("--tekrar >= 1, --butce-usd >= 0, --zaman-asimi-sn >= 1 olmalı", sys.stderr)
        return 2
    try:
        saldirilar = hakem.sec(a.saldiri, hakem.SALDIRILAR, "saldırı")
        gorevler = hakem.sec(a.gorev, hakem.GOREVLER, "görev")
    except ValueError as exc:
        _yaz(str(exc), sys.stderr)
        return 2
    secim = _hakem_sec(a)
    if isinstance(secim, int):
        return secim
    h, ad = secim
    with tempfile.TemporaryDirectory(prefix="vaka-butce-") as gecici:
        butce = None
        if a.butce_usd is not None:
            butce = Butce(a.butce_usd, a.butce_defter or Path(gecici) / "defter.txt", a.tahmini_kosu_usd)
        sonuc = hakem.hakem_sina(h, saldirilar, gorevler, tekrar=a.tekrar, esik=a.esik, butce=butce)
        bilgi = None if butce is None else {"sinir_usd": butce.sinir, "harcanan_usd": round(butce.harcanan(), 6),
                                            "defter": str(a.butce_defter) if a.butce_defter else None}
    _yaz(tablo(hakem.saldiri_satirlari(sonuc), hakem.HAKEM_BASLIK))
    _yaz(hakem.kontrol_satiri(sonuc))
    _yaz(hakem.ozet_satiri(sonuc))
    if bilgi:
        _yaz(f"Harcanan: {bilgi['harcanan_usd']:.4f} USD / sınır {bilgi['sinir_usd']} USD")
    for s in hakem.sorun_satirlari(sonuc):
        _yaz(f"  ! {s}", sys.stderr)
    if a.json:
        json_yaz(a.json, "hakem", {"hakem": ad, **sonuc}, bilgi)
    if a.md:
        dosya_yaz(a.md, hakem.markdown(sonuc, ad))
    return hakem.cikis_kodu(sonuc)


def gunluk_komutu(a):
    d = gunluk_dogrula(a.dizin, tamam_sart=not a.yarim_kabul, beklenen_bas=a.beklenen_bas)
    if a.olaylar:
        _yaz(tablo([[o["sira"], o["tur"], o["zaman"], str(o["ozet"])[:19]] for o in d.olaylar],
                   ["sıra", "tür", "zaman", "özet"]))
    ozet = ozet_satirlari(d.olaylar) if d.gecerli else None
    if d.gecerli:
        _yaz(f"GEÇERLİ: {len(d.olaylar)} olay, koşu {d.kosu}, " + ("tamam" if d.tamam else "YARIM")
             + f", satır sonu {d.satir_sonu}")
        _yaz(f"Baş özeti: {d.bas_ozet}")
        if ozet:
            _yaz(tablo(ozet, OZET_BASLIK))
    else:
        _yaz(f"GEÇERSİZ: {len(d.sorunlar)} sorun")
        for s in d.sorunlar[:50]:
            _yaz(f"  ! {s}", sys.stderr)
        if len(d.sorunlar) > 50:
            _yaz(f"  ! ... {len(d.sorunlar) - 50} sorun daha", sys.stderr)
    if a.json:
        json_yaz(a.json, "gunluk", {**d.sozluk(), "ozet": ozet})
    return 0 if d.gecerli else 1


def main(argv=None):
    a = parser().parse_args(argv)
    return {"dogrula": dogrula_komutu, "kos": kos_komutu, "yeni": yeni_komutu, "liste": liste_komutu,
            "hakem-sina": hakem_komutu, "dogrula-gunluk": gunluk_komutu}[a.komut](a)


def cli():
    # Windows konsolu (cp1252) Türkçe harfte çöker; çıktıyı UTF-8'e çevir.
    for akis in (sys.stdout, sys.stderr):
        if hasattr(akis, "reconfigure"):
            akis.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())


if __name__ == "__main__":
    cli()
