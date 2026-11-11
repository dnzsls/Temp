#!/usr/bin/env python3
"""
Sunum demosu — "Model Çalışırken Ne Oluyor"

Beş şeyi gerçek API çağrılarıyla gösterir:
  1. Girdi / çıktı token asimetrisi          -> slayt 9
  2. Konuşma uzadıkça girdinin birikmesi     -> slayt 8
  3. Prompt caching'in etkisi                -> slayt 8, üçüncü kart
  4. Görünmeyen düşünme token'ları           -> slayt 9, koyu kutu
  5. Türkçe ve İngilizce token farkı         -> slayt 8 (ücretsiz)

Kurulum:
    pip install anthropic
    API anahtarını bu dosyanın yanındaki API_KEY.txt içine yapıştır.

Çalıştırma:
    python3 token_demo.py          # hepsi, aralarda Enter bekler
    python3 token_demo.py 5 2 3    
    python3 token_demo.py 1 4      

Çıktının ekran görüntüsünü yedek olarak slayta koy — salonda ağ
çalışmazsa elinde kalsın.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("Önce kur:  pip install anthropic")

# --- AYARLAR -----------------------------------------------------------
# Orta kademe model: Gartner'ın "etkileşimlerin %70–80'i" dediği kademe.
MODEL = "claude-sonnet-5-5"

# Milyon token başına, dolar — Claude Sonnet 5.5 tarifesi. Slayt 9'daki
# 2,50 / 20 genel bir öncü model örneği; burada gerçek tarife kullanılıyor
# ki ekrandaki maliyet doğru olsun. Modeli değiştirirsen bunları da değiştir
# (Haiku 5.5: 0.10 / 0.50 / 0.01).
GIRDI_FIYAT = 2.00
CIKTI_FIYAT = 10.00
ONBELLEK_OKUMA_FIYAT = 0.20
ONBELLEK_YAZMA_FIYAT = GIRDI_FIYAT * 1.25  # 5 dakikalık önbellek

# Bu modelde düşünme varsayılan olarak açık ve düşünme token'ları
# output_tokens'a ekleniyor. Demo 1–3'te sayılar temiz çıksın diye
# kapatıyoruz; Demo 4 bilerek açık bırakıyor.
# Sonnet 5.5'te {"type": "disabled"} hata verir, kapatmanın yolu bu.
# Haiku 5.5'e geçersen {"type": "disabled"} yaz.
DUSUNME_KAPALI = {"type": "between_tools"}
# -----------------------------------------------------------------------

ANAHTAR_DOSYASI = Path(__file__).with_name("API_KEY.txt")


def anahtar_oku():
    # Önce dosyaya bak; yoksa terminalde tanımlı olana düş.
    if ANAHTAR_DOSYASI.exists():
        anahtar = ANAHTAR_DOSYASI.read_text(encoding="utf-8").strip()
    else:
        anahtar = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not anahtar.startswith("sk-ant-") or anahtar.startswith("sk-ant-..."):
        sys.exit(f"API anahtarı bulunamadı. {ANAHTAR_DOSYASI.name} dosyasını aç,\n"
                 "içindekini silip console.anthropic.com'dan aldığın anahtarı yapıştır.")
    return anahtar


client = Anthropic(api_key=anahtar_oku())


def usd(token, fiyat):
    return token / 1_000_000 * fiyat


def metin(cevap):
    # Yanıt birden çok blok içerebilir (düşünme, metin); metni bul.
    return next((b.text for b in cevap.content if b.type == "text"), "")


def token_say(t):
    # count_tokens ücretsizdir. Mesajın sabit ek yükünü düşmek için tek
    # karakterlik bir mesajla farkını alıyoruz.
    def ham(x):
        return client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": x}]
        ).input_tokens

    return max(ham(t) - ham(".") + 1, 1)


def baslik(metin):
    print("\n" + "=" * 68)
    print(metin)
    print("=" * 68)


# =======================================================================
# DEMO 1 — Girdi ucuz, çıktı pahalı
# =======================================================================
def demo1_asimetri():
    baslik("DEMO 1  ·  Aynı çağrı, girdi ve çıktı ayrı faturalanıyor")

    soru = "Faiz oranı artışının konut kredisi talebine etkisini 150 kelimeyle açıkla."

    cevap = client.messages.create(
        model=MODEL,
        max_tokens=1000,  # Türkçe kelime başına ~4 token; 150 kelime ~600 token
        thinking=DUSUNME_KAPALI,
        messages=[{"role": "user", "content": soru}],
    )

    g = cevap.usage.input_tokens
    c = cevap.usage.output_tokens

    print(f"\n  Girdi  : {g:>6} token   ->  ${usd(g, GIRDI_FIYAT):.5f}")
    print(f"  Çıktı  : {c:>6} token   ->  ${usd(c, CIKTI_FIYAT):.5f}")
    print(f"\n  Çıktı, girdinin {c / g:.1f} katı kadar token.")
    print(f"  Ama maliyeti {usd(c, CIKTI_FIYAT) / usd(g, GIRDI_FIYAT):.1f} katı.")
    print("\n  Sebep: girdi tek seferde işlenir, çıktı kelime kelime üretilir.")


# =======================================================================
# DEMO 2 — Konuşma uzadıkça her mesaj pahalılaşıyor
# =======================================================================
def demo2_baglam_birikimi():
    baslik("DEMO 2  ·  Her mesajda tüm geçmiş yeniden gidiyor")

    sorular = [
        "Merhaba, konut kredisi hakkında birkaç sorum olacak.",
        "Sabit faiz mi değişken faiz mi daha mantıklı?",
        "Peki erken kapama cezası nasıl işliyor?",
        "Vade uzatmanın toplam maliyete etkisi ne olur?",
        "Son olarak, kredi notu bu hesaba nasıl giriyor?",
    ]

    gecmis = []
    toplam_girdi = 0
    ilk_girdi = None
    onceki = 0  # bir önceki turda giden girdi + gelen çıktı

    print(f"\n  {'Tur':<5}{'Girdi token':>13}{'Çıktı token':>13}{'Artış':>9}{'Geçmiş payı':>14}")
    print("  " + "-" * 54)

    for i, soru in enumerate(sorular, 1):
        gecmis.append({"role": "user", "content": soru})

        cevap = client.messages.create(
            model=MODEL,
            max_tokens=150,
            thinking=DUSUNME_KAPALI,
            messages=gecmis,
        )

        g = cevap.usage.input_tokens
        c = cevap.usage.output_tokens
        toplam_girdi += g
        if ilk_girdi is None:
            ilk_girdi = g

        artis = f"{g / ilk_girdi:.1f}x" if i > 1 else "—"
        pay = f"%{onceki / g * 100:.0f}" if i > 1 else "—"
        print(f"  {i:<5}{g:>13}{c:>13}{artis:>9}{pay:>14}")
        onceki = g + c

        # modelin cevabını geçmişe ekle — bir sonraki turda o da gidecek
        gecmis.append({"role": "assistant", "content": metin(cevap)})

    print("  " + "-" * 54)
    print(f"  Toplam girdi: {toplam_girdi} token  ->  ${usd(toplam_girdi, GIRDI_FIYAT):.5f}")
    print("\n  Geçmiş payı: o turda gönderilen girdinin ne kadarı eski konuşma.")
    print("  Konuşma uzadıkça her mesaj biraz daha pahalı oluyor.")


# =======================================================================
# DEMO 3 — Prompt caching: sabit metni bir kez öde
# =======================================================================
def demo3_prompt_caching():
    baslik("DEMO 3  ·  Sabit sistem talimatı önbelleğe alınırsa")

    # Önbelleğin devreye girmesi için sistem talimatının yeterince uzun
    # olması gerekiyor (bu modelde en az 512 token). Burada gerçekçi bir
    # kurum talimatını tekrarlayarak o eşiği aşıyoruz.
    kural = (
        "Bir bankanın müşteri hizmetleri asistanısın. Yanıtlarında kesin faiz "
        "oranı, kesin vade ya da kişiye özel kredi limiti vaat etmezsin; bunlar "
        "şubeye veya uygulamadaki hesaplama aracına yönlendirilir. Müşterinin "
        "kimlik, hesap ve kart bilgilerini asla tekrar etmez, ekrana yazmazsın. "
        "Yatırım tavsiyesi vermez, ürün karşılaştırmasını yalnızca kamuya açık "
        "koşullar üzerinden yaparsın. Şikâyet içeren mesajlarda önce durumu "
        "özetler, sonra ilgili birime aktarıldığını belirtirsin. Resmî ve sade "
        "bir dil kullanır, teknik terimleri açıklarsın. "
    )
    # Prova ile sunum arasında 5 dakikadan az geçerse önbellek hâlâ dolu
    # olur ve ilk çağrı da "okunan" gösterir. Başa eklenen oturum etiketi
    # her çalıştırmayı boş önbellekle başlatır.
    oturum = f"Oturum {datetime.now():%H%M%S}.\n"
    sistem_talimati = oturum + kural * 20  # eşiği rahatça aşmak için

    def cagir(etiket):
        cevap = client.messages.create(
            model=MODEL,
            max_tokens=120,
            thinking=DUSUNME_KAPALI,
            system=[
                {
                    "type": "text",
                    "text": sistem_talimati,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": "Konut kredisi başvurusu için ne gerekiyor?"}],
        )
        u = cevap.usage
        yazma = getattr(u, "cache_creation_input_tokens", 0) or 0
        okuma = getattr(u, "cache_read_input_tokens", 0) or 0
        print(f"\n  [{etiket}]")
        print(f"    Normal girdi      : {u.input_tokens:>6} token")
        print(f"    Önbelleğe yazılan : {yazma:>6} token")
        print(f"    Önbellekten okunan: {okuma:>6} token")
        return yazma, okuma

    y1, o1 = cagir("1. çağrı — önbellek kuruluyor")
    y2, o2 = cagir("2. çağrı — önbellekten okunuyor")

    if o2 > 0:
        normal = usd(o2, GIRDI_FIYAT)
        onbellek = usd(o2, ONBELLEK_OKUMA_FIYAT)
        print(f"\n  Sistem talimatı ({o2} token) her istekte:")
        print(f"    önbelleksiz      : ${normal:.5f}")
        print(f"    önbellekten      : ${onbellek:.5f}   ({normal / onbellek:.0f} kat ucuz)")
        print(f"    bir kerelik yazma: ${usd(y1, ONBELLEK_YAZMA_FIYAT):.5f}   (%25 pahalı,"
              " ikinci istekte kendini çıkarır)")
        print("\n  Bin kullanıcı sorduysa sabit kısım bir kez yazılıp")
        print("  bin kez ucuza okunur. Cevabın kalitesi değişmez.")
    else:
        print("\n  Önbellek devreye girmedi — sistem talimatı eşiğin altında")
        print("  kalmış olabilir. `kural * 20` çarpanını artırıp tekrar dene.")


# =======================================================================
# DEMO 4 — Görünmeyen kalem: düşünme token'ları
# =======================================================================
def demo4_dusunme():
    baslik("DEMO 4  ·  Kısa cevap, uzun fatura: düşünme token'ları")

    # Tahminle değil ancak hesapla cevaplanabilen bir soru ki model her
    # çalıştırmada düşünsün; cevabı tek harf ki fark çarpıcı olsun.
    # Doğru cevap B — sorulursa kontrol için:
    #   A: 40.089 TL x 60 = 2.405.317 TL
    #   B: 38.090 TL x 60 + 80.000 = 2.365.396 TL
    soru = (
        "İki konut kredisi teklifi var, ikisi de 1.000.000 TL ve 60 ay vadeli, "
        "eşit taksitli. A: yıllık %42 faiz, masrafsız. B: yıllık %39 faiz, "
        "ayrıca 80.000 TL dosya masrafı. Toplam ödemesi daha düşük olan hangisi? "
        "Yalnızca A ya da B yaz, başka hiçbir şey yazma."
    )
    mesajlar = [{"role": "user", "content": soru}]

    cevap = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=mesajlar,
    )

    yazi = metin(cevap)
    faturalanan = cevap.usage.output_tokens

    gorunen = token_say(yazi)  # ekranda görünen metnin token sayısı
    gizli = max(faturalanan - gorunen, 0)

    print(f"\n  Cevap: {yazi.strip()}")
    print(f"\n  Ekranda gördüğün     : {gorunen:>6} token")
    print(f"  Faturalanan çıktı    : {faturalanan:>6} token   ->  ${usd(faturalanan, CIKTI_FIYAT):.5f}")
    print(f"  Görünmeyen düşünme   : {gizli:>6} token")
    print(f"\n  Ekranda gördüğün her 1 token için {gizli / gorunen:.0f} token düşünme ödendi.")
    print("  Hiç görmediğin metin, çıktı tarifesinden ödeniyor.")


# =======================================================================
# DEMO 5 — Aynı içerik, Türkçede kaç token?
# =======================================================================
def demo5_dil_farki():
    baslik("DEMO 5  ·  Aynı paragraf, iki dil, iki fatura")

    # Sunumun kendi konuşma metninden bir paragraf ve çevirisi.
    metinler = {
        "Türkçe": (
            "Şimdiye kadar sunucu tarafını konuştuk. Ama çoğunuzun kendi kartı "
            "yok, API kullanıyorsunuz. Peki anlattıklarım size ne işe yaradı? "
            "Şu işe yaradı: faturanızın neden böyle olduğunu artık biliyorsunuz. "
            "Her çubuk bir mesaj. Mavi kısım o turda yeniden gönderilen geçmiş, "
            "turuncu kısım o anki yeni mesajınız. Beşinci mesajda gönderdiğiniz "
            "verinin dörtte üçü eski konuşma ve her turda yeniden faturalanıyor."
        ),
        "İngilizce": (
            "So far we have talked about the server side. But most of you do not "
            "have your own card, you use the API. So what did all of this do for "
            "you? It did this: you now know why your bill looks the way it does. "
            "Each bar is one message. The blue part is the history resent in that "
            "turn, the orange part is your new message. By the fifth message, "
            "three quarters of what you send is old conversation, and it is billed "
            "again every turn."
        ),
    }

    print(f"\n  {'Dil':<11}{'Kelime':>8}{'Token':>8}{'Token / kelime':>17}")
    print("  " + "-" * 44)
    sonuc = {}
    for dil, t in metinler.items():
        kelime = len(t.split())
        token = token_say(t)
        sonuc[dil] = (kelime, token)
        print(f"  {dil:<11}{kelime:>8}{token:>8}{token / kelime:>17.1f}")
    print("  " + "-" * 44)

    tr_kelime, tr_token = sonuc["Türkçe"]
    en_kelime, en_token = sonuc["İngilizce"]
    print(f"\n  Aynı içerik Türkçede {tr_token / en_token:.1f} kat token tuttu.")
    def binlik(x):
        return f"{x:,.0f}".replace(",", ".")  # 3825 -> 3.825

    print(f"  1.000 kelimelik belge: Türkçe ~{binlik(tr_token / tr_kelime * 1000)} token,"
          f" İngilizce ~{binlik(en_token / en_kelime * 1000)} token.")
    print("\n  Token başına fiyat aynı, ama Türkçe aynı iş için daha çok token")
    print("  harcıyor. Bütçe hesabını İngilizce oranlarla yapma.")


# =======================================================================
DEMOLAR = {
    "1": demo1_asimetri,
    "2": demo2_baglam_birikimi,
    "3": demo3_prompt_caching,
    "4": demo4_dusunme,
    "5": demo5_dil_farki,
}

if __name__ == "__main__":
    secim = sys.argv[1:] or list(DEMOLAR)
    gecersiz = [s for s in secim if s not in DEMOLAR]
    if gecersiz:
        sys.exit(f"Bilinmeyen demo: {' '.join(gecersiz)}  (1–5 arası yaz)")

    print(f"\nModel: {MODEL}")
    try:
        for i, s in enumerate(secim):
            if i > 0 and sys.stdin.isatty():
                input("\n  [Enter] sonraki demo ...")
            DEMOLAR[s]()
    except Exception as hata:
        print("\n" + "!" * 68)
        print("API çağrısı başarısız oldu:")
        print(f"  {type(hata).__name__}: {hata}")
        print("\nSık görülen sebepler:")
        print("  · MODEL adı hesabında yok -> MODEL satırını değiştir")
        print("  · anahtar geçersiz ya da bakiye bitmiş")
        print("  · kurum ağı api.anthropic.com'u engelliyor")
        print("!" * 68 + "\n")
        sys.exit(1)

    print("\n" + "=" * 68)
    print("Bitti.")
    print("=" * 68 + "\n")
