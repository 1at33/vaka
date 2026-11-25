"""Sert maliyet sınırı; uçuştaki koşulara duyarlı, paralel süreçler arasında ortak defter.

Kural: bir koşu yalnız  harcanan + uçuştaki rezervler + tahmin <= sınır  ise başlar. `tahmin`, gözlenen
koşu maliyetlerinin ortalamasıdır; gözlem yoksa tohum (`tahmini_kosu_usd`). Kontrol ve rezerv tek kilit
altında yapılır: iki süreç aynı boşluğu kapamaz.

Maliyet bildirmeyen koşu (ajan son satırında `maliyet_usd` vermedi) tahmin kadar harcanmış sayılır: bütçe
yine dolar, sınır koşu sayısı sınırı gibi çalışır.

Defter satırları: `S <kimlik> <rezerv>` başlangıç, `E <kimlik> <usd>` bildirilen harcama, `T <kimlik> <usd>`
tahminle sayılan harcama (ortalamaya girmez); ikisi de koşuyu uçuştan çıkarır.
Kilit: Linux/macOS `fcntl.flock`, Windows `msvcrt.locking`.
"""
import os
import secrets
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

# Windows bayt kilitleri zorunludur; veri bölgesinin çok ötesindeki tek bayt kilitlenir.
_WIN_KILIT_OFSET = 0x7FFFFFFF


def _kilitle(f):
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_EX)
        return None
    fd = os.open(f.name, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        while True:
            os.lseek(fd, _WIN_KILIT_OFSET, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return fd
            except OSError:
                time.sleep(0.005)
    except BaseException:
        os.close(fd)
        raise


def _birak(f, fd):
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_UN)
        return
    try:
        f.flush()
        os.lseek(fd, _WIN_KILIT_OFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


class Butce:
    def __init__(self, sinir, defter, tahmini_kosu_usd=0.01):
        self.sinir = float(sinir)
        if self.sinir < 0:
            raise ValueError("bütçe sınırı negatif olamaz")
        self.tahmin0 = float(tahmini_kosu_usd)
        self.defter = Path(defter)
        self.defter.parent.mkdir(parents=True, exist_ok=True)
        self.defter.touch()

    @staticmethod
    def _coz(icerik):
        harcanan, ucus, gozlem = 0.0, {}, []
        for satir in icerik.splitlines():
            p = satir.split()
            if len(p) == 3 and p[0] == "S":
                ucus[p[1]] = float(p[2])
            elif len(p) == 3 and p[0] in ("E", "T"):
                usd = float(p[2])
                harcanan += usd
                ucus.pop(p[1], None)
                if p[0] == "E" and usd > 0:
                    gozlem.append(usd)
        return harcanan, ucus, gozlem

    def _tahmin(self, gozlem):
        return sum(gozlem) / len(gozlem) if gozlem else self.tahmin0

    def _kilitli(self, islem):
        with open(self.defter, "a+", encoding="utf-8") as f:
            kilit = _kilitle(f)
            try:
                f.seek(0)
                durum = self._coz(f.read())
                satirlar = islem(*durum)
                if satirlar:
                    f.write("".join(x + "\n" for x in satirlar))
                    f.flush()
                    f.seek(0)
                    durum = self._coz(f.read())
                return durum
            finally:
                _birak(f, kilit)

    def harcanan(self):
        return self._kilitli(lambda h, u, g: None)[0]

    def ucustaki(self):
        return len(self._kilitli(lambda h, u, g: None)[1])

    def tahmin(self):
        return self._tahmin(self._kilitli(lambda h, u, g: None)[2])

    def baslat(self):
        """Atomik kontrol + rezerv. Kimlik ya da sığmıyorsa None (koşu BAŞLATILMAZ)."""
        kimlik = secrets.token_hex(6)
        sonuc = {}

        def islem(h, u, g):
            rezerv = self._tahmin(g)
            if h + sum(u.values()) + rezerv > self.sinir + 1e-12:
                return None
            sonuc["id"] = kimlik
            return [f"S {kimlik} {rezerv!r}"]

        self._kilitli(islem)
        return sonuc.get("id")

    def bitir(self, kimlik, usd):
        """Koşu bitti: maliyeti yaz, rezervi bırak. usd None ise (bildirilmedi) tahmin kadar sayılır."""
        def islem(h, u, g):
            if usd is None:
                return [f"T {kimlik} {self._tahmin(g)!r}"]
            return [f"E {kimlik} {float(usd)!r}"]
        return self._kilitli(islem)[0]

    def iptal(self, kimlik):
        """Koşu hiç başlamadı (ör. kurulum hatası): rezervi bırak, harcama yok."""
        return self._kilitli(lambda h, u, g: [f"E {kimlik} 0.0"])[0]
