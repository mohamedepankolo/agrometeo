"""transcribe_all.py — transcrit tous les audios de reference_pairs/ via l'ASR mooré.
Découpe en morceaux de <=120s (limite empirique constatée du service ASR) et
recolle les transcriptions. Sauvegarde un .txt par audio dans reference_pairs/transcripts/.
"""
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    # Sans ça, un print() sur du texte mooré (ɩ, ẽ, ʋ...) plante sur la console Windows
    # (cp1252) : l'exception est alors avalée par le `except` plus bas, qui écrit un message
    # d'erreur à la place de la VRAIE transcription pourtant bien reçue. Perte de données silencieuse.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from moore_client import MooreClient

HERE = Path(__file__).parent
WAV_DIR = HERE / "wav"
OUT_DIR = HERE / "transcripts"
OUT_DIR.mkdir(exist_ok=True)

CHUNK_S = 110  # marge de sécurité sous la limite de 120s observée


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def extract_chunk(src: Path, start: float, duration: float | None, dst: Path) -> None:
    cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", str(src)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-ar", "16000", "-ac", "1", str(dst), "-loglevel", "error"]
    subprocess.run(cmd, check=True)


def main() -> None:
    mc = MooreClient()
    wav_files = sorted(p for p in WAV_DIR.glob("*.wav") if not p.name.startswith(("clip", "_")))

    for wav in wav_files:
        out_path = OUT_DIR / (wav.stem + ".txt")
        if out_path.exists():
            print(f"[skip] {wav.name} (déjà fait)")
            continue

        duration = ffprobe_duration(wav)
        print(f"== {wav.name} ({duration:.0f}s) ==")

        pieces = []
        start = 0.0
        tmp = HERE / "wav" / "_chunk_tmp.wav"
        while start < duration:
            extract_chunk(wav, start, CHUNK_S, tmp)
            try:
                text = mc.asr_moore(str(tmp))
            except Exception as exc:
                text = f"[ERREUR à {start:.0f}s: {exc}]"
            # Le print() est séparé de l'appel ASR : un problème d'affichage (encodage console
            # Windows sur les caractères mooré) ne doit jamais faire perdre une transcription
            # déjà reçue avec succès.
            pieces.append(text)
            try:
                print(f"  [{start:.0f}s+] {text[:80]}...", flush=True)
            except Exception:
                print(f"  [{start:.0f}s+] (texte reçu, non affichable sur cette console)", flush=True)
            start += CHUNK_S

        out_path.write_text("\n\n---\n\n".join(pieces), encoding="utf-8")
        print(f"  -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
