"""Declarative camera compatibility profiles; files cannot execute commands.

A profile can restrict measured capabilities, never grant a capability that the
driver did not verify on this device. New protocols still need a tested driver.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SUPPORTED_DRIVERS = {"openipc_ssh", "rtsp"}
MATCH_FIELDS = {"family", "model", "firmware", "soc", "sensor", "radio_driver"}
BUILTINS = (
    {"id": "openipc", "label": "OpenIPC / Majestic", "driver": "openipc_ssh", "match": {"family": "openipc"}},
    {"id": "rtsp", "label": "RTSP-камера", "driver": "rtsp", "match": {"family": "rtsp"}},
)


def load_profiles(folder: Path) -> list[dict]:
    profiles = [dict(profile) for profile in BUILTINS]
    identifiers = {p["id"] for p in profiles}
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        if path.stat().st_size > 65536:
            raise ValueError(f"Слишком большой профиль: {path.name}")
        profile = json.loads(path.read_text())
        if not isinstance(profile, dict) or set(profile) - {"schema", "id", "label", "driver", "match", "capabilities"}:
            raise ValueError(f"Неверный формат профиля: {path.name}")
        if profile.get("schema") != 1 or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", str(profile.get("id", ""))):
            raise ValueError(f"Неверная версия или имя профиля: {path.name}")
        if profile["id"] in identifiers or profile.get("driver") not in SUPPORTED_DRIVERS:
            raise ValueError(f"Дубликат или неподдерживаемый драйвер: {path.name}")
        match = profile.get("match")
        if not isinstance(match, dict) or not match.get("family") or set(match) - MATCH_FIELDS:
            raise ValueError(f"Неверные условия обнаружения: {path.name}")
        if not all(isinstance(v, str) and 0 < len(v) <= 128 for v in match.values()):
            raise ValueError(f"Неверное значение обнаружения: {path.name}")
        if not isinstance(profile.get("label"), str) or not 0 < len(profile["label"]) <= 80:
            raise ValueError(f"Неверное название: {path.name}")
        capabilities = profile.get("capabilities")
        if capabilities is not None and (not isinstance(capabilities, list) or
                not all(isinstance(v, str) and len(v) <= 80 for v in capabilities)):
            raise ValueError(f"Неверный список возможностей: {path.name}")
        identifiers.add(profile["id"])
        profiles.append(profile)
    return profiles


def resolve_profile(profiles: list[dict], observed: dict, verified_capabilities: list[str]) -> dict:
    matches = [p for p in profiles if all(observed.get(k) == v for k, v in p["match"].items())]
    if not matches:
        return {"id": "unknown", "label": "Неизвестная камера", "driver": None, "capabilities": []}
    matches.sort(key=lambda p: len(p["match"]), reverse=True)
    if len(matches) > 1 and len(matches[0]["match"]) == len(matches[1]["match"]):
        raise ValueError("Камере соответствуют несколько профилей; уточните модель в профиле")
    selected = dict(matches[0])
    allowed = selected.get("capabilities", verified_capabilities)
    selected["capabilities"] = sorted(set(verified_capabilities).intersection(allowed))
    return selected
