import argparse
import yt_dlp
import re
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

from deep_translator import GoogleTranslator
import time


# -----------------------------------------------------------
# 🟩 Взема заглавие на видеото
# -----------------------------------------------------------

def get_video_title(video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {'quiet': True, 'skip_download': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download = False)
        return info.get('title', 'unknown_video').replace('/','-')
    

# -----------------------------------------------------------
# 🟨 Сваляне на видео с избрано качество
# -----------------------------------------------------------

def download_video(video_id: str, quality: str = "best[height<=720]"):
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Вземаме информация за видеото (за безопасно заглавие)
    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', 'unknown_video')
    
    # Почистваме заглавието от недопустими символи
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)

    # Настройка за изходното име на файла: title + video_id
    outtmpl = f"{safe_title}_{video_id}.%(ext)s"
    
    ydl_opts = {
        'format': quality,
        'outtmpl': outtmpl,
        'merge_output_format': 'mp4',
        'noplaylist': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        print(f"✅ Видео свалено: {info.get('title', 'Неизвестно видео')}")


# -----------------------------------------------------------
# 🟦 Сваляне на транскрипция
# -----------------------------------------------------------        

def download_transcript(video_id, language="en", translate=None, chunk_size=4500, delay=0.2):
    """
    Извлича транскрипцията и я превежда, ако translate_to е зададен.
    Съвместимо с новия youtube-transcript-api (v0.6+)
    Изтегля и по желание превежда транскрипцията на YouTube видео.
    
    :param video_id: ID на видеото
    :param lang: език на оригиналната транскрипция (по подразбиране 'en')
    :param translate: език за превод (пример: 'bg')
    :param output_file: име на файла за запис (пример: 'transcript.txt')
    """
    print(f"🎬 Изтегляне на транскрипция за видео {video_id}...")

    # Вземаме заглавието  
    try:
        title = get_video_title(video_id)
    except Exception as e:
        print(f"⚠️ Не може да се вземе заглавие на видеото: {e}")
        title = "unknown_video"

    # Почиства заглавието от символи, неподходящи за файлове
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)

    # Уверяваме се, че директорията съществува
    #os.makedirs(output_dir, exist_ok=True)

    # --------------------------------------
    # Вземане на оригиналната транскрипция
    # --------------------------------------
    yt = YouTubeTranscriptApi()
    try:
        transcript = yt.fetch(video_id, languages=[language])
    except TranscriptsDisabled:
        print("❌ Това видео няма включени субтитри.")
        return None, None
    except NoTranscriptFound:
        print(f"❌ Няма налична транскрипция за езика '{language}'.")
        return None, None
    except Exception as e:
        print(f"❌ Грешка при изтеглянето: {e}")
        return None, None
    
    # Извличаме текста от обектите
    original_lines = [snippet.text.strip() for snippet in transcript if snippet.text.strip()]
    original_text = " ".join(original_lines)

    # Уверяваме се, че директорията съществува
    #os.makedirs(output_dir, exist_ok=True)
    
    # Файл за оригинала
    original_file = f"{safe_title}_original_{video_id}.txt"
    # записваме оригиналния текст
    with open(original_file, "w", encoding="utf-8") as f:
        f.write(original_text)
    print(f"✅ Оригиналната транскрипция е запазена като: {original_file}")

    # --------------------------------------
    # Превод (по избор)
    # --------------------------------------
    translated_text = None

    # Ако има заявен превод
    if translate:
        print(f"🌐 Превеждане на транскрипцията към '{translate}' (chunk_size={chunk_size}, delay={delay})...")
        # Създаваме translator; ако lang е None или 'auto' може да се използва 'auto'
        src = language if language else "auto"
        translator = GoogleTranslator(source=src, target=translate)

        # превеждаме по chunks -> получаваме преведени lines
        translated_lines = _translate_chunks(original_lines, translator, chunk_size=chunk_size, delay=delay)

        # сглобяване и запис
        translated_text = " ".join(translated_lines)
        translated_file = f"{safe_title}_translated_{translate}_{video_id}.txt"
        with open(translated_file, "w", encoding="utf-8") as f:
            f.write(translated_text)
            print(f"✅ Преведената транскрипция е запазена като: {translated_file}")

