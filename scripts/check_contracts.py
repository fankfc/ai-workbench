"""Generate D007 schemas or check persisted schemas without modifying them."""
import argparse
import json
from pathlib import Path

from app.contracts.artifacts import ArtifactVersion, DeliveryBundle
from app.contracts.events import InternalEventRecord, MessageRecord, PublicEvent
from app.contracts.providers import AgentRequestRecord, ProviderContract, RouteSnapshot, SCHEMA_VERSION
from app.contracts.translation import TranslationBlock, TranslationJob, TranslationQA

ROOT = Path(__file__).resolve().parents[1]


def generated_schemas() -> dict[str, dict]:
    public = PublicEvent.model_json_schema()
    provider = ProviderContract.model_json_schema()
    definitions = provider.setdefault("$defs", {})
    for model in (RouteSnapshot, AgentRequestRecord, InternalEventRecord, MessageRecord,
                  TranslationJob, TranslationBlock, TranslationQA, ArtifactVersion, DeliveryBundle):
        schema = model.model_json_schema()
        for name, definition in schema.pop("$defs", {}).items():
            if name in definitions and definitions[name] != definition:
                raise ValueError(f"SCHEMA_DEFINITION_COLLISION:{name}")
            definitions[name] = definition
        definitions[model.__name__] = schema
    values = {"public-events.schema.json": public, "provider.schema.json": provider}
    for filename, schema in values.items():
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:ai-workbench:contracts:{SCHEMA_VERSION}:{filename}"
        schema["x-contract-version"] = SCHEMA_VERSION
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--strict", action="store_true")
    parser.add_argument("--schema-dir", type=Path, default=ROOT / "packages" / "contracts")
    args = parser.parse_args(argv)
    errors = []
    for name, expected in generated_schemas().items():
        path = args.schema_dir / name
        if args.write:
            args.schema_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"SCHEMA_WRITTEN:{name}")
            continue
        try:
            actual = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"SCHEMA_UNREADABLE:{name}:{type(exc).__name__}")
            continue
        if actual != expected:
            errors.append(f"SCHEMA_DRIFT:{name}")
    for error in errors:
        print(error)
    if errors:
        return 1
    print(f"CONTRACTS_OK:version={SCHEMA_VERSION};schemas=2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
