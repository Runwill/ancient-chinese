import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


MODS = Path(r"E:\Minecraft\.minecraft\versions\1.21.11-Fabric-0.19.3\mods")
RESOURCEPACKS = Path(r"E:\Minecraft\.minecraft\versions\1.21.11-Fabric-0.19.3\resourcepacks")
OUT = Path(__file__).resolve().parents[1] / "NoN-Related-Mods-zh_CN-1.21.11" / "assets"

SOURCES = {
    "animationframework": [
        (MODS / "animationdirector-1.3.1.jar", "assets/animationframework/lang/en_us.json"),
    ],
    "needsofnature": [
        (MODS / "needsofnature-1.3.1.jar", "assets/needsofnature/lang/en_us.json"),
        (RESOURCEPACKS / "needs_of_nature_default_packv1.3.0.zip", "assets/needsofnature/lang/en_us.json"),
    ],
}

SENTINEL = "ZXQSEPZXQ"
PROTECT_RE = re.compile(
    r"https?://\S+|%\d*\$?[a-zA-Z]|%%|§.|<[^>]+>|\{[^{}]*\}|"
    r"NeedsOfNature|Needs of Nature|AnimationDirector|Animation Director|"
    r"AnimationFramework|Female Gender Mod|GeckoLib|Minecraft|Fabric|Mojang|OptiFine"
)

FIXED_TERMS = {
    "NeedsOfNature": "Needs of Nature",
    "Needs of Nature": "Needs of Nature",
    "AnimationDirector": "动画导演",
    "Animation Director": "动画导演",
    "AnimationFramework": "动画框架",
    "Female Gender Mod": "女性性别模组",
    "GeckoLib": "GeckoLib",
    "Minecraft": "Minecraft",
    "Fabric": "Fabric",
    "Mojang": "Mojang",
    "OptiFine": "OptiFine",
}


def read_json_from_zip(archive: Path, member: str) -> dict[str, str]:
    with zipfile.ZipFile(archive) as zf:
        with zf.open(member) as fp:
            return json.load(fp)


def protect(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        token = f"ZXQPH{len(replacements):04d}QXZ"
        original = match.group(0)
        replacements[token] = FIXED_TERMS.get(original, original)
        return token

    return PROTECT_RE.sub(repl, text), replacements


def restore(text: str, replacements: dict[str, str]) -> str:
    for token, original in replacements.items():
        text = re.sub(rf"\s*{re.escape(token)}\s*", original, text, flags=re.IGNORECASE)
    return text.strip()


def google_translate(text: str) -> str:
    query = urllib.parse.urlencode(
        {"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text}
    )
    request = urllib.request.Request(
        "https://translate.googleapis.com/translate_a/single?" + query,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            return "".join(segment[0] for segment in payload[0] if segment[0])
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Translation request failed: {last_error}")


def translate_batch(values: list[str]) -> list[str]:
    protected_values = []
    replacement_maps = []
    for value in values:
        protected, replacements = protect(value)
        protected_values.append(protected)
        replacement_maps.append(replacements)

    joined = f"\n{SENTINEL}\n".join(protected_values)
    translated = google_translate(joined)
    parts = re.split(rf"\s*{SENTINEL}\s*", translated, flags=re.IGNORECASE)
    if len(parts) != len(values):
        parts = [google_translate(value) for value in protected_values]
    return [restore(value, mapping) for value, mapping in zip(parts, replacement_maps)]


def translate_mapping(source: dict[str, str]) -> dict[str, str]:
    unique_values = list(dict.fromkeys(str(value) for value in source.values() if str(value)))
    translated_values: dict[str, str] = {"": ""}
    batch: list[str] = []
    batch_size = 0

    def flush() -> None:
        nonlocal batch, batch_size
        if not batch:
            return
        results = translate_batch(batch)
        translated_values.update(zip(batch, results))
        print(f"translated {len(translated_values) - 1}/{len(unique_values)}", flush=True)
        batch = []
        batch_size = 0

    for value in unique_values:
        projected = batch_size + len(value) + len(SENTINEL) + 2
        if batch and projected > 3000:
            flush()
        batch.append(value)
        batch_size += len(value) + len(SENTINEL) + 2
    flush()
    return {key: translated_values[str(value)] for key, value in source.items()}


def main() -> None:
    for namespace, archives in SOURCES.items():
        merged: dict[str, str] = {}
        for archive, member in archives:
            if not archive.exists():
                raise FileNotFoundError(archive)
            merged.update(read_json_from_zip(archive, member))
        print(f"{namespace}: {len(merged)} keys", flush=True)
        translated = translate_mapping(merged)
        destination = OUT / namespace / "lang" / "zh_cn.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {destination}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
