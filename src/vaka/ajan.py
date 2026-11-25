"""Takılabilir ajan koşucusu. Yalnız kullanıcı bir komut verdiğinde ve bütçe koyduğunda çalışır.

Komut, kum havuzunun `calisma/` klasöründe bash ile çalışır. Şablon yer tutucuları (tırnaklı yol):

    {girdi_dosyasi}   görev metni dosyası (../GIRDI.txt)
    {baglam_dosyasi}  `baglam` kolunda ../BAGLAM.md, öteki kollarda boş dize ('')
    {calisma}         çalışma klasörü

Ortamda VAKA_GIRDI (görev metni) ve `baglam` kolunda VAKA_BAGLAM_DOSYASI vardır; vakanın `ortam.env`
değişkenleri de eklenir. Kullanıcının sır adlı/sır görünümlü değişkenleri ayıklanmıştır (kum.miras_alinir);
`ayar.ortam_izin` adları yalnız ajana geri açılır. Kontrolün kullandığı kök dosyaları (taban-commit vb.) ajan
çalışırken ayrı bir yere taşınır, kontrolden önce geri konur. Komutun stdout'unun SON satırı JSON ise `maliyet_usd` alanı bütçeye yazılır.
Sonuca giren ajan ve kontrol çıktısı kırpılmadan önce `maskele` ile sırlardan arındırılır.

Kollar (yetenek vakalarında, vakada `baglam` varsa): `baglam` (kullanıcının kural/not alıntısı verilir) ve
`baglamsiz` (hiçbir şey). Fark = notların ölçülen katkısı. Regresyon vakaları tek kolda ("-") koşar.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from vaka.bicim import baglam_metni
from vaka.dogrula import kontrol
from vaka.kum import BASH, WIN_ONEK, bash_yolu, kaldir, kum_havuzu, sil
from vaka.yardimci import maskele

KOLLAR = ("baglam", "baglamsiz")
KOK_KALIR = ("calisma", "home", "uzak.git", "GIRDI.txt", "BAGLAM.md")


def kontrol_dosyalarini_sakla(kok, gorunur=()):
    """Kökteki kontrol dosyalarını ajan görmesin (ajan `ls ..` yapabilir). `ortam.gorunur` kalır."""
    saklik = Path(tempfile.mkdtemp(prefix="vaka-k-"))
    kalir = set(KOK_KALIR) | set(gorunur)
    for p in list(kok.iterdir()):
        if p.name not in kalir:
            shutil.move(str(p), str(saklik / p.name))
    return saklik


def kontrol_dosyalarini_geri_koy(kok, saklik):
    for p in saklik.iterdir():
        shutil.move(str(p), str(kok / p.name))
    sil(saklik)


def komut_ac(sablon, kok, baglam_var):
    return (sablon.replace("{girdi_dosyasi}", bash_yolu(kok / "GIRDI.txt"))
            .replace("{baglam_dosyasi}", bash_yolu(kok / "BAGLAM.md") if baglam_var else "''")
            .replace("{calisma}", bash_yolu(kok / "calisma")))


def son_satir_json(stdout):
    satirlar = stdout.strip().splitlines()
    if not satirlar:
        return None
    try:
        v = json.loads(satirlar[-1])
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def maliyet_al(ozet):
    m = (ozet or {}).get("maliyet_usd")
    return float(m) if isinstance(m, (int, float)) and not isinstance(m, bool) and m >= 0 else None


def kollar(vaka, secim="ikisi"):
    """Vakanın koşacağı kollar. Regresyon ya da bağlamsız vaka: [None]."""
    if vaka.get("suite") == "regresyon" or not baglam_metni(vaka):
        return [None]
    return list(KOLLAR) if secim == "ikisi" else [secim]


def tek_kosu(vaka, varyant, kol, ayar, ek_env=None):
    baglam = baglam_metni(vaka) if kol == "baglam" else None
    kok, calisma, env_e, env_k = kum_havuzu(vaka, varyant, baglam)
    saklik = None
    try:
        saklik = kontrol_dosyalarini_sakla(kok, (vaka.get("ortam") or {}).get("gorunur") or ())
        if ayar.kendi_ev:
            env_e["HOME"] = os.environ.get("HOME", env_e["HOME"])
            if os.name == "nt" and os.environ.get("USERPROFILE"):
                env_e["USERPROFILE"] = os.environ["USERPROFILE"]
        for ad in ayar.ortam_izin:  # ayıklanan sırlardan kullanıcının açıkça izin verdikleri; yalnız ajana
            if ad in os.environ:
                env_e[ad] = os.environ[ad]
        env_e.update(ek_env or {})
        env_e["VAKA_GIRDI"] = (kok / "GIRDI.txt").read_text(encoding="utf-8").rstrip("\n")
        if baglam:
            env_e["VAKA_BAGLAM_DOSYASI"] = str(kok / "BAGLAM.md")
        komut = komut_ac(ayar.komut, kok, bool(baglam))
        kanarya, gizli_env = env_k.get("KANARYA"), {**os.environ, **env_e}
        t0 = time.time()
        try:
            r = subprocess.run([BASH, "-c", WIN_ONEK + komut], cwd=calisma, env=env_e, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=ayar.zaman_asimi_sn,
                               check=False)
            rc, cikti = r.returncode, r.stdout
            ham = maskele(r.stdout + r.stderr, kanarya, gizli_env)[-500:]
        except subprocess.TimeoutExpired:
            rc, cikti, ham = 124, "", "zaman aşımı"
        sure = round(time.time() - t0, 1)
        ozet = son_satir_json(cikti)
        kontrol_dosyalarini_geri_koy(kok, saklik)
        saklik = None
        gecti, kcikti = kontrol(vaka, calisma, env_k)
        return {"senaryo": (varyant or {}).get("ad", "ana"), "gecti": gecti, "ajan_cikis": rc, "sure_sn": sure,
                "maliyet_usd": maliyet_al(ozet),
                "kontrol_cikti": maskele(kcikti, kanarya, gizli_env)[-300:],
                "baglam_dosyasi": baglam is not None, "ajan_cikti": ham}
    finally:
        if saklik is not None and saklik.exists():
            sil(saklik)
        kaldir(kok)


def ajan_kos(vaka, ayar, kol=None, tekrar=1, varyant_tekrar=None, butce=None, ek_env=None):
    """Her senaryo `tekrar` kez koşar (varyantlar `varyant_tekrar`). Bütçe dolunca kalan koşular BAŞLAMAZ,
    `atlandi_butce` olur: kaldı sayılmaz, orana girmez."""
    if not ayar.komut:
        raise ValueError("ajan komutu yok: --ajan ver ya da ayar.toml'da [ajan] komut yaz")
    sonuclar = []
    for varyant in [None] + list(vaka.get("varyantlar") or []):
        n_tekrar = tekrar if varyant is None or varyant_tekrar is None else varyant_tekrar
        for n in range(1, n_tekrar + 1):
            senaryo = (varyant or {}).get("ad", "ana")
            kimlik = butce.baslat() if butce is not None else None
            if butce is not None and kimlik is None:
                sonuclar.append({"senaryo": senaryo, "deneme": n, "gecti": None, "atlandi_butce": True})
                continue
            try:
                s = tek_kosu(vaka, varyant, kol, ayar, ek_env)
            except BaseException:
                if kimlik is not None:
                    butce.iptal(kimlik)
                raise
            if kimlik is not None:
                butce.bitir(kimlik, s["maliyet_usd"])
            sonuclar.append({"deneme": n, **s})
    kosan = [s for s in sonuclar if not s.get("atlandi_butce")]
    return {"id": vaka["id"], "kol": kol, "suite": vaka.get("suite"),
            "gecti": all(s["gecti"] for s in kosan) if kosan else None,
            "gecen": sum(bool(s["gecti"]) for s in kosan), "kosu": len(kosan),
            "atlandi_butce": len(sonuclar) - len(kosan), "senaryolar": sonuclar}
