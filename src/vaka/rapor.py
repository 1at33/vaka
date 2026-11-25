"""Raporlar: terminal tablosu, Markdown, JSON.

Sonuç/rapor dosyaları yalnız sahibinin okuyabileceği izinle (0o600, platform destekliyorsa) yazılır: içlerinde
maskelenmiş de olsa ajan ve kontrol çıktısı bulunur.
"""
import json
import os
import stat


def tablo(satirlar, basliklar):
    gen = [max(len(str(r[i])) for r in [basliklar] + satirlar) for i in range(len(basliklar))]
    bicim = "  ".join(f"{{:<{g}}}" for g in gen)
    return "\n".join([bicim.format(*basliklar), bicim.format(*("-" * g for g in gen))]
                     + [bicim.format(*map(str, r)) for r in satirlar])


def md_tablo(satirlar, basliklar):
    return "\n".join(["| " + " | ".join(map(str, basliklar)) + " |", "|" + "---|" * len(basliklar)]
                     + ["| " + " | ".join(map(str, r)) + " |" for r in satirlar])


def dogrulama_satirlari(sonuc):
    satir = []
    for s in sonuc:
        ana = s["senaryolar"][0] if s["senaryolar"] else None
        satir.append([s["id"], s.get("suite") or "-", s.get("hata_sinifi", "-"),
                      ("geçti" if ana["referans"]["gecti"] else "KALDI") if ana else "-",
                      ("kaldı" if not ana["negatif"]["gecti"] else "GEÇTİ") if ana else "-",
                      len(s["senaryolar"]), "GEÇERLİ" if s["gecerli"] else "GEÇERSİZ"])
    return satir


DOGRULAMA_BASLIK = ["vaka", "paket", "sınıf", "referans->kontrol", "negatif->kontrol", "senaryo", "durum"]


def ozet_oran(sonuc, kol):
    """(geçen, koşu, atlanan, oran|None). Bütçeden atlanan koşular paydaya girmez."""
    g = sum(s["gecen"] for s in sonuc if s["kol"] == kol)
    k = sum(s["kosu"] for s in sonuc if s["kol"] == kol)
    a = sum(s.get("atlandi_butce", 0) for s in sonuc if s["kol"] == kol)
    return g, k, a, (g / k if k else None)


def kol_farki(sonuc):
    """Vaka başına baglam ve baglamsiz geçme oranları ve fark."""
    satirlar = []
    for vid in dict.fromkeys(s["id"] for s in sonuc):
        oran = {s["kol"]: s["gecen"] / s["kosu"] for s in sonuc if s["id"] == vid and s["kosu"]}
        if "baglam" in oran and "baglamsiz" in oran:
            satirlar.append([vid, f"{oran['baglam']:.2f}", f"{oran['baglamsiz']:.2f}",
                             f"{oran['baglam'] - oran['baglamsiz']:+.2f}"])
    return satirlar


def ajan_satirlari(sonuc):
    return [[s["id"], s["kol"] or "-", f"{s['gecen']}/{s['kosu']}",
             "ATLANDI(bütçe)" if s["gecti"] is None else ("GEÇTİ" if s["gecti"] else "KALDI"),
             s.get("atlandi_butce", 0)] for s in sonuc]


AJAN_BASLIK = ["vaka", "kol", "geçen/koşu", "ajan", "atlanan"]
FARK_BASLIK = ["vaka", "baglam", "baglamsiz", "fark"]


def markdown(mod, sonuc, butce=None, gunluk=None):
    if mod == "dogrulama":
        parca = ["# Vaka doğrulaması", "", md_tablo(dogrulama_satirlari(sonuc), DOGRULAMA_BASLIK)]
        sorun = [f"- `{s['id']}`: {p}" for s in sonuc for p in s["sorunlar"]]
        if sorun:
            parca += ["", "## Sorunlar", ""] + sorun
        return "\n".join(parca) + "\n"
    parca = ["# Ajan koşusu", "", md_tablo(ajan_satirlari(sonuc), AJAN_BASLIK), ""]
    for kol in dict.fromkeys(s["kol"] for s in sonuc):
        g, k, a, o = ozet_oran(sonuc, kol)
        parca.append(f"- {kol or '-'}: {g}/{k} = {'-' if o is None else format(o, '.3f')} (bütçeden atlanan: {a})")
    fark = kol_farki(sonuc)
    if fark:
        parca += ["", "## Bağlamın katkısı", "", md_tablo(fark, FARK_BASLIK)]
    if butce:
        parca += ["", f"Harcanan: {butce['harcanan_usd']:.4f} USD / sınır {butce['sinir_usd']} USD"]
    if gunluk:
        parca += ["", f"Olay günlüğü: `{gunluk['dizin']}` (baş özeti `{gunluk['bas_ozet']}`)"]
    return "\n".join(parca) + "\n"


def dosya_yaz(yol, metin_):
    """UTF-8, LF; yeni dosya 0o600 açılır, var olan normal dosyanın izni de 0o600'e çekilir (POSIX)."""
    fd = os.open(yol, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        if hasattr(os, "fchmod") and stat.S_ISREG(os.fstat(fd).st_mode):
            os.fchmod(fd, 0o600)
        f.write(metin_.encode("utf-8"))


def json_yaz(yol, mod, sonuc, butce=None, gunluk=None):
    """`gunluk` (dizin ve baş özeti) yalnız olay günlüğü tutulduysa eklenir; sonuç dosyası günlüğü bağlar."""
    veri = {"mod": mod, "sonuc": sonuc, "butce": butce}
    if gunluk is not None:
        veri["gunluk"] = gunluk
    dosya_yaz(yol, json.dumps(veri, ensure_ascii=False, indent=2) + "\n")


def md_yaz(yol, mod, sonuc, butce=None, gunluk=None):
    dosya_yaz(yol, markdown(mod, sonuc, butce, gunluk))
