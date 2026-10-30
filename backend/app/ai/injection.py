"""Deterministic prompt-injection signals (FR / EN / AR).

This is a warning for the reviewer, never the protection itself: whatever the email says, the model has
no tool, its output is a validated proposal, and every business action needs a human.
"""

import base64
import binascii
import re
import unicodedata

_PATTERNS: dict[str, re.Pattern] = {
    name: re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    for name, pattern in {
        "ignore_instructions": r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instruction|prompt|rule|previous|above)s?\b",
        "ignore_instructions_fr": r"\b(ignore[rz]?|oublie[rz]?)\b.{0,40}\b(instructions?|consignes?|règles?|précédent)",
        "ignore_instructions_ar": r"(تجاهل|انس).{0,40}(التعليمات|الأوامر|السابقة)",
        "role_override": r"\b(you are now|act as|tu es maintenant|agis comme|system prompt|developer mode|jailbreak)\b",
        "role_markers": r"(<\|?(system|assistant|im_start|im_end)\|?>|\[/?(system|inst)\]|^\s*(system|assistant)\s*:)",
        "forced_output": r"\b(confidence|review_confidence|self_reported_confidence)\b\"?\s*[:=]\s*\"?(high|1(\.0+)?)\b",
        "forced_action": r"\b(approve|create|convert|validate|valide[rz]?|approuve[rz]?|crée[rz]?|converti[rs]?)\b.{0,60}\b(automatically|automatiquement|without (human )?(review|validation)|sans (validation|vérification|revue))",
        "exfiltration": r"\b(send|forward|envoie[rz]?|transf[eè]re[rz]?)\b.{0,60}\b(list|liste|database|base de données|all students|tous les étudiants)\b",
        "delimiter_spoof": r"<<<\s*(end|email)_",
        "tool_call": r"\b(tool_calls?|function_call)\b",
    }.items()
}


def _base64_payloads(text: str) -> str:
    """Decodes long base64-looking runs so that encoded instructions are inspected too."""
    decoded = []
    for run in re.findall(r"[A-Za-z0-9+/]{24,}={0,2}", text)[:20]:
        try:
            value = base64.b64decode(run, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        decoded.append(value)
    return "\n".join(decoded)


def detect(text: str) -> list[str]:
    """Names of the injection patterns found in `text` (empty when nothing suspicious)."""
    text = unicodedata.normalize("NFKC", text or "")
    corpus = text + "\n" + _base64_payloads(text)
    return sorted(name for name, pattern in _PATTERNS.items() if pattern.search(corpus))
