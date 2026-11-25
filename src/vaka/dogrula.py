"""Vaka doğrulaması: vakanın kendisi adil ve çözülebilir mi? Model çağrısı yok.

Her senaryo (ana + varyantlar) için ayrı kum havuzlarında:

  1. referans_cozum çalışır  -> kontrol GEÇMELİ (vaka çözülebilir)
  2. negatif çalışır         -> kontrol KALMALI (kontrol ihlali gerçekten yakalıyor)
  3. hiçbir şey yapılmaz     -> kontrol geçerse "ücretsiz yol" (bos_durum_gecebilir demedikçe)

Biri tutmazsa vaka GEÇERSİZdir. Rapora giren kontrol çıktısı kırpılmadan önce `maskele` ile sırlardan arındırılır.
"""
import os

from vaka.bicim import bicim_hatalari, eksik_alanlar, metin
from vaka.kum import calistir, kaldir, kum_havuzu
from vaka.yardimci import maskele


def kontrol(vaka, calisma, env_k, timeout=60):
    """Kontrol sözleşmesi: çıkış 0 VE `gecer_cikti` çıktıda geçiyorsa GEÇTİ."""
    k = vaka["kontrol"]
    rc, cikti = calistir(metin(k["komut"]), calisma, env_k, timeout=timeout, yardimci=True)
    return (rc == 0 and k["gecer_cikti"] in cikti), cikti


def adim(vaka, ad, varyant=None, betik=None):
    """Taze bir kum havuzunda betiği (ya da hiçbir şeyi) çalıştır, kontrolü uygula."""
    kok, calisma, env_e, env_k = kum_havuzu(vaka, varyant)
    try:
        rc, _ = calistir(metin(betik), calisma, env_e) if betik else (0, "")
        gecti, cikti = kontrol(vaka, calisma, env_k)
        cikti = maskele(cikti, env_k.get("KANARYA"), {**os.environ, **env_e})
        return {"adim": ad, "gecti": gecti, "kontrol_cikti": cikti[-300:], "eylem_cikis": rc}
    finally:
        kaldir(kok)


def senaryo_dogrula(vaka, varyant=None):
    ad = (varyant or {}).get("ad", "ana")
    ref = (varyant or {}).get("referans_cozum") or vaka["referans_cozum"]
    neg = (varyant or {}).get("negatif") or vaka["negatif"]
    r = adim(vaka, "referans", varyant, ref)
    n = adim(vaka, "negatif", varyant, neg)
    b = adim(vaka, "bos", varyant, None)
    sorunlar = []
    if not r["gecti"]:
        sorunlar.append(f"{ad}: referans çözüm kontrolden GEÇMEDİ ({r['kontrol_cikti']})")
    if n["gecti"]:
        sorunlar.append(f"{ad}: negatif (yanlış davranış) kontrolü GEÇTİ; kontrol ihlali yakalamıyor")
    if b["gecti"] and not (varyant or {}).get("bos_gecebilir") and not vaka.get("bos_durum_gecebilir"):
        sorunlar.append(f"{ad}: hiçbir şey yapılmayan durum kontrolü geçiyor (ücretsiz yol)")
    return {"senaryo": ad, "referans": r, "negatif": n, "bos_gecti": b["gecti"], "sorunlar": sorunlar}


def vaka_dogrula(vaka):
    vid = vaka.get("id") or vaka.get("_dosya", "?")
    sorunlar = [f"eksik alan: {', '.join(e)}" for e in [eksik_alanlar(vaka)] if e] + bicim_hatalari(vaka)
    if sorunlar:
        return {"id": vid, "suite": vaka.get("suite"), "gecerli": False, "sorunlar": sorunlar, "senaryolar": []}
    try:
        senaryolar = [senaryo_dogrula(vaka)] + [senaryo_dogrula(vaka, v) for v in vaka.get("varyantlar") or []]
    except RuntimeError as exc:
        return {"id": vid, "suite": vaka.get("suite"), "gecerli": False, "sorunlar": [str(exc)], "senaryolar": []}
    sorunlar = [s for sn in senaryolar for s in sn["sorunlar"]]
    return {"id": vid, "suite": vaka["suite"], "hata_sinifi": vaka["hata_sinifi"], "kaynak_not": vaka["kaynak_not"],
            "gecerli": not sorunlar, "sorunlar": sorunlar, "senaryolar": senaryolar}