#        try:
#            translator = GoogleTranslator(source=language, target=translate)
#            translated_text = translator.translate(original_text)
#
#            translated_file = f"{title}_translated_{translate}.txt"
#            with open(translated_file, encoding="utf-8") as f:
#                f.write(translated_text)
#            print(f"✅ Преведената транскрипция е запазена като: {translated_file}")
#
#        except Exception as e:
#            print(f"⚠️ Грешка при превода: {e}")


def _translate_chunks(lines, translator, chunk_size=4500, delay=0.2):
    """
    Вътрешна помощна функция:
    - lines: списък от short text snippets (strings)
    - translator: екземпляр GoogleTranslator(source=..., target=...)
    - chunk_size: макс. брой символи на chunk (за safety оставяме < 5000)
    - delay: пауза в секунди между заявките (rate-limit)
    Връща списък translated_lines съответстващ на lines.
    """
    SEP = "|||+++|||"
    n = len(lines)
    translated_lines = []
    i = 0

    while i < n:
        # Сглобяваме chunk от няколко реда, без да надвишаваме chunk_size 
        j = i + 1
        chunk_items = [lines[i]]
        cur_len = len(lines[i])

        while j < n and (cur_len + len(SEP) + len(lines[j])) <= chunk_size:
            cur_len += len(SEP) + len(lines[j])
            chunk_items.append(lines[j])
            j += 1

        chunk_text = SEP.join(chunk_items)

        try:
            translated_chunk = translator.translate(chunk_text)
            # Опитваме да разделим обратно по SEP
            parts = translated_chunk.split(SEP)
            if len(parts) == len(chunk_items):
                translated_lines.extend(parts)
            else:
                # Нещо се е променило при превода (SEP премахнат/променен) -> fallback
                # Ако Google Translate промени разделителя
                print(f"⚠️ Непълен chunk [{i}:{j}] — fallback по редове")
                for item in chunk_items:
                    try:
                        translated_lines.append(translator.translate(item))
                    except Exception as e2:
                        print(f"❗ Проблем при превод на ред: {e2}")
                        translated_lines.append(item)
                    time.sleep(delay)
        except Exception as e:
            # fallback: превеждаме поединично
            print(f"⚠️ Грешка при превод на chunk [{i}:{j}] — {e}")
            # fallback: превеждаме всеки ред поотделно
            for item in chunk_items:
                try:
                    translated_lines.append(translator.translate(item))
 
                except Exception as e2:
                    print(f"❗ Проблем при превод на ред: {e2}")
                    translated_lines.append(item)
                time.sleep(delay)

        # пауза между chunk-ове
        i = j
        time.sleep(delay)

    return translated_lines


# -----------------------------------------------------------
# ⚙️ Главна функция с argparse
# -----------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description='🎬 YouTube Video & Transcript Downloader'
    )
    parser.add_argument(
        "--id",
        required=True,
        help="YouTube video ID (пример: dQw4w9WgXcQ)"
    )
    parser.add_argument(
        "--action",
        choices=["video","transcript", "both"],
        default="both",
        help="Действие: 'video', 'transcript' или 'both' (по подразбиране: both)"
    )
    parser.add_argument(
        "--quality",
        choices=["best", "1080p", "720p", "480p", "audio"],
        default="720p",
        help="Качество на видеото: best, 1080p, 720p, 480p, audio (по подразбиране: 720p)"
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Езикът на оригиналната транскрипция (напр. en, es, fr, bg). По подразбиране: en."
    )
    parser.add_argument(
        "--translate",
        help="Преведи транскрипцията към избрания език (пример: bg, fr, de). Ако не е зададено, няма превод."
    )

    args = parser.parse_args()

    # Мапване на изборите към yt-dlp формати
    quality_map = {
        "best": "best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
        "audio": "bestaudio[ext=m4a]",
    }

    # Изпълнение според избраното действие
    if args.action in ["video", "both"]:
        download_video(args.id, quality_map[args.quality])

    if args.action in ["transcript", "both"]:
        download_transcript(args.id, args.lang, args.translate)

    print("\n✅ Готово!")        


if __name__ == "__main__":
    main()    