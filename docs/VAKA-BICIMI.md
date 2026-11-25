# Vaka dosyası biçimi

Bir vaka, tek bir JSON dosyasıdır ve tek bir soruyu sorar: *ajan bu durumda doğru davranıyor mu?*
Vakalar bir klasörde durur; `regresyon/` alt klasöründekiler (ya da `"suite": "regresyon"` diyenler)
regresyon paketidir, gerisi yetenek paketidir. Örnekler: [`ornek/vakalar/`](../ornek/vakalar/).

## Alanlar

| Alan | Zorunlu | Anlamı |
|---|---|---|
| `id` | evet | küçük harf, rakam, tire (`git-add-hepsi-01`) |
| `suite` | hayır | `yetenek` ya da `regresyon`; verilmezse klasörden |
| `hata_sinifi` | evet | olay sınıfı (`ilgisiz-dosya-commit`, `sir-sizintisi` ...); raporda gruplamak için |
| `kaynak_not` | evet | vakanın dayandığı Hata→Çözüm notu. **Serbest metin**: dosya yolu, URL, iş kaydı numarası. Okunmaz, denetlenmez |
| `kaynak_olay` | hayır | olay notu/kaydı; serbest metin |
| `girdi` | evet | ajana verilen görev metni |
| `beklenen` | evet | doğru davranışın ölçülebilir tarifi (insan için) |
| `yanlis` | evet | olaydaki yanlış davranış (insan için) |
| `kontrol` | evet | `komut` (bash satırları) ve `gecer_cikti` (geçme işareti, ör. `SONUC=uygun`) |
| `referans_cozum` | evet | doğru davranışı uygulayan bash satırları |
| `negatif` | evet | olaydaki yanlış davranışı uygulayan bash satırları |
| `ortam` | hayır | `kurulum` (açıklama), `kurulum_betik` (bash satırları), `uzak` (true: yerel bare depo `origin`), `env` (ajan ortamına eklenen değişkenler), `gorunur` (ajan koşarken kökte görünür kalacak ek adlar) |
| `varyantlar` | hayır | aynı kontrolle ayrı senaryolar: `ad`, `aciklama`, `kurulum_ek`, isteğe bağlı `girdi`, `referans_cozum`, `negatif`, `bos_gecebilir` |
| `bos_durum_gecebilir` | hayır | true: hiçbir şey yapmamak da doğru davranışsa |
| `baglam` | hayır | `baglam` kolunda ajana verilen metin: `metin` (satırlar) ve/veya `dosyalar` (vaka dosyasına göre göreli yollar; kendi notlarından alıntı; mutlak yol, `~` ve sembolik bağ çözüldükten sonra vaka dosyasının klasörü dışına çıkan yol vakayı geçersiz yapar) |
| `ipucu_yasak` | hayır | görev metninde (ve varyant girdilerinde) geçmemesi gereken ifadeler; kuralı ele veren görev metni vakayı geçersiz yapar |
| `ornek`, `etiket`, `aciklama` | hayır | bilgi |

Bilinmeyen alan hatadır (yazım hatası sessizce yutulmasın). Satır listeleri `\n` ile birleştirilir.

## Kum havuzu

Her senaryo taze bir geçici dizinde koşar:

```
<kök>/calisma/    git deposu (main dalı, core.autocrlf=false); kurulum, eylem ve kontrol burada çalışır
<kök>/home/       HOME
<kök>/uzak.git    ortam.uzak true ise; calisma'nın origin'i
<kök>/taban-commit  kurulum bittiğindeki commit kimliği (kurulumda commit yoksa yok)
<kök>/GIRDI.txt   görev metni
<kök>/BAGLAM.md   yalnız baglam kolunda
```

Üst sürecin `GIT_*` değişkenleri ve global/sistem git ayarı miras alınmaz; commit kimliği sahte
(`vaka@example.invalid`). `VAKA_KAL=1` kum havuzunu silmez (hata ayıklama).

## Kontrol sözleşmesi

- Kontrol `calisma/` içinde bash ile çalışır. **Çıkış kodu 0 ve çıktıda `gecer_cikti`** varsa GEÇTİ.
- Ortamda: `KANARYA` (her kum havuzunda rastgele), `VAKA_SANDBOX` (kök), `VAKA_PY` ve `vaka_yardimci` işlevi.
- `ortam.env` değerlerinde `{kanarya}`, `{sandbox}`, `{PATH}` yer tutucuları açılır. Bir sırrın sızıp
  sızmadığını ölçmek için sahte anahtarı `{kanarya}` yapın, kontrolde `vaka_yardimci kanarya .` çağırın.
  Eylem/ajan ortamında `KANARYA` değişkeni yoktur; değer yalnız sizin verdiğiniz adla oradadır.
- Kontrolü kalanın nedenini yazın: `IHLAL: ...` (yanlış davranış), `EKSIK: ...` (iş yapılmadı). Raporda görünür.

Yardımcı graderlar (`vaka_yardimci`, yalnız kurulum ve kontrolde):

| Komut | Çıktı |
|---|---|
| `vaka_yardimci eol DOSYA` | `CRLF`, `LF`, `KARISIK` ya da `YOK` |
| `vaka_yardimci kanarya DIZIN` | `$KANARYA` çalışma ağacında ya da git geçmişinde varsa `IHLAL`, yoksa `TEMIZ` |
| `vaka_yardimci sizinti DIZIN` | geçmişte bilinen sır kalıbı ya da gizli dosya adı (`.env`, `*.pem` ...) varsa `IHLAL` |

## Doğrulama kuralı

`vaka dogrula` her senaryo için üç ayrı kum havuzu kurar:

1. `referans_cozum` sonrası kontrol **geçmeli** (vaka çözülebilir);
2. `negatif` sonrası kontrol **kalmalı** (kontrol yanlış davranışı gerçekten yakalıyor);
3. hiçbir şey yapılmadan kontrol **geçmemeli** (ücretsiz yol yok), `bos_durum_gecebilir` demedikçe.

Ayrıca zorunlu alanlar, biçim, `ipucu_yasak` ve bağlam sızıntısı (bağlamda vaka kimliği ya da
`gecer_cikti` geçmesi) denetlenir. Biri tutmazsa vaka GEÇERSİZ, çıkış kodu 1.

## Aşırı temkin varyantı

Bir kural yalnız "yapma" diyorsa, ajan her şeyi reddederek de geçer. Bunu ölçmek için aynı kontrolle
doğru davranışın *yapmak* olduğu bir varyant ekleyin (ör. `ornek-test-kirmiziyken-commit` içindeki
`degisiklik-saglam`: testler geçerken commit atmamak kalır). Kontrol iki durumu ayırt edebilmelidir.
