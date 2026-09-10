#!/usr/bin/env python3
import os
import re
import tomllib
from pathlib import Path

WEB = Path(os.environ["FANWAAVE_WEB"])
API = Path(os.environ["FANWAAVE_API"])
FLAGS_PIN = "b708a041531a830bd49f030250836896096e7abd"
LIB_PIN = "b7b0c79bf6c5c71a5508c12f25503ad001a1265e"


def load_toml(root: Path, name: str):
    with (root / name).open("rb") as handle:
        return tomllib.load(handle)


def cargo_text(root: Path) -> str:
    return (root / "Cargo.toml").read_text(encoding="utf-8")


def source_text(root: Path, name: str) -> str:
    return (root / name).read_text(encoding="utf-8")


def assert_pin(text: str, repo_fragment: str, pin: str):
    pattern = rf'{re.escape(repo_fragment)}[^\n]*rev\s*=\s*"{pin}"'
    if not re.search(pattern, text):
        raise AssertionError(f"missing immutable pin {pin} for {repo_fragment}")


def binding(config: dict, env_key: str) -> dict:
    matches = [item for item in config.get("env", []) if item.get("key") == env_key]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one binding for {env_key}, found {len(matches)}")
    return matches[0]


def assert_secret_env_only(root: Path, env_key: str):
    cli = load_toml(root, ".cli-flags.toml")
    domain = load_toml(root, ".fanwaave-cfg.toml")

    exposed = [
        name
        for name, spec in cli.get("flags", {}).items()
        if isinstance(spec, dict) and spec.get("env") == env_key
    ]
    if exposed:
        raise AssertionError(f"{env_key} is exposed through argv flag(s): {exposed}")

    item = binding(domain, env_key)
    if item.get("secret") is not True:
        raise AssertionError(f"{env_key} must be marked secret in .fanwaave-cfg.toml")
    if "default" in item:
        raise AssertionError(f"{env_key} must not have a plaintext TOML default")


def main():
    for root in (WEB, API):
        text = cargo_text(root)
        assert_pin(text, "flags-2-env", FLAGS_PIN)
        assert_pin(text, "fanwaave-lib-core", LIB_PIN)

        flags = source_text(root, "src/flags.rs")
        if "provided_flags" not in flags:
            raise AssertionError(f"{root.name} does not preserve explicit argv provenance")
        if "parsed.flags" in flags:
            raise AssertionError(f"{root.name} regressed to default-bearing parsed.flags")

        main_source = source_text(root, "src/main.rs")
        if "resolve_fanwaave_config" not in main_source:
            raise AssertionError(f"{root.name} is not using Fanwaave domain resolution")

    assert_secret_env_only(WEB, "FANWAAVE_DATABASE_URL")
    assert_secret_env_only(API, "FANWAAVE_NATS_URL")

    print("fanwaave flags/secret boundary canary: passed")


if __name__ == "__main__":
    main()
